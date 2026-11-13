from __future__ import annotations

import json

import pytest

from app import create_app

TODAY = "2026-10-23"


def make_record(**overrides) -> dict:
    record = {
        "id": "A1",
        "source": "MLS_A",
        "address": "100 Main St",
        "city": "Austin",
        "state": "TX",
        "zip": "78701",
        "price": "500000",
        "bedrooms": 3,
        "bathrooms": 2.0,
        "sqft": 1800,
        "latitude": 30.27,
        "longitude": -97.74,
        "listedDate": TODAY,
        "status": "active",
        "description": "Bright home with a pool and updated kitchen.",
    }
    record.update(overrides)
    return record


# Small, hand-crafted dataset with the same kinds of inconsistencies as real feeds.
FIXTURE_RECORDS = [
    make_record(id="A1", price="500000", listedDate="2026-10-23", description="Pool and updated kitchen."),
    make_record(id="A2", price="550000", bedrooms=4, listedDate="2026-09-23", description="Large yard, two-car garage."),
    make_record(id="A3", price="450000", bedrooms=2, listedDate="2026-08-24", status="pending",
                description="Cozy condo near downtown with a whirlpool tub."),
    make_record(id="A4", city="Dallas", zip="75201", price="300000", bedrooms=3, listedDate="2026-10-13",
                description="Renovated ranch with pools of natural light."),
    # Same id as A1 but different source: must coexist.
    make_record(id="A1", source="MLS_B", city=" austin ", state="Texas", zip="78704-1234", price="$1,200,000",
                bedrooms=5, listedDate="2026-07-01", status="sold", description="Luxury estate with a pool."),
    make_record(id="B2", source="MLS_B", city="DENVER", state="co", zip="80202", price="$640,000.00",
                bedrooms=3, listedDate="2026-10-20", description="Mountain views and a home office."),
]


@pytest.fixture
def data_file(tmp_path):
    path = tmp_path / "listings.json"
    path.write_text(json.dumps(FIXTURE_RECORDS), encoding="utf-8")
    return path


@pytest.fixture
def app(data_file):
    return create_app({"DATA_FILE": str(data_file), "REFERENCE_DATE": TODAY, "TESTING": True})


@pytest.fixture
def client(app):
    return app.test_client()
