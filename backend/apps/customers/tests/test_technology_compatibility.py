import pytest

from apps.customers.models import ServiceType
from apps.customers.services.technology_compatibility import is_package_line_compatible
from apps.network.models import AccessTechnology


@pytest.mark.parametrize(
    ("service_type", "package_technology", "line_technology", "expected"),
    [
        (ServiceType.BROADBAND, AccessTechnology.FIBER, AccessTechnology.FIBER, True),
        (ServiceType.BROADBAND, AccessTechnology.FIBER, AccessTechnology.GPON, True),
        (ServiceType.BROADBAND, AccessTechnology.FIBER, AccessTechnology.VDSL, False),
        (ServiceType.BROADBAND, AccessTechnology.FIBER, AccessTechnology.ADSL, False),
        (ServiceType.BROADBAND, AccessTechnology.GPON, AccessTechnology.FIBER, False),
        (ServiceType.BROADBAND, AccessTechnology.GPON, AccessTechnology.GPON, False),
        (ServiceType.BROADBAND, AccessTechnology.GPON, AccessTechnology.VDSL, False),
        (ServiceType.BROADBAND, AccessTechnology.GPON, AccessTechnology.ADSL, False),
        (ServiceType.BROADBAND, AccessTechnology.VDSL, AccessTechnology.FIBER, False),
        (ServiceType.BROADBAND, AccessTechnology.VDSL, AccessTechnology.GPON, False),
        (ServiceType.BROADBAND, AccessTechnology.VDSL, AccessTechnology.VDSL, True),
        (ServiceType.BROADBAND, AccessTechnology.VDSL, AccessTechnology.ADSL, False),
        (ServiceType.BROADBAND, AccessTechnology.ADSL, AccessTechnology.FIBER, False),
        (ServiceType.BROADBAND, AccessTechnology.ADSL, AccessTechnology.GPON, False),
        (ServiceType.BROADBAND, AccessTechnology.ADSL, AccessTechnology.VDSL, False),
        (ServiceType.BROADBAND, AccessTechnology.ADSL, AccessTechnology.ADSL, True),
        (ServiceType.METRO_ETHERNET, AccessTechnology.FIBER, AccessTechnology.FIBER, True),
        (ServiceType.METRO_ETHERNET, AccessTechnology.FIBER, AccessTechnology.GPON, False),
        (ServiceType.METRO_ETHERNET, AccessTechnology.FIBER, AccessTechnology.VDSL, False),
        (ServiceType.METRO_ETHERNET, AccessTechnology.FIBER, AccessTechnology.ADSL, False),
        (ServiceType.METRO_ETHERNET, AccessTechnology.VDSL, AccessTechnology.VDSL, False),
        (ServiceType.METRO_ETHERNET, AccessTechnology.ADSL, AccessTechnology.ADSL, False),
    ],
)
def test_package_line_technology_compatibility_matrix(
    service_type,
    package_technology,
    line_technology,
    expected,
):
    assert (
        is_package_line_compatible(package_technology, line_technology, service_type)
        is expected
    )


@pytest.mark.parametrize(
    ("package_technology", "line_technology"),
    [
        ("unknown", AccessTechnology.FIBER),
        (AccessTechnology.FIBER, "unknown"),
        ("", AccessTechnology.FIBER),
        (AccessTechnology.FIBER, ""),
        ("fiber", None),
        (None, "gpon"),
    ],
)
def test_package_line_technology_compatibility_rejects_unknown_values(
    package_technology,
    line_technology,
):
    assert is_package_line_compatible(package_technology, line_technology) is False


def test_package_line_technology_compatibility_rejects_unknown_service_type():
    assert (
        is_package_line_compatible(
            AccessTechnology.FIBER,
            AccessTechnology.FIBER,
            "unknown",
        )
        is False
    )
