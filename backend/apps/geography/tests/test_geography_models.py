import pytest
from django.db import IntegrityError

from apps.geography.models import AreaProfileType, City, District, Neighborhood


@pytest.mark.django_db
def test_city_district_neighborhood_chain_for_maltepe():
    city = City.objects.create(name="İstanbul", plate_code="34")
    district = District.objects.create(
        city=city,
        name="Maltepe",
        profile_type=AreaProfileType.MIXED,
        metadata={"initial_slice": True},
    )
    neighborhood = Neighborhood.objects.create(
        district=district,
        name="Zümrütevler",
        profile_type=AreaProfileType.RESIDENTIAL,
    )

    assert city.slug == "istanbul"
    assert district.slug == "maltepe"
    assert district.full_name == "İstanbul / Maltepe"
    assert neighborhood.slug == "zumrutevler"
    assert neighborhood.full_name == "İstanbul / Maltepe / Zümrütevler"
    assert district.metadata == {"initial_slice": True}


@pytest.mark.django_db
def test_district_name_is_unique_only_inside_same_city():
    istanbul = City.objects.create(name="İstanbul", plate_code="34")
    ankara = City.objects.create(name="Ankara", plate_code="06")
    District.objects.create(city=istanbul, name="Merkez")
    District.objects.create(city=ankara, name="Merkez")

    with pytest.raises(IntegrityError):
        District.objects.create(city=istanbul, name="Merkez")


@pytest.mark.django_db
def test_neighborhood_name_is_unique_only_inside_same_district():
    city = City.objects.create(name="İstanbul", plate_code="34")
    maltepe = District.objects.create(city=city, name="Maltepe")
    kadikoy = District.objects.create(city=city, name="Kadıköy")
    Neighborhood.objects.create(district=maltepe, name="Merkez")
    Neighborhood.objects.create(district=kadikoy, name="Merkez")

    with pytest.raises(IntegrityError):
        Neighborhood.objects.create(district=maltepe, name="Merkez")
