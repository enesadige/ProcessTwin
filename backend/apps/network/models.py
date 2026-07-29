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


class NetworkDeviceAccessRole(models.TextChoices):
    STANDARD_ACCESS = "standard_access", "Standard access"
    CORPORATE_FIBER_AGGREGATION = (
        "corporate_fiber_aggregation",
        "Corporate fiber aggregation",
    )


class AccessTechnology(models.TextChoices):
    FIBER = "fiber", "Fiber"
    GPON = "gpon", "GPON"
    VDSL = "vdsl", "VDSL"
    ADSL = "adsl", "ADSL"


class NetworkDeviceStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    MAINTENANCE = "maintenance", "Maintenance"
    DECOMMISSIONED = "decommissioned", "Decommissioned"


class NetworkLinkStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    DEGRADED = "degraded", "Degraded"
    DOWN = "down", "Down"
    MAINTENANCE = "maintenance", "Maintenance"


class NetworkPortType(models.TextChoices):
    UPLINK = "uplink", "Uplink"
    DOWNLINK = "downlink", "Downlink"
    ACCESS = "access", "Access"
    CUSTOMER = "customer", "Customer"
    MANAGEMENT = "management", "Management"


class NetworkPortStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    RESERVED = "reserved", "Reserved"
    MAINTENANCE = "maintenance", "Maintenance"
    DECOMMISSIONED = "decommissioned", "Decommissioned"


class LineConnectionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PLANNED = "planned", "Planned"
    SUSPENDED = "suspended", "Suspended"
    TERMINATED = "terminated", "Terminated"


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
    inventory_status = models.CharField(
        max_length=24,
        choices=NetworkDeviceStatus.choices,
        default=NetworkDeviceStatus.ACTIVE,
    )
    access_role = models.CharField(
        max_length=40,
        choices=NetworkDeviceAccessRole.choices,
        null=True,
        blank=True,
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
        verbose_name = "Ağ cihazı"
        verbose_name_plural = "Ağ cihazları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "code"],
                name="unique_network_device_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        device_type=NetworkDeviceType.ACCESS_NODE,
                        access_role__isnull=False,
                    )
                    | ~models.Q(device_type=NetworkDeviceType.ACCESS_NODE)
                    & models.Q(access_role__isnull=True)
                ),
                name="network_device_access_role_matches_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.get_device_type_display()})"

    def clean(self):
        validate_location_chain(self.city, self.district, self.neighborhood)
        errors: dict[str, str] = {}
        if self.device_type == NetworkDeviceType.ACCESS_NODE and not self.access_role:
            errors["access_role"] = "Access node devices require an access role."
        if self.device_type != NetworkDeviceType.ACCESS_NODE and self.access_role:
            errors["access_role"] = "Only access node devices can have an access role."
        if errors:
            raise ValidationError(errors)

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


class NetworkPort(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="network_ports",
    )
    device = models.ForeignKey(
        NetworkDevice,
        on_delete=models.CASCADE,
        related_name="ports",
    )
    port_code = models.CharField(max_length=80)
    port_type = models.CharField(
        max_length=24,
        choices=NetworkPortType.choices,
        default=NetworkPortType.ACCESS,
    )
    inventory_status = models.CharField(
        max_length=24,
        choices=NetworkPortStatus.choices,
        default=NetworkPortStatus.ACTIVE,
    )
    capacity_mbps = models.PositiveIntegerField(default=0)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "network_port"
        ordering = ["data_snapshot", "device__code", "port_code"]
        verbose_name = "Ağ portu"
        verbose_name_plural = "Ağ portları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "device", "port_code"],
                name="unique_network_port_code_per_device_snapshot",
            )
        ]

    def __str__(self) -> str:
        return f"{self.device.code}/{self.port_code}"

    def clean(self):
        if (
            self.device_id
            and self.data_snapshot_id
            and self.device.data_snapshot_id != self.data_snapshot_id
        ):
            raise ValidationError({"device": "Port device must belong to the same data snapshot."})


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
        verbose_name = "Erişim segmenti"
        verbose_name_plural = "Erişim segmentleri"
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


class LineConnection(TimeStampedModel):
    data_snapshot = models.ForeignKey(
        DataSnapshot,
        on_delete=models.CASCADE,
        related_name="line_connections",
    )
    line_code = models.CharField(max_length=80)
    port = models.ForeignKey(
        NetworkPort,
        on_delete=models.PROTECT,
        related_name="line_connections",
    )
    access_segment = models.ForeignKey(
        AccessSegment,
        on_delete=models.PROTECT,
        related_name="line_connections",
    )
    technology = models.CharField(max_length=32, choices=AccessTechnology.choices)
    status = models.CharField(
        max_length=24,
        choices=LineConnectionStatus.choices,
        default=LineConnectionStatus.ACTIVE,
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "network_line_connection"
        ordering = ["data_snapshot", "line_code"]
        verbose_name = "Hat bağlantısı"
        verbose_name_plural = "Hat bağlantıları"
        constraints = [
            models.UniqueConstraint(
                fields=["data_snapshot", "line_code"],
                name="unique_line_connection_code_per_snapshot",
            ),
            models.CheckConstraint(
                condition=models.Q(valid_to__isnull=True)
                | models.Q(valid_to__gt=models.F("valid_from")),
                name="line_connection_valid_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.line_code}: {self.port} -> {self.access_segment.segment_code}"

    def clean(self):
        errors: dict[str, str] = {}
        if self.valid_to and self.valid_to <= self.valid_from:
            errors["valid_to"] = "valid_to must be later than valid_from."
        if (
            self.port_id
            and self.data_snapshot_id
            and self.port.data_snapshot_id != self.data_snapshot_id
        ):
            errors["port"] = "Port must belong to the same data snapshot."
        if (
            self.access_segment_id
            and self.data_snapshot_id
            and self.access_segment.data_snapshot_id != self.data_snapshot_id
        ):
            errors["access_segment"] = "Access segment must belong to the same data snapshot."
        if self.access_segment_id and self.technology != self.access_segment.technology:
            errors["technology"] = "Line technology must match the access segment technology."
        if errors:
            raise ValidationError(errors)

    def is_valid_at(self, moment) -> bool:
        if not self.is_active or self.status != LineConnectionStatus.ACTIVE:
            return False
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to


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
        verbose_name = "Ağ bağlantısı"
        verbose_name_plural = "Ağ bağlantıları"
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
