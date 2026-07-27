from django.contrib import admin

from apps.geography.models import City, District, Neighborhood


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "country_code", "plate_code", "created_at")
    list_filter = ("country_code",)
    search_fields = ("name", "slug", "plate_code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "profile_type", "created_at")
    list_filter = ("city", "profile_type")
    search_fields = ("name", "slug", "city__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Neighborhood)
class NeighborhoodAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "profile_type", "external_code", "created_at")
    list_filter = ("district__city", "district", "profile_type")
    search_fields = ("name", "slug", "external_code", "district__name", "district__city__name")
    readonly_fields = ("created_at", "updated_at")
