from django.urls import path

from apps.simulation.public_views import (
    baseline_create,
    candidate_create,
    run_events,
    run_pause,
    run_replay,
    run_result,
    run_resume,
    run_start,
    run_status,
    run_stop,
    scenario_create,
    scenario_validate,
)

urlpatterns = [
    path("scenarios/validate/", scenario_validate, name="simulation-scenario-validate"),
    path("scenarios/", scenario_create, name="simulation-scenario-create"),
    path("runs/baseline/", baseline_create, name="simulation-baseline-create"),
    path("runs/candidate/", candidate_create, name="simulation-candidate-create"),
    path("runs/<str:run_code>/start/", run_start, name="simulation-run-start"),
    path("runs/<str:run_code>/pause/", run_pause, name="simulation-run-pause"),
    path("runs/<str:run_code>/resume/", run_resume, name="simulation-run-resume"),
    path("runs/<str:run_code>/stop/", run_stop, name="simulation-run-stop"),
    path("runs/<str:run_code>/replay/", run_replay, name="simulation-run-replay"),
    path("runs/<str:run_code>/status/", run_status, name="simulation-run-status"),
    path("runs/<str:run_code>/result/", run_result, name="simulation-run-result"),
    path("runs/<str:run_code>/events/", run_events, name="simulation-run-events"),
]
