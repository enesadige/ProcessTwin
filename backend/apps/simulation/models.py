from __future__ import annotations

from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot

SUPPORTED_SPEED_MULTIPLIERS = (1, 10, 60)


def generate_simulation_run_code() -> str:
    return f"SIM-{uuid4().hex.upper()}"


def generate_replay_identity() -> str:
    return f"RPL-{uuid4().hex.upper()}"


class SimulationRunStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    READY = "ready", "Ready"
    RUNNING = "running", "Running"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    STOPPED = "stopped", "Stopped"


class SimulationComparisonRole(models.TextChoices):
    BASELINE = "baseline", "Baseline"
    CANDIDATE = "candidate", "Candidate"


class SimulationScenario(TimeStampedModel):
    """Reusable, snapshot-local definition for a future ProcessTwin run."""

    source_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.PROTECT,
        related_name="simulation_scenarios",
    )
    scenario_code = models.CharField(max_length=120)
    name = models.CharField(max_length=160)
    scenario_type = models.CharField(max_length=80)
    description = models.TextField(blank=True)
    definition = models.JSONField(default=dict, blank=True)
    default_parameters = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "simulation_scenario"
        ordering = ["source_snapshot", "scenario_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["source_snapshot", "scenario_code"],
                name="simulation_scenario_snapshot_code_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source_snapshot", "scenario_type"],
                name="sim_scenario_snap_type_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.scenario_code

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if not isinstance(self.definition, dict):
            errors["definition"] = "Scenario definition must be an object."
        if not isinstance(self.default_parameters, dict):
            errors["default_parameters"] = "Default parameters must be an object."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)


