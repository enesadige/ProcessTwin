import pytest

from apps.orchestration.result_merge import _cross_incident_correlation


def test_cross_incident_result_normalizer_keeps_only_deterministic_evidence_fields():
    extracted = _cross_incident_correlation(
        {
            "anchor_event_code": "CE-CORR-001",
            "correlations": [
                {
                    "anchor_event_code": "CE-CORR-001",
                    "candidate_event_code": "CE-CORR-002",
                    "correlation_status": "verified_relation",
                    "time_difference_seconds": 2220,
                    "within_window": True,
                    "requested_window_seconds": 3600,
                    "topology_relation": "shared_failure_domain",
                    "resource_relation": "shared_failure_domain",
                    "event_relation": None,
                    "root_symptom_status": "not_verified",
                    "evidence": [
                        {"dimension": "temporal"},
                        {"dimension": "topology"},
                        {"dimension": "resource"},
                    ],
                }
            ],
        }
    )

    assert extracted.cross_incident_correlation == {
        "anchor_event_code": "CE-CORR-001",
        "candidate_event_code": "CE-CORR-002",
        "correlation_status": "verified_relation",
        "time_difference_seconds": 2220,
        "within_window": True,
        "requested_window_seconds": 3600,
        "topology_relation": "shared_failure_domain",
        "resource_relation": "shared_failure_domain",
        "event_relation": None,
        "root_symptom_status": "not_verified",
        "evidence_dimensions": ["resource", "temporal", "topology"],
    }


@pytest.mark.parametrize("status", ["caused", "unknown", ""])
def test_cross_incident_result_normalizer_rejects_unallowlisted_status(status):
    with pytest.raises(ValueError, match="correlation_status"):
        _cross_incident_correlation(
            {
                "anchor_event_code": "CE-CORR-001",
                "correlations": [
                    {
                        "candidate_event_code": "CE-CORR-002",
                        "correlation_status": status,
                        "evidence": [],
                    }
                ],
            }
        )
