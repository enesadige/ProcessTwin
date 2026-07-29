from apps.network.models import AccessTechnology

SERVICE_TYPE_BROADBAND = "broadband"
SERVICE_TYPE_METRO_ETHERNET = "metro_ethernet"

COMPATIBLE_PACKAGE_LINE_TECHNOLOGIES = frozenset(
    {
        (SERVICE_TYPE_BROADBAND, AccessTechnology.FIBER, AccessTechnology.FIBER),
        (SERVICE_TYPE_BROADBAND, AccessTechnology.FIBER, AccessTechnology.GPON),
        (SERVICE_TYPE_BROADBAND, AccessTechnology.VDSL, AccessTechnology.VDSL),
        (SERVICE_TYPE_BROADBAND, AccessTechnology.ADSL, AccessTechnology.ADSL),
        (SERVICE_TYPE_METRO_ETHERNET, AccessTechnology.FIBER, AccessTechnology.FIBER),
    }
)


def is_package_line_compatible(
    package_technology: str,
    line_technology: str,
    service_type: str = SERVICE_TYPE_BROADBAND,
) -> bool:
    return (
        service_type,
        package_technology,
        line_technology,
    ) in COMPATIBLE_PACKAGE_LINE_TECHNOLOGIES
