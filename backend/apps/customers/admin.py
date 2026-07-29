from django.contrib import admin

from apps.customers.models import (
    Campaign,
    CampaignAllowedSegment,
    CampaignAllowedServiceType,
    CampaignAllowedTechnology,
    CampaignEnrollment,
    CompensationHistory,
    Customer,
    PaymentRecord,
    ServicePackage,
    ServicePackageAllowedSegment,
    ServicePackagePriceVersion,
    SLAProfile,
    Subscription,
    SubscriptionConnection,
)


class ServicePackageAllowedSegmentInline(admin.TabularInline):
    model = ServicePackageAllowedSegment
    extra = 0
    autocomplete_fields = ("data_snapshot",)


class ServicePackagePriceVersionInline(admin.TabularInline):
    model = ServicePackagePriceVersion
    extra = 0
    autocomplete_fields = ("data_snapshot",)


@admin.register(SLAProfile)
class SLAProfileAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "availability_target_percent",
        "backup_requirement",
        "required_path_diversity",
        "monitoring_level",
        "active",
        "data_snapshot",
    )
    list_filter = (
        "backup_requirement",
        "required_path_diversity",
        "monitoring_level",
        "is_contractual",
        "active",
    )
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "customer_number",
        "display_name",
        "segment",
        "priority_level",
        "status",
        "district",
        "data_snapshot",
    )
    list_filter = ("segment", "priority_level", "status", "city", "district")
    search_fields = ("customer_number", "display_name", "city__name", "district__name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "city", "district", "neighborhood")
    list_select_related = ("data_snapshot", "city", "district", "neighborhood")
    date_hierarchy = "created_at"


@admin.register(ServicePackage)
class ServicePackageAdmin(admin.ModelAdmin):
    list_display = (
        "package_code",
        "name",
        "technology",
        "service_type",
        "status",
        "default_sla_profile",
        "download_mbps",
        "upload_mbps",
        "symmetric",
        "monthly_price",
        "backup_eligible",
        "data_snapshot",
    )
    list_filter = (
        "technology",
        "service_type",
        "status",
        "symmetric",
        "backup_eligible",
        "commitment_months",
    )
    search_fields = ("package_code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "default_sla_profile")
    list_select_related = ("data_snapshot", "default_sla_profile")
    date_hierarchy = "created_at"
    inlines = (ServicePackageAllowedSegmentInline, ServicePackagePriceVersionInline)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "subscription_number",
        "customer",
        "service_package",
        "sla_profile",
        "status",
        "is_active",
        "valid_from",
        "valid_to",
        "data_snapshot",
    )
    list_filter = ("status", "is_active", "service_package__technology", "sla_profile")
    search_fields = (
        "subscription_number",
        "customer__customer_number",
        "customer__display_name",
        "service_package__package_code",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "customer", "service_package", "sla_profile")
    list_select_related = ("data_snapshot", "customer", "service_package", "sla_profile")
    date_hierarchy = "valid_from"


@admin.register(SubscriptionConnection)
class SubscriptionConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "line_connection",
        "connection_role",
        "is_active",
        "valid_from",
        "valid_to",
        "port_identifier",
        "data_snapshot",
    )
    list_filter = ("connection_role", "is_active", "line_connection__technology")
    search_fields = (
        "subscription__subscription_number",
        "line_connection__line_code",
        "port_identifier",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "subscription", "line_connection")
    list_select_related = ("data_snapshot", "subscription", "line_connection")
    date_hierarchy = "valid_from"


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "period",
        "billing_period_start",
        "billing_period_end",
        "billed_amount",
        "paid_amount",
        "outstanding_amount",
        "currency",
        "status",
        "paid_at",
        "data_snapshot",
    )
    list_filter = ("status", "period")
    search_fields = ("subscription__subscription_number", "period")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "subscription")
    list_select_related = ("data_snapshot", "subscription")
    date_hierarchy = "created_at"


class CampaignAllowedSegmentInline(admin.TabularInline):
    model = CampaignAllowedSegment
    extra = 0
    autocomplete_fields = ("data_snapshot",)


class CampaignAllowedServiceTypeInline(admin.TabularInline):
    model = CampaignAllowedServiceType
    extra = 0
    autocomplete_fields = ("data_snapshot",)


class CampaignAllowedTechnologyInline(admin.TabularInline):
    model = CampaignAllowedTechnology
    extra = 0
    autocomplete_fields = ("data_snapshot",)


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "discount_type",
        "discount_value",
        "duration_months",
        "stackable",
        "status",
        "valid_from",
        "valid_to",
        "data_snapshot",
    )
    list_filter = ("discount_type", "stackable", "status")
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
    date_hierarchy = "valid_from"
    inlines = (
        CampaignAllowedSegmentInline,
        CampaignAllowedServiceTypeInline,
        CampaignAllowedTechnologyInline,
    )


@admin.register(CampaignEnrollment)
class CampaignEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "campaign",
        "campaign_code",
        "name",
        "status",
        "valid_from",
        "valid_to",
        "data_snapshot",
    )
    list_filter = ("status", "campaign_code", "campaign__code")
    search_fields = ("subscription__subscription_number", "campaign_code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "subscription", "campaign")
    list_select_related = ("data_snapshot", "subscription", "campaign")
    date_hierarchy = "valid_from"


@admin.register(CompensationHistory)
class CompensationHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "reference_code",
        "subscription",
        "customer",
        "incident",
        "outage",
        "rule_version",
        "amount",
        "currency",
        "decision_status",
        "settlement_status",
        "decided_at",
        "settled_at",
        "data_snapshot",
    )
    list_filter = ("decision_status", "settlement_status", "currency")
    search_fields = ("reference_code", "subscription__subscription_number", "reason")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = (
        "data_snapshot",
        "subscription",
        "customer",
        "incident",
        "outage",
        "rule_version",
    )
    list_select_related = (
        "data_snapshot",
        "subscription",
        "customer",
        "incident",
        "outage",
        "rule_version",
    )
    date_hierarchy = "decided_at"
