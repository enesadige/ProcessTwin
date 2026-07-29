from typing import Any

from apps.datasets.models import DataSnapshot
from apps.network.models import NetworkDeviceType, NetworkLink

REALISTIC_ACCESS_DEVICE_TYPES = {
    NetworkDeviceType.OLT,
    NetworkDeviceType.DSLAM,
    NetworkDeviceType.ACCESS_NODE,
}


def collect_realistic_multi_city_topology_profile(snapshot: DataSnapshot) -> dict[str, Any]:
    """Collect profile-level topology findings for the large realistic dataset.

    The small Maltepe regression dataset intentionally keeps direct BNG-to-access
    links for backwards compatibility. This helper is only for the expanded
    realistic profile where the metro aggregation layer is required.
    """
    direct_bng_access_links = list(
        NetworkLink.objects.filter(
            data_snapshot=snapshot,
            source_device__device_type=NetworkDeviceType.BNG,
            target_device__device_type__in=REALISTIC_ACCESS_DEVICE_TYPES,
        )
        .order_by("link_code")
        .values_list("link_code", flat=True)
    )
    return {
        "direct_bng_access_link_count": len(direct_bng_access_links),
        "direct_bng_access_link_codes": direct_bng_access_links,
        "passed": not direct_bng_access_links,
    }
