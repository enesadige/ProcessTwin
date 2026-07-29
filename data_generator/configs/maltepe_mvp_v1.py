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
    "single_subscription_customers": 210,
    "segment_distribution": {
        "individual": 170,
        "sme": 35,
        "enterprise": 15,
        "public": 5,
    },
    "priority_distribution": {
        "standard": 205,
        "vip": 20,
    },
    "vip_segment_distribution": {
        "individual": 12,
        "sme": 5,
        "enterprise": 2,
        "public": 1,
    },
    "vip_bng_distribution": {
        "BNG-MAL-001": 12,
        "BNG-MAL-002": 8,
    },
    "vip_neighborhood_distribution": {
        "Altayçeşme": 4,
        "Cevizli": 4,
        "Küçükyalı": 4,
        "Zümrütevler": 4,
        "Fındıklı": 4,
    },
    "bng_customer_distribution": {
        "BNG-MAL-001": {
            "unique_customers": 140,
            "multi_subscription_customers": 10,
            "subscriptions": 150,
        },
        "BNG-MAL-002": {
            "unique_customers": 85,
            "multi_subscription_customers": 5,
            "subscriptions": 90,
        },
    },
    "customer_neighborhood_distribution": {
        "Altayçeşme": 47,
        "Cevizli": 47,
        "Küçükyalı": 46,
        "Zümrütevler": 43,
        "Fındıklı": 42,
    },
    "customer_segment_by_neighborhood": {
        "Altayçeşme": {"individual": 36, "sme": 7, "enterprise": 3, "public": 1},
        "Cevizli": {"individual": 36, "sme": 7, "enterprise": 3, "public": 1},
        "Küçükyalı": {"individual": 35, "sme": 7, "enterprise": 3, "public": 1},
        "Zümrütevler": {"individual": 32, "sme": 7, "enterprise": 3, "public": 1},
        "Fındıklı": {"individual": 31, "sme": 7, "enterprise": 3, "public": 1},
    },
    "vip_segment_by_neighborhood": {
        "Altayçeşme": {"individual": 3, "sme": 1, "enterprise": 0, "public": 0},
        "Cevizli": {"individual": 3, "sme": 1, "enterprise": 0, "public": 0},
        "Küçükyalı": {"individual": 2, "sme": 1, "enterprise": 1, "public": 0},
        "Zümrütevler": {"individual": 2, "sme": 1, "enterprise": 0, "public": 1},
        "Fındıklı": {"individual": 2, "sme": 1, "enterprise": 1, "public": 0},
    },
}

SERVICE_PACKAGE_CATALOG = [
    {
        "package_code": "PKG-FIBER-100",
        "name": "Fiber 100",
        "technology": "fiber",
        "download_mbps": 100,
        "upload_mbps": 20,
        "monthly_price": "399.90",
        "commitment_months": 12,
        "subscription_count": 60,
    },
    {
        "package_code": "PKG-FIBER-200",
        "name": "Fiber 200",
        "technology": "fiber",
        "download_mbps": 200,
        "upload_mbps": 30,
        "monthly_price": "499.90",
        "commitment_months": 12,
        "subscription_count": 35,
    },
    {
        "package_code": "PKG-FIBER-500",
        "name": "Fiber 500",
        "technology": "fiber",
        "download_mbps": 500,
        "upload_mbps": 50,
        "monthly_price": "699.90",
        "commitment_months": 12,
        "subscription_count": 20,
    },
    {
        "package_code": "PKG-FIBER-1000",
        "name": "Fiber 1000",
        "technology": "fiber",
        "download_mbps": 1000,
        "upload_mbps": 100,
        "monthly_price": "1199.90",
        "commitment_months": 12,
        "subscription_count": 15,
    },
    {
        "package_code": "PKG-VDSL-35",
        "name": "VDSL 35",
        "technology": "vdsl",
        "download_mbps": 35,
        "upload_mbps": 6,
        "monthly_price": "249.90",
        "commitment_months": 12,
        "subscription_count": 35,
    },
    {
        "package_code": "PKG-VDSL-50",
        "name": "VDSL 50",
        "technology": "vdsl",
        "download_mbps": 50,
        "upload_mbps": 10,
        "monthly_price": "299.90",
        "commitment_months": 12,
        "subscription_count": 35,
    },
    {
        "package_code": "PKG-VDSL-100",
        "name": "VDSL 100",
        "technology": "vdsl",
        "download_mbps": 100,
        "upload_mbps": 15,
        "monthly_price": "399.90",
        "commitment_months": 12,
        "subscription_count": 20,
    },
    {
        "package_code": "PKG-ADSL-16",
        "name": "ADSL 16",
        "technology": "adsl",
        "download_mbps": 16,
        "upload_mbps": 2,
        "monthly_price": "199.90",
        "commitment_months": 12,
        "subscription_count": 20,
    },
]

SERVICE_PACKAGE_METADATA = {
    "synthetic_catalog": True,
    "disclaimer": (
        "Synthetic demo catalog only. Package names and prices do not represent real "
        "Turkcell products or current prices."
    ),
    "eligibility_rule_defined": False,
}

DEFAULT_SLA_PROFILE = {
    "code": "best_effort",
    "name": "Best Effort Synthetic SLA",
    "availability_target_percent": "99.00",
    "support_window": "8x5",
    "response_target_minutes": 1440,
    "restoration_target_minutes": 4320,
    "latency_threshold_ms": 80,
    "jitter_threshold_ms": 30,
    "packet_loss_threshold_percent": "2.00",
    "backup_requirement": "none",
    "required_path_diversity": "not_required",
    "monitoring_level": "standard",
    "is_contractual": False,
    "active": True,
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
    "metro_ethernet_service_packages": 0,
    "gpon_packages": 0,
    "gpon_physical_lines": 100,
    "general_fiber_physical_lines": 30,
}

