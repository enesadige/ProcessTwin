from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel


class AreaProfileType(models.TextChoices):
    UNKNOWN = "unknown", "Unknown"
    RESIDENTIAL = "residential", "Residential"
    BUSINESS = "business", "Business"
    INDUSTRIAL = "industrial", "Industrial"
    MIXED = "mixed", "Mixed"


class City(TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    country_code = models.CharField(max_length=2, default="TR")
    plate_code = models.CharField(max_length=8, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "geography_city"
        ordering = ["name"]
        verbose_name_plural = "cities"

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class District(TimeStampedModel):
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="districts")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    profile_type = models.CharField(
        max_length=24,
        choices=AreaProfileType.choices,
        default=AreaProfileType.UNKNOWN,
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "geography_district"
        ordering = ["city__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["city", "slug"], name="unique_district_slug_per_city"),
            models.UniqueConstraint(fields=["city", "name"], name="unique_district_name_per_city"),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.city.name}"

    @property
    def full_name(self) -> str:
        return f"{self.city.name} / {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Neighborhood(TimeStampedModel):
    district = models.ForeignKey(District, on_delete=models.CASCADE, related_name="neighborhoods")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    profile_type = models.CharField(
        max_length=24,
        choices=AreaProfileType.choices,
        default=AreaProfileType.UNKNOWN,
    )
    external_code = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "geography_neighborhood"
        ordering = ["district__city__name", "district__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["district", "slug"],
                name="unique_neighborhood_slug_per_district",
            ),
            models.UniqueConstraint(
                fields=["district", "name"],
                name="unique_neighborhood_name_per_district",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name}, {self.district.name}"

    @property
    def full_name(self) -> str:
        return f"{self.district.city.name} / {self.district.name} / {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
