from __future__ import annotations

from apps.orchestration.answerability import (
    AnswerabilityStatus,
    classify_completed_answerability,
    classify_unsupported_capability,
)


def test_prediction_is_classified_as_unsupported_capability():
    result = classify_unsupported_capability("Bu müşterinin gelecek ay kullanımını tahmin et.")

    assert result is not None
    assert result.status == AnswerabilityStatus.UNSUPPORTED_CAPABILITY


def test_completed_result_is_partially_verified_when_root_cause_is_unverified():
    result = classify_completed_answerability(
        final_result={
            "causal_summary": {"root_cause_reason_codes": ["root_cause_unverified"]},
            "impact_summary": {"affected_customer_count": 495},
        },
        requested_outputs=["root_cause", "impact"],
    )

    assert result["status"] == AnswerabilityStatus.PARTIALLY_VERIFIED.value
    assert result["missing_unverified_outputs"] == ["physical_root_cause"]
    assert result["verified_outputs"] == ["root_cause", "impact"]


def test_missing_customer_impact_evidence_is_not_rendered_as_zero():
    result = classify_completed_answerability(
        final_result={
            "impact_summary": {
                "affected_customer_count": None,
                "missing_evidence_categories": ["CustomerImpactAssessment"],
            }
        },
        requested_outputs=["impact"],
    )

    assert result["status"] == AnswerabilityStatus.PARTIALLY_VERIFIED.value
    assert result["missing_unverified_outputs"] == ["customer_impact"]