OUTAGE_PLAN = {
    "main": {
        "outage_code": "OUT-MAL-BNG-001",
        "incident_number": "INC-MAL-BNG-001",
        "source_device": "BNG-MAL-001",
        "started_at": "2026-07-20T10:15:00+03:00",
        "ended_at": "2026-07-20T13:35:00+03:00",
        "duration_minutes": 200,
        "alarm_type": "BNG_UNREACHABLE",
        "supporting_alarm_type": "LINK_DOWN",
        "root_cause_category": "bng_failure",
        "root_cause_summary": "Synthetic BNG control-plane outage for Maltepe MVP.",
    },
    "secondary": [
        {
            "outage_code": "OUT-MAL-OLT-001",
            "incident_number": "INC-MAL-OLT-001",
            "source_type": "olt",
            "source_device": "OLT-MAL-ZUM-001",
            "started_at": "2026-07-10T09:20:00+03:00",
            "ended_at": "2026-07-10T10:05:00+03:00",
            "duration_minutes": 45,
            "alarm_type": "ACCESS_DEVICE_UNREACHABLE",
            "must_not_overlap_main": True,
        },
        {
            "outage_code": "OUT-MAL-DSLAM-001",
            "incident_number": "INC-MAL-DSLAM-001",
            "source_type": "dslam",
            "source_device": "DSLAM-MAL-FIN-001",
            "started_at": "2026-07-25T16:40:00+03:00",
            "ended_at": "2026-07-25T17:50:00+03:00",
            "duration_minutes": 70,
            "alarm_type": "ACCESS_DEVICE_UNREACHABLE",
            "must_not_overlap_main": True,
            "at_least_one_on_bng": "BNG-MAL-002",
        },
    ],
    "timezone": "Europe/Istanbul",
    "date_rule": "previous_calendar_month_of_reference_datetime",
}

ALARM_CATALOG = [
    {
        "code": "BNG_UNREACHABLE",
        "name": "BNG unreachable",
        "severity": "critical",
        "category": "core",
        "description": "Synthetic BNG reachability loss alarm for the MVP outage scenario.",
    },
    {
        "code": "ACCESS_DEVICE_UNREACHABLE",
        "name": "Access device unreachable",
        "severity": "major",
        "category": "access",
        "description": "Synthetic OLT/DSLAM reachability loss alarm for short outage scenarios.",
    },
    {
        "code": "LINK_DOWN",
        "name": "Link down",
        "severity": "major",
        "category": "transport",
        "description": "Synthetic supporting transport link alarm attached to relevant incidents.",
    },
]

OPERATIONAL_EVENT_TEMPLATES = [
    {
        "suffix": "DETECTED",
        "event_type": "note",
        "offset_minutes": 2,
        "source": "noc",
        "summary": "Synthetic NOC detection event.",
    },
    {
        "suffix": "INVESTIGATION",
        "event_type": "manual_intervention",
        "offset_minutes": 35,
        "source": "noc",
        "summary": "Synthetic operation investigation event.",
    },
    {
        "suffix": "RECOVERY",
        "event_type": "auto_recovery",
        "offset_minutes_from_end": -5,
        "source": "network",
        "summary": "Synthetic auto recovery signal; not a partial customer restoration claim.",
    },
    {
        "suffix": "CLOSED",
        "event_type": "note",
        "offset_minutes_from_end": 10,
        "source": "noc",
        "summary": "Synthetic closure note.",
    },
]

REFUND_RULE_PLAN = {
    "code": "REFUND-001",
    "name": "Synthetic full outage refund eligibility",
    "rule_type": "compensation",
    "status": "active",
    "description": (
        "Synthetic MVP refund eligibility rule. This is not a real Turkcell policy."
    ),
    "versions": [
        {
            "version": 1,
            "status": "active",
            "valid_from": "2026-01-01T00:00:00+03:00",
            "valid_to": "2026-07-14T23:59:59+03:00",
            "minimum_impact_minutes": 180,
        },
        {
            "version": 2,
            "status": "active",
            "valid_from": "2026-07-15T00:00:00+03:00",
            "valid_to": None,
            "minimum_impact_minutes": 120,
        },
    ],
    "refund_formula": {
        "type": "monthly_price_percentage",
        "percentage": "0.10",
        "currency": "TRY",
        "decimal_places": 2,
        "rounding": "ROUND_HALF_UP",
        "minimum_amount": None,
        "maximum_amount": None,
        "synthetic_demo_policy": True,
    },
    "deferred_inputs": [
        "payment_debt_or_late_payment",
        "campaign_discount",
        "previous_compensation",
    ],
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
        "service_package_catalog": SERVICE_PACKAGE_CATALOG,
        "service_package_metadata": SERVICE_PACKAGE_METADATA,
        "subscription_distribution": SUBSCRIPTION_DISTRIBUTION,
        "technology_totals": TECHNOLOGY_TOTALS,
        "outage_plan": OUTAGE_PLAN,
        "alarm_catalog": ALARM_CATALOG,
        "operational_event_templates": OPERATIONAL_EVENT_TEMPLATES,
        "refund_rule_plan": REFUND_RULE_PLAN,
    }
