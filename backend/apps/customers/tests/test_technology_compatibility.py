import pytest

from apps.customers.services.technology_compatibility import is_package_line_compatible
from apps.network.models import AccessTechnology


@pytest.mark.parametrize(
    ("package_technology", "line_technology", "expected"),
    [
        (AccessTechnology.FIBER, AccessTechnology.FIBER, True),
        (AccessTechnology.FIBER, AccessTechnology.GPON, True),
        (AccessTechnology.FIBER, AccessTechnology.VDSL, False),
        (AccessTechnology.FIBER, AccessTechnology.ADSL, False),
        (AccessTechnology.FIBER, AccessTechnology.METRO_ETHERNET, False),
        (AccessTechnology.GPON, AccessTechnology.FIBER, False),
        (AccessTechnology.GPON, AccessTechnology.GPON, False),
        (AccessTechnology.GPON, AccessTechnology.VDSL, False),
        (AccessTechnology.GPON, AccessTechnology.ADSL, False),
        (AccessTechnology.GPON, AccessTechnology.METRO_ETHERNET, False),
        (AccessTechnology.VDSL, AccessTechnology.FIBER, False),
        (AccessTechnology.VDSL, AccessTechnology.GPON, False),
        (AccessTechnology.VDSL, AccessTechnology.VDSL, True),
        (AccessTechnology.VDSL, AccessTechnology.ADSL, False),
        (AccessTechnology.VDSL, AccessTechnology.METRO_ETHERNET, False),
        (AccessTechnology.ADSL, AccessTechnology.FIBER, False),
        (AccessTechnology.ADSL, AccessTechnology.GPON, False),
        (AccessTechnology.ADSL, AccessTechnology.VDSL, False),
        (AccessTechnology.ADSL, AccessTechnology.ADSL, True),
        (AccessTechnology.ADSL, AccessTechnology.METRO_ETHERNET, False),
        (AccessTechnology.METRO_ETHERNET, AccessTechnology.FIBER, False),
        (AccessTechnology.METRO_ETHERNET, AccessTechnology.GPON, False),
        (AccessTechnology.METRO_ETHERNET, AccessTechnology.VDSL, False),
        (AccessTechnology.METRO_ETHERNET, AccessTechnology.ADSL, False),
        (AccessTechnology.METRO_ETHERNET, AccessTechnology.METRO_ETHERNET, True),
    ],
)
def test_package_line_technology_compatibility_matrix(
    package_technology,
    line_technology,
    expected,
):
    assert is_package_line_compatible(package_technology, line_technology) is expected


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
