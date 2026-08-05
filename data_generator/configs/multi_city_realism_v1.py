"""Deterministic configuration for the large multi-city realism dataset.

All values are synthetic simulation inputs. They do not represent real operator
inventory, customers, tariffs, alarms, incidents, or policies.
"""

from data_generator.configs import realistic_commercial_profile_v1 as commercial

DATASET_NAME = "Multi-city Realism Dataset"
DATASET_SLUG = "multi-city-realism-v1"
SNAPSHOT_NAME = "Multi-city Realism Snapshot v1"
GENERATOR_VERSION = "multi-city-realism-generator-v1"
DATASET_SEED = "multi-city-realism-fixed-seed-v1"
DEFAULT_REFERENCE_DATETIME = "2026-08-01T00:00:00+03:00"

CITY_PROFILES = {
    "İstanbul": {
        "plate_code": "34",
        "districts": {
            "Maltepe": ["Altayçeşme", "Cevizli", "Küçükyalı", "Zümrütevler", "Fındıklı"],
            "Şişli": ["Mecidiyeköy", "Esentepe", "Halaskargazi", "Teşvikiye"],
            "Esenyurt": ["Akçaburgaz", "Mehterçeşme", "Pınar", "Saadetdere", "Talatpaşa"],
        },
    },
    "Ankara": {
        "plate_code": "06",
        "districts": {
            "Çankaya": ["Kızılay", "Kavaklıdere", "Çukurambar", "Söğütözü", "Bahçelievler"],
            "Yenimahalle": ["Ostim", "İvedikköy", "Serhat", "Macun", "Ergazi"],
            "Etimesgut": ["Eryaman", "Bağlıca", "Elvan", "Süvari", "Yapracık"],
        },
    },
    "İzmir": {
        "plate_code": "35",
        "districts": {
            "Konak": ["Alsancak", "Göztepe", "Güzelyalı", "Kültür", "İsmet Kaptan"],
            "Bornova": ["Kazımdirik", "Erzene", "Evka 3", "Atatürk", "Yeşilova"],
            "Karşıyaka": ["Bostanlı", "Mavişehir", "Yalı", "Alaybey", "Şemikler"],
        },
    },
    "Kocaeli": {
        "plate_code": "41",
        "districts": {
            "İzmit": ["Yenişehir", "Yahyakaptan", "Alikahya Atatürk", "Yeşilova", "Sanayi"],
            "Gebze": ["Arapçeşme", "Osman Yılmaz", "Barış", "Tatlıkuyu", "İstasyon"],
            "Körfez": ["Güney", "Mimar Sinan", "Yukarı Hereke", "Kirazlıyalı", "Hacı Osman"],
        },
    },
}

DISTRICT_TECHNOLOGY_DISTRIBUTION = {
    "Maltepe": {"gpon": 744, "fiber": 124, "vdsl": 589, "adsl": 93, "metro": 0},
    "Şişli": {"gpon": 660, "fiber": 290, "vdsl": 343, "adsl": 27, "metro": 106},
    "Esenyurt": {"gpon": 1081, "fiber": 94, "vdsl": 1034, "adsl": 141, "metro": 5},
    "Çankaya": {"gpon": 858, "fiber": 297, "vdsl": 462, "adsl": 33, "metro": 116},
    "Yenimahalle": {"gpon": 529, "fiber": 177, "vdsl": 491, "adsl": 63, "metro": 38},
    "Etimesgut": {"gpon": 670, "fiber": 54, "vdsl": 335, "adsl": 21, "metro": 5},
    "Konak": {"gpon": 396, "fiber": 88, "vdsl": 506, "adsl": 110, "metro": 11},
    "Bornova": {"gpon": 554, "fiber": 123, "vdsl": 492, "adsl": 61, "metro": 18},
    "Karşıyaka": {"gpon": 594, "fiber": 59, "vdsl": 317, "adsl": 20, "metro": 5},
    "İzmit": {"gpon": 488, "fiber": 111, "vdsl": 455, "adsl": 56, "metro": 22},
    "Gebze": {"gpon": 600, "fiber": 360, "vdsl": 510, "adsl": 30, "metro": 120},
    "Körfez": {"gpon": 403, "fiber": 265, "vdsl": 360, "adsl": 32, "metro": 74},
}