class SimulationRun(TimeStampedModel):
    """Isolated, deterministic baseline or candidate simulation context.

    The model deliberately references only the immutable source snapshot. Runtime
    execution, overrides, result metrics, and operational writes are deferred to
    later ProcessTwin tasks.
    """

    SUPPORTED_SPEED_MULTIPLIERS = SUPPORTED_SPEED_MULTIPLIERS

    source_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.PROTECT,
        related_name="simulation_runs",
    )
    scenario = models.ForeignKey(
        SimulationScenario,
        on_delete=models.PROTECT,
        related_name="runs",
    )
    run_code = models.CharField(
        max_length=48,
        unique=True,
        default=generate_simulation_run_code,
    )
    comparison_role = models.CharField(
        max_length=16,
        choices=SimulationComparisonRole.choices,
    )
    baseline_run = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="candidate_runs",
    )
    replay_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replays",
    )
    replay_identity = models.CharField(
        max_length=48,
        db_index=True,
        default=generate_replay_identity,
    )
    deterministic_seed = models.CharField(max_length=160)
    virtual_clock = models.DateTimeField()
    speed_multiplier = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=16,
        choices=SimulationRunStatus.choices,
        default=SimulationRunStatus.DRAFT,
    )
    input_parameters = models.JSONField(default=dict, blank=True)
    lifecycle_context = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "simulation_run"
        ordering = ["-created_at", "run_code"]
        constraints = [
            models.CheckConstraint(
                condition=Q(speed_multiplier__in=SUPPORTED_SPEED_MULTIPLIERS),
                name="simulation_run_supported_speed",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        comparison_role=SimulationComparisonRole.BASELINE,
                        baseline_run__isnull=True,
                    )
                    | Q(
                        comparison_role=SimulationComparisonRole.CANDIDATE,
                        baseline_run__isnull=False,
                    )
                ),
                name="simulation_run_baseline_candidate_shape",
            ),
            models.CheckConstraint(
                condition=~Q(pk=F("baseline_run")),
                name="simulation_run_no_self_baseline",
            ),
            models.CheckConstraint(
                condition=~Q(pk=F("replay_of")),
                name="simulation_run_no_self_replay",
            ),
        ]
        indexes = [
            models.Index(
                fields=["source_snapshot", "status", "created_at"],
                name="sim_run_snap_status_idx",
            ),
            models.Index(
                fields=["replay_identity", "created_at"],
                name="sim_run_replay_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.run_code

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if self.speed_multiplier not in self.SUPPORTED_SPEED_MULTIPLIERS:
            errors["speed_multiplier"] = "Supported speed multipliers are 1x, 10x, and 60x."
        if not isinstance(self.input_parameters, dict):
            errors["input_parameters"] = "Simulation input parameters must be an object."
        if not isinstance(self.lifecycle_context, dict):
            errors["lifecycle_context"] = "Lifecycle context must be an object."
        if self.scenario_id and self.source_snapshot_id:
            if self.scenario.source_snapshot_id != self.source_snapshot_id:
                errors["scenario"] = "Scenario must belong to the source snapshot."
        if self.comparison_role == SimulationComparisonRole.BASELINE:
            if self.baseline_run_id is not None:
                errors["baseline_run"] = "Baseline runs cannot reference another baseline run."
        elif self.comparison_role == SimulationComparisonRole.CANDIDATE:
            if self.baseline_run_id is None:
                errors["baseline_run"] = "Candidate runs require a baseline run."
            else:
                baseline = self.baseline_run
                if baseline.pk == self.pk:
                    errors["baseline_run"] = "A run cannot be its own baseline."
                elif baseline.comparison_role != SimulationComparisonRole.BASELINE:
                    errors["baseline_run"] = "Candidate runs must reference a baseline run."
                else:
                    if baseline.source_snapshot_id != self.source_snapshot_id:
                        errors["baseline_run"] = "Baseline run must use the same source snapshot."
                    if baseline.scenario_id != self.scenario_id:
                        errors["baseline_run"] = "Baseline run must use the same scenario."
                    if baseline.deterministic_seed != self.deterministic_seed:
                        errors["baseline_run"] = (
                            "Baseline run must use the same deterministic seed."
                        )
                    if baseline.virtual_clock != self.virtual_clock:
                        errors["baseline_run"] = "Baseline run must use the same virtual clock."
        if self.replay_of_id is not None:
            replay_source = self.replay_of
            if replay_source.pk == self.pk:
                errors["replay_of"] = "A run cannot replay itself."
            else:
                if replay_source.source_snapshot_id != self.source_snapshot_id:
                    errors["replay_of"] = "Replay must use the same source snapshot."
                if replay_source.scenario_id != self.scenario_id:
                    errors["replay_of"] = "Replay must use the same scenario."
                if replay_source.deterministic_seed != self.deterministic_seed:
                    errors["replay_of"] = "Replay must use the same deterministic seed."
                if replay_source.replay_identity != self.replay_identity:
                    errors["replay_identity"] = "Replay must keep the originating replay identity."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)


class SimulationRunEvent(TimeStampedModel):
    """One time-ordered, snapshot-isolated event in a simulation run."""

    simulation_run = models.ForeignKey(
        SimulationRun,
        on_delete=models.CASCADE,
        related_name="events",
    )
    sequence = models.PositiveIntegerField()
    event_code = models.CharField(max_length=120)
    event_type = models.CharField(max_length=80)
    virtual_occurred_at = models.DateTimeField()
    event_context = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "simulation_run_event"
        ordering = ["simulation_run", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["simulation_run", "sequence"],
                name="simulation_event_run_sequence_uniq",
            ),
            models.UniqueConstraint(
                fields=["simulation_run", "event_code"],
                name="simulation_event_run_code_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["simulation_run", "virtual_occurred_at"],
                name="sim_event_run_clock_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.simulation_run.run_code}:{self.sequence}"

    def clean(self) -> None:
        errors: dict[str, str] = {}
        if not isinstance(self.event_context, dict):
            errors["event_context"] = "Simulation event context must be an object."
        if self.simulation_run_id:
            prior_event = (
                SimulationRunEvent.objects.filter(
                    simulation_run_id=self.simulation_run_id,
                    sequence__lt=self.sequence,
                )
                .exclude(pk=self.pk)
                .order_by("-sequence")
                .first()
            )
            next_event = (
                SimulationRunEvent.objects.filter(
                    simulation_run_id=self.simulation_run_id,
                    sequence__gt=self.sequence,
                )
                .exclude(pk=self.pk)
                .order_by("sequence")
                .first()
            )
            if prior_event and prior_event.virtual_occurred_at > self.virtual_occurred_at:
                errors["virtual_occurred_at"] = (
                    "Simulation event time cannot precede an earlier sequence."
                )
            if next_event and next_event.virtual_occurred_at < self.virtual_occurred_at:
                errors["virtual_occurred_at"] = (
                    "Simulation event time cannot follow a later sequence."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        return super().save(*args, **kwargs)
