from datetime import date

import pytest

from app.errors import ValidationError
from app.models import apply_patch, listing_from_dict

from .conftest import make_record


def fields_in_error(exc_info) -> set[str]:
    return {d["field"] for d in exc_info.value.details}


def test_valid_record_is_normalized():
    listing = listing_from_dict(make_record(
        source="mls_b", city=" round   ROCK ", state="texas", zip="78664-0001",
        price="$425,000", listedDate="2026-10-01T08:00:00Z", status="Active",
    ))
    assert listing.source == "MLS_B"
    assert listing.city == "Round Rock"
    assert listing.state == "TX"
    assert listing.zip == "78664"
    assert listing.price == 425000.0
    assert listing.listed_date == date(2026, 10, 1)
    assert listing.status == "active"
    assert listing.key == ("MLS_B", "A1")


def test_to_dict_round_trips():
    original = listing_from_dict(make_record())
    assert listing_from_dict(original.to_dict()) == original
    assert original.to_dict()["price"] == 500000  # integral prices serialize as ints


def test_description_is_optional():
    record = make_record()
    del record["description"]
    assert listing_from_dict(record).description == ""


def test_missing_required_fields_are_all_reported():
    with pytest.raises(ValidationError) as exc:
        listing_from_dict({"id": "x"})
    assert {"source", "address", "price", "listedDate", "status"} <= fields_in_error(exc)


def test_null_counts_as_missing():
    with pytest.raises(ValidationError) as exc:
        listing_from_dict(make_record(price=None))
    assert fields_in_error(exc) == {"price"}


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError) as exc:
        listing_from_dict(make_record(garage=True))
    assert fields_in_error(exc) == {"garage"}


@pytest.mark.parametrize("field, value", [
    ("bedrooms", True),          # bool is not an int here
    ("bedrooms", 2.5),
    ("bedrooms", -1),
    ("bedrooms", "3"),
    ("bathrooms", 2.3),          # not a multiple of 0.25
    ("bathrooms", -1),
    ("sqft", 0),
    ("latitude", 91),
    ("longitude", -181),
    ("latitude", "30.2"),
    ("status", "withdrawn"),
    ("listedDate", "yesterday"),
    ("price", "free"),
    ("zip", "1234"),
    ("state", "Atlantis"),
    ("address", "   "),
    ("id", ""),
    ("description", "x" * 5001),
])
def test_invalid_values_are_rejected(field, value):
    with pytest.raises(ValidationError) as exc:
        listing_from_dict(make_record(**{field: value}))
    assert fields_in_error(exc) == {field}


def test_whole_number_float_bedrooms_are_accepted():
    assert listing_from_dict(make_record(bedrooms=3.0)).bedrooms == 3


def test_non_object_body_is_rejected():
    with pytest.raises(ValidationError):
        listing_from_dict(["not", "an", "object"])


def test_patch_merges_and_renormalizes():
    existing = listing_from_dict(make_record())
    patched = apply_patch(existing, {"price": "$499,000", "city": "dallas", "description": "Now with SOLAR"})
    assert patched.price == 499000.0
    assert patched.city == "Dallas"
    assert patched.city_lc == "dallas"
    assert patched.description_lc == "now with solar"
    assert patched.bedrooms == existing.bedrooms


def test_patch_cannot_change_identity():
    existing = listing_from_dict(make_record())
    with pytest.raises(ValidationError) as exc:
        apply_patch(existing, {"id": "other", "source": "MLS_Z"})
    assert fields_in_error(exc) == {"id", "source"}


def test_patch_with_same_identity_is_allowed():
    existing = listing_from_dict(make_record())
    assert apply_patch(existing, {"id": "A1", "source": "mls_a", "bedrooms": 4}).bedrooms == 4
