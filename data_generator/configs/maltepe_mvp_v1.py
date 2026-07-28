GENERATOR_VERSION = "maltepe-mvp-v1"
FIXED_RANDOM_SEED = "maltepe-mvp-fixed-seed-v1"
DEFAULT_REFERENCE_DATETIME = "2026-08-01T00:00:00+03:00"

DATASET_NAME = "Maltepe MVP Synthetic Dataset"
DATASET_SEED = FIXED_RANDOM_SEED
SNAPSHOT_NAME = "Maltepe MVP Snapshot"

CITY = {
    "name": "İstanbul",
    "country_code": "TR",
    "plate_code": "34",
}

DISTRICT = {
    "name": "Maltepe",
    "profile_type": "mixed",
}

NEIGHBORHOODS = [
    "Altayçeşme",
    "Cevizli",
    "Küçükyalı",
    "Zümrütevler",
    "Fındıklı",
]

NEIGHBORHOOD_CODES = {
    "Altayçeşme": "ALT",
    "Cevizli": "CEV",
    "Küçükyalı": "KUC",
    "Zümrütevler": "ZUM",
    "Fındıklı": "FIN",
}

BNG_DISTRIBUTION = {
    "BNG-MAL-001": ["Altayçeşme", "Cevizli", "Küçükyalı"],
    "BNG-MAL-002": ["Zümrütevler", "Fındıklı"],
}

ACCESS_DEVICE_PLAN = {
    "olt_per_neighborhood": 1,
    "dslam_per_neighborhood": 1,
    "total_olt": 5,
    "total_dslam": 5,
    "optional_access_nodes": 2,
}

PORT_CAPACITY_PLAN = {
    "gpon": {
        "active_physical_pon_ports": 10,
        "reserved_physical_pon_ports": 2,
        "total_physical_pon_ports": 12,
        "active_subscriptions": 100,
        "average_subscriptions_per_active_pon_port": 10,
        "allowed_fan_out_examples": [8, 9, 11, 12],
    },
    "dslam": {
        "active_customer_ports": 110,
        "reserved_customer_ports": 20,
        "total_customer_ports": 130,
        "active_ports_per_dslam": 22,
        "reserved_ports_per_dslam": 4,
    },
    "general_fiber": {
        "active_ports": 30,
        "reserved_ports": 5,
        "total_ports": 35,
        "access_nodes": [
            {
                "code": "AN-MAL-GF-001",
                "name": "Maltepe General Fiber Access Node 001",
                "bng_code": "BNG-MAL-001",
                "neighborhood": "Cevizli",
                "active_ports": 18,
                "reserved_ports": 3,
            },
            {
                "code": "AN-MAL-GF-002",
                "name": "Maltepe General Fiber Access Node 002",
                "bng_code": "BNG-MAL-002",
                "neighborhood": "Fındıklı",
                "active_ports": 12,
                "reserved_ports": 2,
            },
        ],
    },
}

GPON_FAN_OUT_BY_NEIGHBORHOOD = {
    "Altayçeşme": [10, 11],
    "Cevizli": [10, 11],
    "Küçükyalı": [10, 10],
    "Zümrütevler": [9, 10],
    "Fındıklı": [9, 10],
}

GPON_RESERVED_PORT_NEIGHBORHOODS = ["Altayçeşme", "Zümrütevler"]

DSLAM_PORT_DISTRIBUTION = {
    "Altayçeşme": {"vdsl": 19, "adsl": 5, "reserved": 4},
    "Cevizli": {"vdsl": 18, "adsl": 5, "reserved": 4},
    "Küçükyalı": {"vdsl": 18, "adsl": 5, "reserved": 4},
    "Zümrütevler": {"vdsl": 18, "adsl": 2, "reserved": 4},
    "Fındıklı": {"vdsl": 17, "adsl": 3, "reserved": 4},
}

CUSTOMER_PLAN = {
    "unique_customers": 225,
    "subscriptions": 240,
    "active_subscription_connections": 240,
    "multi_subscription_customers": 15,
    "vip_customers": 20,
    "standard_customers": 205,
}

SUBSCRIPTION_DISTRIBUTION = {
    "BNG-MAL-001": {
        "total": 150,
        "fiber": 80,
        "vdsl": 55,
        "adsl": 15,
        "gpon_physical_lines": 62,
        "general_fiber_physical_lines": 18,
    },
    "BNG-MAL-002": {
        "total": 90,
        "fiber": 50,
        "vdsl": 35,
        "adsl": 5,
        "gpon_physical_lines": 38,
        "general_fiber_physical_lines": 12,
    },
}

TECHNOLOGY_TOTALS = {
    "fiber_packages": 130,
    "vdsl_packages": 90,
    "adsl_packages": 20,
    "metro_ethernet_packages": 0,
    "gpon_packages": 0,
    "gpon_physical_lines": 100,
    "general_fiber_physical_lines": 30,
}

OUTAGE_PLAN = {
    "main": {
        "source_device": "BNG-MAL-001",
        "started_at": "2026-07-20T10:15:00+03:00",
        "ended_at": "2026-07-20T13:35:00+03:00",
        "duration_minutes": 200,
    },
    "secondary": [
        {
            "source_type": "olt",
            "duration_minutes": 45,
            "must_not_overlap_main": True,
        },
        {
            "source_type": "dslam",
            "duration_minutes": 70,
            "must_not_overlap_main": True,
            "at_least_one_on_bng": "BNG-MAL-002",
        },
    ],
    "timezone": "Europe/Istanbul",
    "date_rule": "previous_calendar_month_of_reference_datetime",
}


def build_serializable_config(reference_datetime: str) -> dict:
    return {
        "generator_version": GENERATOR_VERSION,
        "fixed_random_seed": FIXED_RANDOM_SEED,
        "reference_datetime": reference_datetime,
        "dataset": {
            "name": DATASET_NAME,
            "seed": DATASET_SEED,
            "snapshot_name": SNAPSHOT_NAME,
        },
        "geography": {
            "city": CITY,
            "district": DISTRICT,
            "neighborhoods": NEIGHBORHOODS,
            "neighborhood_codes": NEIGHBORHOOD_CODES,
        },
        "bng_distribution": BNG_DISTRIBUTION,
        "access_device_plan": ACCESS_DEVICE_PLAN,
        "port_capacity_plan": PORT_CAPACITY_PLAN,
        "gpon_fan_out_by_neighborhood": GPON_FAN_OUT_BY_NEIGHBORHOOD,
        "gpon_reserved_port_neighborhoods": GPON_RESERVED_PORT_NEIGHBORHOODS,
        "dslam_port_distribution": DSLAM_PORT_DISTRIBUTION,
        "customer_plan": CUSTOMER_PLAN,
        "subscription_distribution": SUBSCRIPTION_DISTRIBUTION,
        "technology_totals": TECHNOLOGY_TOTALS,
        "outage_plan": OUTAGE_PLAN,
    }
