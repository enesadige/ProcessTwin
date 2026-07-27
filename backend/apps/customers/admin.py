from django.contrib import admin

from apps.customers.models import (
    CampaignEnrollment,
    CompensationHistory,
    Customer,
    PaymentRecord,
    ServicePackage,
    Subscription,
    SubscriptionConnection,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "customer_number",
        "display_name",
        "segment",
        "status",
        "district",
        "data_snapshot",
    )
    list_filter = ("segment", "status", "city", "district")
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
        "download_mbps",
        "upload_mbps",
        "monthly_price",
        "data_snapshot",
    )
    list_filter = ("technology", "commitment_months")
    search_fields = ("package_code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot",)
    list_select_related = ("data_snapshot",)
    date_hierarchy = "created_at"


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "subscription_number",
        "customer",
        "service_package",
        "status",
        "is_active",
        "valid_from",
        "valid_to",
        "data_snapshot",
    )
    list_filter = ("status", "is_active", "service_package__technology")
    search_fields = (
        "subscription_number",
        "customer__customer_number",
        "customer__display_name",
        "service_package__package_code",
    )
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "customer", "service_package")
    list_select_related = ("data_snapshot", "customer", "service_package")
    date_hierarchy = "valid_from"


@admin.register(SubscriptionConnection)
class SubscriptionConnectionAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "line_connection",
        "is_active",
        "valid_from",
        "valid_to",
        "port_identifier",
        "data_snapshot",
    )
    list_filter = ("is_active", "line_connection__technology")
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
    list_display = ("subscription", "period", "amount", "status", "paid_at", "data_snapshot")
    list_filter = ("status", "period")
    search_fields = ("subscription__subscription_number", "period")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "subscription")
    list_select_related = ("data_snapshot", "subscription")
    date_hierarchy = "created_at"


@admin.register(CampaignEnrollment)
class CampaignEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "campaign_code",
        "name",
        "status",
        "valid_from",
        "valid_to",
        "data_snapshot",
    )
    list_filter = ("status", "campaign_code")
    search_fields = ("subscription__subscription_number", "campaign_code", "name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "subscription")
    list_select_related = ("data_snapshot", "subscription")
    date_hierarchy = "valid_from"


@admin.register(CompensationHistory)
class CompensationHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "reference_code",
        "subscription",
        "amount",
        "status",
        "decided_at",
        "data_snapshot",
    )
    list_filter = ("status",)
    search_fields = ("reference_code", "subscription__subscription_number", "reason")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("data_snapshot", "subscription")
    list_select_related = ("data_snapshot", "subscription")
    date_hierarchy = "decided_at"
