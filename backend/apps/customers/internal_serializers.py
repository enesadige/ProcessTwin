from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from apps.customers.models import (
    Campaign,
    CampaignEnrollment,
    CompensationHistory,
    Customer,
    PaymentRecord,
    ServicePackage,
    SLAProfile,
    Subscription,
    SubscriptionConnection,
)
from apps.datasets.models import DatasetKind, DataSnapshot
from apps.network.internal_serializers import iso_or_none, json_safe, location_summary


def snapshot_is_synthetic(snapshot: DataSnapshot) -> bool:
    return snapshot.dataset_version.kind == DatasetKind.SYNTHETIC


def mask_display_name(display_name: str) -> str:
    if not display_name:
        return ""
    parts = display_name.split()
    masked_parts = []
    for part in parts:
        if len(part) <= 2:
            masked_parts.append(f"{part[0]}***")
        else:
            masked_parts.append(f"{part[:2]}***")
    return " ".join(masked_parts)


def maybe_display_name(
    customer: Customer,
    *,
    include_display_name: bool,
    snapshot: DataSnapshot,
) -> dict[str, str]:
    payload = {"masked_display_name": mask_display_name(customer.display_name)}
    if include_display_name and snapshot_is_synthetic(snapshot):
        payload["display_name"] = customer.display_name
    return payload