DEVICE_DISTRIBUTION = {
    "Maltepe": {"olt": 3, "dslam": 10, "standard_access": 4, "corporate_fiber_aggregation": 1},
    "Şişli": {"olt": 3, "dslam": 6, "standard_access": 6, "corporate_fiber_aggregation": 5},
    "Esenyurt": {"olt": 4, "dslam": 16, "standard_access": 3, "corporate_fiber_aggregation": 1},
    "Çankaya": {"olt": 3, "dslam": 7, "standard_access": 6, "corporate_fiber_aggregation": 6},
    "Yenimahalle": {"olt": 2, "dslam": 8, "standard_access": 5, "corporate_fiber_aggregation": 3},
    "Etimesgut": {"olt": 3, "dslam": 5, "standard_access": 2, "corporate_fiber_aggregation": 1},
    "Konak": {"olt": 2, "dslam": 9, "standard_access": 3, "corporate_fiber_aggregation": 1},
    "Bornova": {"olt": 2, "dslam": 8, "standard_access": 4, "corporate_fiber_aggregation": 2},
    "Karşıyaka": {"olt": 3, "dslam": 5, "standard_access": 2, "corporate_fiber_aggregation": 1},
    "İzmit": {"olt": 2, "dslam": 7, "standard_access": 3, "corporate_fiber_aggregation": 2},
    "Gebze": {"olt": 3, "dslam": 8, "standard_access": 7, "corporate_fiber_aggregation": 6},
    "Körfez": {"olt": 2, "dslam": 6, "standard_access": 6, "corporate_fiber_aggregation": 4},
}

NETWORK_TARGETS = {
    "bng": 8,
    "metro_aggregation": 16,
    "olt": 32,
    "dslam": 95,
    "standard_access": 51,
    "corporate_fiber_aggregation": 33,
    "network_devices": 235,
    "network_links": 245,
    "active_pon_ports": 322,
    "pon_port_capacity": 512,
    "active_dsl_ports": 6581,
    "dsl_port_capacity": 9120,
    "dedicated_fiber_port_capacity": 4032,
    "reserved_backup_port_capacity": 261,
}

TIMELINE_TARGETS = {
    "maintenance_windows": 30,
    "timeline_days": 60,
    "causal_event_budget": 210,
    "causal_event_variance": 12,
    "quality_samples_per_event": {"min": 38, "max": 62},
}

EXPECTED_TOTALS = {
    "cities": 4,
    "districts": 12,
    "neighborhoods": 59,
    **commercial.DATASET_SCALE,
    **NETWORK_TARGETS,
    "service_packages": 27,
    "sla_profiles": 5,
    "campaigns": 10,
    "service_package_price_versions": 72,
    "payment_records": 59600,
    "campaign_enrollments": 4050,
    "compensation_history": 1100,
    "rule_sets": 1,
    "rules": 25,
    "rule_versions": 25,
}


def build_serializable_config(reference_datetime: str) -> dict:
    return {
        "dataset_slug": DATASET_SLUG,
        "generator_version": GENERATOR_VERSION,
        "seed": DATASET_SEED,
        "reference_datetime": reference_datetime,
        "city_profiles": CITY_PROFILES,
        "district_commercial_distribution": commercial.DISTRICT_COMMERCIAL_DISTRIBUTION,
        "district_technology_distribution": DISTRICT_TECHNOLOGY_DISTRIBUTION,
        "device_distribution": DEVICE_DISTRIBUTION,
        "network_targets": NETWORK_TARGETS,
        "technology_totals": commercial.TECHNOLOGY_TOTALS,
        "backup_distribution": commercial.BACKUP_DISTRIBUTION,
        "payment_history": commercial.PAYMENT_HISTORY,
        "campaign_enrollment_targets": commercial.CAMPAIGN_ENROLLMENT_TARGETS,
        "compensation_history_targets": commercial.COMPENSATION_HISTORY_TARGETS,
        "timeline_targets": TIMELINE_TARGETS,
        "synthetic_disclaimer": (
            "Multi-city realism data is deterministic synthetic simulation data only."
        ),
    }
