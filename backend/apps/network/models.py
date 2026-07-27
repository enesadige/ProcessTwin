from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.core.models import TimeStampedModel
from apps.datasets.models import DataSnapshot
from apps.geography.models import City, District, Neighborhood


class NetworkDeviceType(models.TextChoices):
    BNG = "bng", "BNG"
    OLT = "olt", "OLT"
    DSLAM = "dslam", "DSLAM"
    ACCESS_NODE = "access_node", "Access node"


class AccessTechnology(models.TextChoices):
    FIBER = "fiber", "Fiber"
    GPON = "gpon", "GPON"
    VDSL = "vdsl", "VDSL"
    ADSL = "adsl", "ADSL"
    METRO_ETHERNET = "metro_ethernet", "Metro Ethernet"


class NetworkDeviceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    MAINTENANCE = "maintenance", "Maintenance"
    DECOMMISSIONED = "decommissioned", "Decommissioned"


class NetworkLinkStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DEGRADED = "degraded", "Degraded"
    DOWN = "down", "Down"
    MAINTENANCE = "maintenance", "Maintenance"


def validate_location_chain(
    city: City,
    district: District | None,
    neighborhood: Neighborhood | None,
) -> None:
    errors: dict[str, str] = {}
    if district and district.city_id != city.id:
        errors["district"] = "District must belong to the selected city."
    if neighborhood and not district:
        errors["neighborhood"] = "Neighborhood requires a district."
    if neighborhood and district and neighborhood.district_id != district.id:
        errors["neighborhood"] = "Neighborhood must belong to the selected district."
    if errors:
        raise ValidationError(errors)


class NetworkDevice(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="network_devices",
    )
    code = models.CharField(max_length=80)
    name = models.CharField(max_length=160, blank=True)
    device_type = models.CharField(max_length=24, choices=NetworkDeviceType.choices)
    status = models.CharField(
        max_length=24,
        choices=NetworkDeviceStatus.choices,
        default=NetworkDeviceStatus.ACTIVE,
    )
    vendor = models.CharField(max_length=80, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    software_version = models.CharField(max_length=80, blank=True)
    management_ip = models.GenericIPAddressField(null=True, blank=True)
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name="network_devices",
    )
    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="network_devices",
    )
    neighborhood = models.ForeignKey(
        Neighborhood,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="network_devices",
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "network_device"
        ordering = ["data_snapshot", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_network_device_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.get_device_type_display()})"

    def clean(self):
        validate_location_chain(self.city, self.district, self.neighborhood)

    @property
    def display_name(self) -> str:
        return self.name or self.code

    @property
    def location_name(self) -> str:
        if self.neighborhood:
            return self.neighborhood.full_name
        if self.district:
            return self.district.full_name
        return self.city.name


class AccessSegment(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="access_segments",
    )
    segment_code = models.CharField(max_length=80)
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=180, blank=True)
    technology = models.CharField(max_length=32, choices=AccessTechnology.choices)
    serving_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.PROTECT,
        related_name="access_segments",
    )
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name="access_segments",
    )
    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="access_segments",
    )
    neighborhood = models.ForeignKey(
        Neighborhood,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="access_segments",
    )
    estimated_customer_count = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "network_access_segment"
        ordering = ["data_snapshot", "segment_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "segment_code"],
                name="unique_access_segment_code_per_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.segment_code} - {self.get_technology_display()}"

    def clean(self):
        validate_location_chain(self.city, self.district, self.neighborhood)
        if (
            self.serving_device_id
            and self.data_snapshot_id
            and self.serving_device.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError(
                {"serving_device": "Serving device must belong to the same data snapshot."}
            )

    @property
    def location_name(self) -> str:
        if self.neighborhood:
            return self.neighborhood.full_name
        if self.district:
            return self.district.full_name
        return self.city.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(f"{self.segment_code}-{self.name}")
        super().save(*args, **kwargs)


class NetworkLink(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="network_links",
    )
    link_code = models.CharField(max_length=80)
    source_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="outgoing_links",
    )
    target_device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="incoming_links",
    )
    status = models.CharField(
        max_length=24,
        choices=NetworkLinkStatus.choices,
        default=NetworkLinkStatus.ACTIVE,
    )
    capacity_mbps = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "network_link"
        ordering = ["data_snapshot", "link_code"]
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "link_code"],
                name="unique_network_link_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=~models.Q(source_device=models.F("target_device")),
                name="network_link_source_target_differ",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.link_code}: {self.source_device.code} -> {self.target_device.code}"

    def clean(self):
        errors: dict[str, str] = {}
        if (
            self.source_device_id
            and self.target_device_id
            and self.source_device_id == self.target_device_id
        ):
            errors["target_device"] = "Source and target devices must be different."
        if (
            self.source_device_id
            and self.data_snapshot_id
            and self.source_device.data_snapshot_id != self.data_snapshot_id
        ):
            errors["source_device"] = "Source device must belong to the same data snapshot."
        if (
            self.target_device_id
            and self.data_snapshot_id
            and self.target_device.data_snapshot_id != self.data_snapshot_id
        ):
            errors["target_device"] = "Target device must belong to the same data snapshot."
        if errors:
            raise ValidationError(errors)
