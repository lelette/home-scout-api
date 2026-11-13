import json

import pytest

from app.errors import ConflictError, NotFoundError
from app.models import apply_patch, listing_from_dict
from app.repository import DataFileError, ListingRepository

from .conftest import make_record


def write(tmp_path, payload) -> str:
    path = tmp_path / "data.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
    return path


def test_ingest_skips_invalid_records_and_reports_them(tmp_path):
    records = [make_record(id="ok"), make_record(id="bad", price="free"), "not-an-object", make_record(id="ok2")]
    repo = ListingRepository.from_json_file(write(tmp_path, records))
    assert len(repo) == 2
    report = repo.ingest_report
    assert report["skipped"] == 2 and report["loaded"] == 2
    assert report["errors"][0]["id"] == "bad"
    assert report["errors"][0]["index"] == 1


def test_ingest_same_id_different_sources_coexist(tmp_path):
    repo = ListingRepository.from_json_file(write(tmp_path, [make_record(source="MLS_A"), make_record(source="MLS_B")]))
    assert len(repo) == 2


def test_ingest_duplicate_within_source_keeps_last(tmp_path):
    repo = ListingRepository.from_json_file(write(tmp_path, [make_record(price="1"), make_record(price="2")]))
    assert len(repo) == 1
    assert repo.get("MLS_A", "A1").price == 2
    assert repo.ingest_report["duplicates"] == 1


def test_ingest_accepts_wrapped_object(tmp_path):
    repo = ListingRepository.from_json_file(write(tmp_path, {"listings": [make_record()]}))
    assert len(repo) == 1


def test_empty_array_is_valid(tmp_path):
    assert len(ListingRepository.from_json_file(write(tmp_path, []))) == 0


@pytest.mark.parametrize("payload", ["{not json", '{"foo": 1}', '"string"'])
def test_bad_data_file_raises(tmp_path, payload):
    with pytest.raises(DataFileError):
        ListingRepository.from_json_file(write(tmp_path, payload))


def test_missing_data_file_raises(tmp_path):
    with pytest.raises(DataFileError):
        ListingRepository.from_json_file(tmp_path / "nope.json")


def test_lookup_is_case_insensitive_on_source():
    repo = ListingRepository([listing_from_dict(make_record())])
    assert repo.get("mls_a", " A1 ").id == "A1"


def test_create_conflict_and_delete_not_found():
    listing = listing_from_dict(make_record())
    repo = ListingRepository([listing])
    with pytest.raises(ConflictError):
        repo.create(listing)
    repo.delete("MLS_A", "A1")
    with pytest.raises(NotFoundError):
        repo.delete("MLS_A", "A1")


def test_indexes_follow_updates():
    listing = listing_from_dict(make_record())
    repo = ListingRepository([listing])
    repo.replace(apply_patch(listing, {"city": "Dallas", "state": "TX", "zip": "75201"}))
    assert repo.candidates(cities=["austin"]) == []
    assert [x.id for x in repo.candidates(cities=["dallas"], zips=["75201"])] == ["A1"]
    repo.delete("MLS_A", "A1")
    assert repo.candidates(cities=["dallas"]) == []
    assert repo.locations() == {"states": [], "cities": [], "zips": []}


def test_locations_counts():
    repo = ListingRepository([
        listing_from_dict(make_record(id="1")),
        listing_from_dict(make_record(id="2", city="austin")),
        listing_from_dict(make_record(id="3", city="Denver", state="CO", zip="80202")),
    ])
    locs = repo.locations()
    assert {"city": "Austin", "state": "TX", "count": 2} in locs["cities"]
    assert {"state": "CO", "count": 1} in locs["states"]


def test_persistence_writes_atomically_and_reloads(tmp_path):
    path = write(tmp_path, [make_record()])
    repo = ListingRepository.from_json_file(path, persist=True)
    repo.create(listing_from_dict(make_record(id="new", price="$725,000")))
    saved = json.loads(path.read_text())
    assert {r["id"] for r in saved} == {"A1", "new"}
    assert not list(tmp_path.glob(".listings-*"))  # temp file cleaned up
    reloaded = ListingRepository.from_json_file(path)
    assert reloaded.get("MLS_A", "new").price == 725000


def test_persistence_off_leaves_file_untouched(tmp_path):
    path = write(tmp_path, [make_record()])
    before = path.read_text()
    ListingRepository.from_json_file(path).delete("MLS_A", "A1")
    assert path.read_text() == before