def customer_summary(
    customer: Customer,
    *,
    include_display_name: bool,
    snapshot: DataSnapshot,
    related_subscription_count: int | None = None,
    technology_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    payload = {
        "customer_number": customer.customer_number,
        **maybe_display_name(
            customer,
            include_display_name=include_display_name,
            snapshot=snapshot,
        ),
        "segment": customer.segment,
        "priority_level": customer.priority_level,
        "status": customer.status,
        "location": location_summary(customer),
    }
    if related_subscription_count is not None:
        payload["related_subscription_count"] = related_subscription_count
    if technology_counts is not None:
        payload["technology_counts"] = technology_counts
    return payload


def sla_summary(sla_profile: SLAProfile | None) -> dict[str, Any] | None:
    if sla_profile is None:
        return None
    return {
        "code": sla_profile.code,
        "name": sla_profile.name,
        "availability_target_percent": str(sla_profile.availability_target_percent),
        "support_window": sla_profile.support_window,
        "response_target_minutes": sla_profile.response_target_minutes,
        "restoration_target_minutes": sla_profile.restoration_target_minutes,
        "latency_threshold_ms": sla_profile.latency_threshold_ms,
        "jitter_threshold_ms": sla_profile.jitter_threshold_ms,
        "packet_loss_threshold_percent": str(sla_profile.packet_loss_threshold_percent),
        "backup_requirement": sla_profile.backup_requirement,
        "required_path_diversity": sla_profile.required_path_diversity,
        "monitoring_level": sla_profile.monitoring_level,
        "is_contractual": sla_profile.is_contractual,
    }


def package_summary(service_package: ServicePackage) -> dict[str, Any]:
    return {
        "package_code": service_package.package_code,
        "name": service_package.name,
        "service_type": service_package.service_type,
        "technology": service_package.technology,
        "download_mbps": service_package.download_mbps,
        "upload_mbps": service_package.upload_mbps,
        "symmetric": service_package.symmetric,
        "monthly_price": str(service_package.monthly_price),
        "commitment_months": service_package.commitment_months,
        "backup_eligible": service_package.backup_eligible,
        "status": service_package.status,
    }


def connection_summary(connection: SubscriptionConnection) -> dict[str, Any]:
    line = connection.line_connection
    device = line.port.device
    return {
        "connection_role": connection.connection_role,
        "is_active": connection.is_active,
        "valid_from": iso_or_none(connection.valid_from),
        "valid_to": iso_or_none(connection.valid_to),
        "line_code": line.line_code,
        "line_technology": line.technology,
        "line_status": line.status,
        "access_segment_code": line.access_segment.segment_code,
        "access_device_code": device.code,
        "access_device_type": device.device_type,
        "access_role": device.access_role,
        "port_code": line.port.port_code,
    }


def campaign_enrollment_summary(enrollment: CampaignEnrollment) -> dict[str, Any]:
    return {
        "campaign_code": enrollment.campaign_code,
        "name": enrollment.name,
        "status": enrollment.status,
        "valid_from": iso_or_none(enrollment.valid_from),
        "valid_to": iso_or_none(enrollment.valid_to),
    }


def campaign_catalog_summary(campaign: Campaign | None) -> dict[str, Any] | None:
    if campaign is None:
        return None
    return {
        "code": campaign.code,
        "name": campaign.name,
        "discount_type": campaign.discount_type,
        "discount_value": str(campaign.discount_value),
        "duration_months": campaign.duration_months,
        "stackable": campaign.stackable,
        "status": campaign.status,
        "valid_from": iso_or_none(campaign.valid_from),
        "valid_to": iso_or_none(campaign.valid_to),
    }


def subscription_summary(
    subscription: Subscription,
    *,
    include_connections: bool = True,
    include_campaigns: bool = False,
) -> dict[str, Any]:
    payload = {
        "subscription_number": subscription.subscription_number,
        "customer_number": subscription.customer.customer_number,
        "status": subscription.status,
        "suspension_reason": subscription.suspension_reason,
        "valid_from": iso_or_none(subscription.valid_from),
        "valid_to": iso_or_none(subscription.valid_to),
        "is_active": subscription.is_active,
        "contracted_monthly_price": str(subscription.monthly_price),
        "service_package": package_summary(subscription.service_package),
        "sla_profile": sla_summary(subscription.sla_profile),
    }
    if include_connections:
        payload["connections"] = [
            connection_summary(connection)
            for connection in subscription.connections.all()
        ]
    if include_campaigns:
        payload["campaign_enrollments"] = [
            campaign_enrollment_summary(enrollment)
            for enrollment in subscription.campaign_enrollments.all()
        ]
    return payload


def compact_subscription_summary(subscription: Subscription) -> dict[str, Any]:
    return {
        "subscription_number": subscription.subscription_number,
        "status": subscription.status,
        "suspension_reason": subscription.suspension_reason,
        "service_package_code": subscription.service_package.package_code,
        "service_type": subscription.service_package.service_type,
        "technology": subscription.service_package.technology,
        "sla_profile_code": subscription.sla_profile.code if subscription.sla_profile else None,
    }


def payment_summary(payment: PaymentRecord) -> dict[str, Any]:
    return {
        "subscription_number": payment.subscription.subscription_number,
        "period": payment.period,
        "billing_period_start": payment.billing_period_start.isoformat()
        if payment.billing_period_start
        else None,
        "billing_period_end": payment.billing_period_end.isoformat()
        if payment.billing_period_end
        else None,
        "due_date": payment.due_date.isoformat() if payment.due_date else None,
        "status": payment.status,
        "recurring_amount": str(payment.recurring_amount),
        "one_time_amount": str(payment.one_time_amount),
        "discount_amount": str(payment.discount_amount),
        "billed_amount": str(payment.billed_amount),
        "paid_amount": str(payment.paid_amount),
        "outstanding_amount": str(payment.outstanding_amount),
        "currency": payment.currency,
        "paid_at": iso_or_none(payment.paid_at),
    }


def payment_aggregate(payments: list[PaymentRecord]) -> dict[str, Any]:
    counts = Counter(payment.status for payment in payments)
    total_outstanding = sum(
        (payment.outstanding_amount for payment in payments),
        Decimal("0.00"),
    )
    return {
        "status_counts": dict(sorted(counts.items())),
        "total_outstanding": str(total_outstanding),
        "currency": payments[0].currency if payments else "TRY",
    }


def compensation_history_summary(history: CompensationHistory) -> dict[str, Any]:
    rule_version = history.rule_version
    return {
        "reference_code": history.reference_code,
        "subscription_number": history.subscription.subscription_number,
        "incident_code": history.incident.incident_number if history.incident_id else None,
        "outage_code": history.outage.outage_code if history.outage_id else None,
        "rule_code": rule_version.rule.code if rule_version else None,
        "rule_version": rule_version.version if rule_version else None,
        "decision_status": history.decision_status,
        "settlement_status": history.settlement_status,
        "amount": str(history.amount),
        "currency": history.currency,
        "decided_at": iso_or_none(history.decided_at),
        "settled_at": iso_or_none(history.settled_at),
        "reason_summary": history.reason,
    }


def counts_by(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json_safe(payload)
