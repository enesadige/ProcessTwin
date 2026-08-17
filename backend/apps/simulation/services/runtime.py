from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from django.db import transaction
from django.utils.dateparse import parse_datetime

from apps.simulation.models import (
    SimulationComparisonRole,
    SimulationRun,
    SimulationRunEvent,
    SimulationRunStatus,
    SimulationScenario,
)


class SimulationRuntimeError(Exception):
    """Base exception for simulation-local runtime operations."""


class SimulationLifecycleError(SimulationRuntimeError):
    """Raised when a requested transition is not valid for a run."""


class SimulationService:
    """Deterministic runtime for isolated ProcessTwin simulation records.

    The service deliberately produces only ``SimulationRun`` and
    ``SimulationRunEvent`` records. Domain event, alarm, outage, impact, rule,
    and compensation execution are introduced by later ProcessTwin tasks.
    """

    _TERMINAL_STATUSES = frozenset(
        {
            SimulationRunStatus.COMPLETED,
            SimulationRunStatus.FAILED,
            SimulationRunStatus.STOPPED,
        }
    )

    def create_run(
        self,
        *,
        scenario: SimulationScenario,
        comparison_role: str,
        deterministic_seed: str,
        virtual_clock: datetime,
        input_parameters: dict[str, Any] | None = None,
        baseline_run: SimulationRun | None = None,
        speed_multiplier: int = 1,
    ) -> SimulationRun:
        """Create an isolated baseline or candidate context from one scenario."""
        if comparison_role not in SimulationComparisonRole.values:
            raise SimulationRuntimeError("Unknown simulation comparison role.")
        if comparison_role == SimulationComparisonRole.BASELINE and baseline_run is not None:
            raise SimulationRuntimeError("Baseline runs cannot reference a baseline run.")
        if comparison_role == SimulationComparisonRole.CANDIDATE and baseline_run is None:
            raise SimulationRuntimeError("Candidate runs require a baseline run.")

        return SimulationRun.objects.create(
            source_snapshot=scenario.source_snapshot,
            scenario=scenario,
            comparison_role=comparison_role,
            baseline_run=baseline_run,
            deterministic_seed=deterministic_seed,
            virtual_clock=virtual_clock,
            speed_multiplier=speed_multiplier,
            input_parameters=copy.deepcopy(input_parameters or {}),
        )

    def create_candidate(
        self,
        *,
        baseline_run: SimulationRun,
        input_overrides: dict[str, Any] | None = None,
        speed_multiplier: int | None = None,
    ) -> SimulationRun:
        """Create a candidate that shares immutable baseline context only."""
        baseline_run = self._load_run(baseline_run)
        if baseline_run.comparison_role != SimulationComparisonRole.BASELINE:
            raise SimulationRuntimeError("Candidates can only be created from a baseline run.")
        if baseline_run.status not in {SimulationRunStatus.DRAFT, SimulationRunStatus.READY}:
            raise SimulationLifecycleError(
                "Candidates must be created before their baseline starts advancing."
            )
        return self.create_run(
            scenario=baseline_run.scenario,
            comparison_role=SimulationComparisonRole.CANDIDATE,
            baseline_run=baseline_run,
            deterministic_seed=baseline_run.deterministic_seed,
            virtual_clock=baseline_run.virtual_clock,
            speed_multiplier=speed_multiplier or baseline_run.speed_multiplier,
            input_parameters=input_overrides,
        )

    def effective_inputs(self, simulation_run: SimulationRun) -> dict[str, Any]:
        """Merge defaults and run-local overrides without mutating either source."""
        run = self._load_run(simulation_run)
        return self._deep_merge(run.scenario.default_parameters, run.input_parameters)

    def prepare(self, simulation_run: SimulationRun) -> SimulationRun:
        """Persist deterministic starting context without advancing virtual time."""
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status not in {SimulationRunStatus.DRAFT, SimulationRunStatus.READY}:
                raise SimulationLifecycleError("Only draft or ready runs can be prepared.")

            self._assert_snapshot_context(run)
            context = copy.deepcopy(run.lifecycle_context)
            initial_clock = self._initial_clock(run)
            effective_inputs = self._deep_merge(
                run.scenario.default_parameters,
                run.input_parameters,
            )
            context.update(
                {
                    "initial_virtual_clock": initial_clock.isoformat(),
                    "effective_inputs": effective_inputs,
                    "effective_input_fingerprint": self._fingerprint(effective_inputs),
                }
            )
            run.lifecycle_context = context
            run.status = SimulationRunStatus.READY
            run.save(update_fields=["lifecycle_context", "status", "updated_at"])
            return run

    def start(self, simulation_run: SimulationRun) -> SimulationRun:
        """Start a prepared run and append a deterministic runtime event."""
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status == SimulationRunStatus.DRAFT:
                run = self._prepare_locked(run)
            elif run.status != SimulationRunStatus.READY:
                raise SimulationLifecycleError("Only draft or ready runs can be started.")

            run.status = SimulationRunStatus.RUNNING
            run.save(update_fields=["status", "updated_at"])
            self._append_event(run, event_type="runtime_started")
            return run

    def pause(self, simulation_run: SimulationRun) -> SimulationRun:
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status != SimulationRunStatus.RUNNING:
                raise SimulationLifecycleError("Only running simulations can be paused.")
            run.status = SimulationRunStatus.PAUSED
            run.save(update_fields=["status", "updated_at"])
            self._append_event(run, event_type="runtime_paused")
            return run

    def resume(self, simulation_run: SimulationRun) -> SimulationRun:
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status != SimulationRunStatus.PAUSED:
                raise SimulationLifecycleError("Only paused simulations can be resumed.")
            run.status = SimulationRunStatus.RUNNING
            run.save(update_fields=["status", "updated_at"])
            self._append_event(run, event_type="runtime_resumed")
            return run

    def stop(self, simulation_run: SimulationRun) -> SimulationRun:
        """Finish a mutable run without modifying its simulation history."""
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status not in {SimulationRunStatus.RUNNING, SimulationRunStatus.PAUSED}:
                raise SimulationLifecycleError("Only running or paused simulations can be stopped.")
            run.status = SimulationRunStatus.STOPPED
            run.save(update_fields=["status", "updated_at"])
            self._append_event(run, event_type="runtime_stopped")
            return run

    def record_domain_event(
        self,
        simulation_run: SimulationRun,
        *,
        event_type: str,
        occurred_at: datetime,
        context: dict[str, Any],
    ) -> SimulationRunEvent:
        """Append a simulation-local domain event at an explicit virtual time."""
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status != SimulationRunStatus.RUNNING:
                raise SimulationLifecycleError("Only running simulations can record domain events.")
            if occurred_at < run.virtual_clock:
                raise SimulationRuntimeError("Domain events cannot precede the virtual clock.")
            return self._append_event(
                run,
                event_type=event_type,
                context=copy.deepcopy(context),
                occurred_at=occurred_at,
            )

    def complete(self, simulation_run: SimulationRun, *, completed_at: datetime) -> SimulationRun:
        """Complete a run at a deterministic virtual timestamp."""
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status != SimulationRunStatus.RUNNING:
                raise SimulationLifecycleError("Only running simulations can be completed.")
            if completed_at < run.virtual_clock:
                raise SimulationRuntimeError("Completion cannot precede the virtual clock.")
            run.virtual_clock = completed_at
            run.status = SimulationRunStatus.COMPLETED
            run.save(update_fields=["virtual_clock", "status", "updated_at"])
            self._append_event(run, event_type="runtime_completed")
            return run

    def advance(
        self,
        simulation_run: SimulationRun,
        *,
        simulation_step: timedelta,
    ) -> SimulationRun:
        """Advance the virtual clock by the supplied step times the run speed."""
        if not isinstance(simulation_step, timedelta) or simulation_step <= timedelta(0):
            raise SimulationRuntimeError("simulation_step must be a positive timedelta.")

        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status != SimulationRunStatus.RUNNING:
                raise SimulationLifecycleError("Only running simulations can advance time.")

            run.virtual_clock = run.virtual_clock + (simulation_step * run.speed_multiplier)
            context = copy.deepcopy(run.lifecycle_context)
            context["advance_count"] = int(context.get("advance_count", 0)) + 1
            run.lifecycle_context = context
            run.save(update_fields=["virtual_clock", "lifecycle_context", "updated_at"])
            self._append_event(
                run,
                event_type="runtime_tick",
                context={
                    "base_step_microseconds": self._timedelta_microseconds(simulation_step),
                    "speed_multiplier": run.speed_multiplier,
                },
            )
            return run

    def reset(self, simulation_run: SimulationRun) -> SimulationRun:
        """Reset only non-terminal, simulation-local runtime state.

        Terminal history is preserved by rejecting reset; callers must create a
        replay instead. No operational records are ever affected.
        """
        with transaction.atomic():
            run = self._lock_run(simulation_run)
            if run.status in self._TERMINAL_STATUSES:
                raise SimulationLifecycleError("Terminal runs must be replayed, not reset.")

            initial_clock = self._initial_clock(run)
            old_context = copy.deepcopy(run.lifecycle_context)
            run.events.all().delete()
            run.virtual_clock = initial_clock
            run.status = SimulationRunStatus.DRAFT
            run.lifecycle_context = {
                "initial_virtual_clock": initial_clock.isoformat(),
                "reset_count": int(old_context.get("reset_count", 0)) + 1,
            }
            run.save(update_fields=["virtual_clock", "status", "lifecycle_context", "updated_at"])
            return run

    def replay(self, simulation_run: SimulationRun) -> SimulationRun:
        """Create a new traceable run from immutable originating context."""
        run = self._load_run(simulation_run)
        self._assert_snapshot_context(run)
        baseline_replay = None
        if run.comparison_role == SimulationComparisonRole.CANDIDATE:
            baseline_replay = self._create_replay_run(run.baseline_run)
        return self._create_replay_run(run, baseline_run=baseline_replay)

    def _create_replay_run(
        self,
        run: SimulationRun,
        *,
        baseline_run: SimulationRun | None = None,
    ) -> SimulationRun:
        initial_clock = self._initial_clock(run)
        return SimulationRun.objects.create(
            source_snapshot=run.source_snapshot,
            scenario=run.scenario,
            comparison_role=run.comparison_role,
            baseline_run=baseline_run if baseline_run is not None else run.baseline_run,
            replay_of=run,
            replay_identity=run.replay_identity,
            deterministic_seed=run.deterministic_seed,
            virtual_clock=initial_clock,
            speed_multiplier=run.speed_multiplier,
            input_parameters=copy.deepcopy(run.input_parameters),
            lifecycle_context={
                "initial_virtual_clock": initial_clock.isoformat(),
                "replay_of": run.run_code,
            },
        )

    def _prepare_locked(self, run: SimulationRun) -> SimulationRun:
        if run.status != SimulationRunStatus.DRAFT:
            raise SimulationLifecycleError("Only draft runs can be prepared.")
        self._assert_snapshot_context(run)
        initial_clock = self._initial_clock(run)
        effective_inputs = self._deep_merge(run.scenario.default_parameters, run.input_parameters)
        context = copy.deepcopy(run.lifecycle_context)
        context.update(
            {
                "initial_virtual_clock": initial_clock.isoformat(),
                "effective_inputs": effective_inputs,
                "effective_input_fingerprint": self._fingerprint(effective_inputs),
            }
        )
        run.lifecycle_context = context
        run.status = SimulationRunStatus.READY
        run.save(update_fields=["lifecycle_context", "status", "updated_at"])
        return run

    def _append_event(
        self,
        run: SimulationRun,
        *,
        event_type: str,
        context: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> SimulationRunEvent:
        last_sequence = run.events.order_by("-sequence").values_list("sequence", flat=True).first()
        sequence = (last_sequence or 0) + 1
        event_context = {
            "runtime": "simulation",
            "effective_input_fingerprint": run.lifecycle_context.get("effective_input_fingerprint"),
            **(context or {}),
        }
        identity = {
            "replay_identity": run.replay_identity,
            "seed": run.deterministic_seed,
            "sequence": sequence,
            "event_type": event_type,
            "virtual_occurred_at": (occurred_at or run.virtual_clock).isoformat(),
            "effective_input_fingerprint": event_context["effective_input_fingerprint"],
        }
        return SimulationRunEvent.objects.create(
            simulation_run=run,
            sequence=sequence,
            event_code=f"SIM-EVT-{self._fingerprint(identity)[:24].upper()}",
            event_type=event_type,
            virtual_occurred_at=occurred_at or run.virtual_clock,
            event_context=event_context,
        )

    @staticmethod
    def _deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(defaults, dict) or not isinstance(overrides, dict):
            raise SimulationRuntimeError("Simulation parameters must be objects.")
        merged = copy.deepcopy(defaults)
        for key in sorted(overrides):
            override = overrides[key]
            if isinstance(merged.get(key), dict) and isinstance(override, dict):
                merged[key] = SimulationService._deep_merge(merged[key], override)
            else:
                merged[key] = copy.deepcopy(override)
        return merged

    @staticmethod
    def _fingerprint(value: object) -> str:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _timedelta_microseconds(value: timedelta) -> int:
        return ((value.days * 86_400 + value.seconds) * 1_000_000) + value.microseconds

    @staticmethod
    def _load_run(simulation_run: SimulationRun) -> SimulationRun:
        if not simulation_run or not simulation_run.pk:
            raise SimulationRuntimeError("A persisted simulation run is required.")
        return SimulationRun.objects.select_related(
            "source_snapshot", "scenario", "baseline_run"
        ).get(pk=simulation_run.pk)

    def _lock_run(self, simulation_run: SimulationRun) -> SimulationRun:
        if not simulation_run or not simulation_run.pk:
            raise SimulationRuntimeError("A persisted simulation run is required.")
        return (
            SimulationRun.objects.select_for_update()
            .select_related("source_snapshot", "scenario", "baseline_run")
            .get(pk=simulation_run.pk)
        )

    def _assert_snapshot_context(self, run: SimulationRun) -> None:
        if run.scenario.source_snapshot_id != run.source_snapshot_id:
            raise SimulationRuntimeError(
                "Simulation scenario crosses the source snapshot boundary."
            )
        if run.baseline_run_id and run.baseline_run.source_snapshot_id != run.source_snapshot_id:
            raise SimulationRuntimeError("Baseline run crosses the source snapshot boundary.")

    @staticmethod
    def _initial_clock(run: SimulationRun) -> datetime:
        value = run.lifecycle_context.get("initial_virtual_clock")
        if isinstance(value, str):
            parsed = parse_datetime(value)
            if parsed is not None:
                return parsed
        return run.virtual_clock
