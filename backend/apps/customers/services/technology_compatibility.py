from apps.network.models import AccessTechnology

COMPATIBLE_PACKAGE_LINE_TECHNOLOGIES = frozenset(
    {
        (AccessTechnology.FIBER, AccessTechnology.FIBER),
        (AccessTechnology.FIBER, AccessTechnology.GPON),
        (AccessTechnology.VDSL, AccessTechnology.VDSL),
        (AccessTechnology.ADSL, AccessTechnology.ADSL),
        (AccessTechnology.METRO_ETHERNET, AccessTechnology.METRO_ETHERNET),
    }
)


def is_package_line_compatible(package_technology: str, line_technology: str) -> bool:
    return (package_technology, line_technology) in COMPATIBLE_PACKAGE_LINE_TECHNOLOGIES
