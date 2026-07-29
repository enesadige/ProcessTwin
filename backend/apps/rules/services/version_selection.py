from dataclasses import dataclass

from django.db.models import Q

from apps.datasets.models import DataSnapshot
from apps.rules.models import RuleVersion, RuleVersionStatus


@dataclass(frozen=True)
class RuleVersionSelection:
    status: str
    rule_code: str
    selected_version: RuleVersion | None
    reason: str


def select_rule_version_for_moment(
    *,
    snapshot: DataSnapshot,
    rule_code: str,
    moment,
) -> RuleVersionSelection:
    candidates = list(
        RuleVersion.objects.filter(
            data_snapshot=snapshot,
            rule__code=rule_code,
            status=RuleVersionStatus.ACTIVE,
            active=True,
            valid_from__lte=moment,
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gt=moment))
        .select_related("rule")
        .order_by("version")
    )
    if len(candidates) == 1:
        return RuleVersionSelection(
            status="selected",
            rule_code=rule_code,
            selected_version=candidates[0],
            reason="single_active_version_for_moment",
        )
    if not candidates:
        return RuleVersionSelection(
            status="manual_review",
            rule_code=rule_code,
            selected_version=None,
            reason="no_active_version_for_moment",
        )
    return RuleVersionSelection(
        status="manual_review",
        rule_code=rule_code,
        selected_version=None,
        reason="multiple_active_versions_for_moment",
    )
