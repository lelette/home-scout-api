"""End-to-end tests through the Flask test client."""

import json

import pytest

from app import create_app

from .conftest import FIXTURE_RECORDS, TODAY, make_record

LISTINGS = "/api/v1/listings"


def error_fields(resp) -> set[str]:
    return {d["field"] for d in resp.get_json()["error"].get("details", [])}


# ---- search ----------------------------------------------------------------------


def test_search_response_shape(client):
    resp = client.get(f"{LISTINGS}?targetBudget=500000&pageSize=2")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["pagination"] == {
        "page": 1, "pageSize": 2, "totalItems": len(FIXTURE_RECORDS), "totalPages": 3,
        "hasNext": True, "hasPrevious": False,
    }
    first = body["data"][0]
    for key in ("address", "price", "bedrooms", "relevanceScore", "rank", "scoreBreakdown"):
        assert key in first
    assert first["rank"] == 1
    assert body["query"]["targetBudget"] == 500000


def test_best_match_ranks_first(client):
    body = client.get(f"{LISTINGS}?targetBudget=500000").get_json()
    top = body["data"][0]
    assert (top["source"], top["id"]) == ("MLS_A", "A1")  # exact budget, listed today
    assert top["relevanceScore"] == 1.0
    scores = [d["relevanceScore"] for d in body["data"]]
    assert scores == sorted(scores, reverse=True)


def test_ranks_continue_across_pages(client):
    page2 = client.get(f"{LISTINGS}?pageSize=2&page=2").get_json()
    assert [d["rank"] for d in page2["data"]] == [3, 4]
    assert page2["pagination"]["hasPrevious"] is True


def test_page_past_end_returns_empty_200(client):
    resp = client.get(f"{LISTINGS}?page=50")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["data"] == [] and body["pagination"]["hasNext"] is False


def test_search_by_city_state_zip_combined(client):
    body = client.get(f"{LISTINGS}?city=austin&state=Texas&zip=78704").get_json()
    assert [(d["source"], d["id"]) for d in body["data"]] == [("MLS_B", "A1")]
    assert body["data"][0]["city"] == "Austin"   # normalized output
    assert body["data"][0]["zip"] == "78704"
    assert body["query"]["city"] == ["Austin"]


def test_search_filters_through_http(client):
    body = client.get(f"{LISTINGS}?minPrice=400000&maxPrice=600000&minBedrooms=3&keyword=kitchen").get_json()
    assert [d["id"] for d in body["data"]] == ["A1"]


def test_score_breakdown_budget_null_without_target(client):
    item = client.get(LISTINGS).get_json()["data"][0]
    assert item["scoreBreakdown"]["budget"] is None


def test_invalid_search_returns_400_with_details(client):
    resp = client.get(f"{LISTINGS}?minPrice=10&maxPrice=1&page=0&minprice=4")
    assert resp.status_code == 400
    body = resp.get_json()["error"]
    assert body["code"] == "validation_error"
    assert {"minPrice", "page", "minprice"} <= error_fields(resp)


# ---- CRUD ------------------------------------------------------------------------


def test_get_listing(client):
    resp = client.get(f"{LISTINGS}/mls_b/A1")
    assert resp.status_code == 200
    assert resp.get_json()["price"] == 1200000


def test_get_missing_listing_404(client):
    resp = client.get(f"{LISTINGS}/MLS_A/nope")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_create_then_search(client):
    record = make_record(id="NEW1", city="Round Rock", zip="78664", price="$410,000", description="Fresh listing")
    resp = client.post(LISTINGS, json=record)
    assert resp.status_code == 201
    assert resp.headers["Location"].endswith("/api/v1/listings/MLS_A/NEW1")
    assert resp.get_json()["price"] == 410000
    found = client.get(f"{LISTINGS}?city=round rock").get_json()["data"]
    assert [d["id"] for d in found] == ["NEW1"]


def test_create_duplicate_409(client):
    resp = client.post(LISTINGS, json=FIXTURE_RECORDS[0])
    assert resp.status_code == 409
    assert resp.get_json()["error"]["code"] == "conflict"


def test_create_invalid_400(client):
    resp = client.post(LISTINGS, json=make_record(id="X", bedrooms="three", extra=1))
    assert resp.status_code == 400
    assert error_fields(resp) == {"bedrooms", "extra"}


def test_create_requires_json_content_type(client):
    resp = client.post(LISTINGS, data="id=1", content_type="application/x-www-form-urlencoded")
    assert resp.status_code == 415
    assert resp.get_json()["error"]["code"] == "unsupported_media_type"


def test_create_malformed_json_400(client):
    resp = client.post(LISTINGS, data="{bad json", content_type="application/json")
    assert resp.status_code == 400


def test_create_non_object_json_400(client):
    resp = client.post(LISTINGS, json=[1, 2, 3])
    assert resp.status_code == 400


def test_put_replaces_and_can_omit_identity(client):
    record = make_record(price="610000", bedrooms=4)
    del record["id"], record["source"]
    resp = client.put(f"{LISTINGS}/MLS_A/A1", json=record)
    assert resp.status_code == 200
    assert resp.get_json()["price"] == 610000
    assert client.get(f"{LISTINGS}/MLS_A/A1").get_json()["bedrooms"] == 4


def test_put_identity_mismatch_400(client):
    resp = client.put(f"{LISTINGS}/MLS_A/A1", json=make_record(id="other"))
    assert resp.status_code == 400
    assert error_fields(resp) == {"id"}


def test_put_missing_404(client):
    assert client.put(f"{LISTINGS}/MLS_A/ghost", json=make_record(id="ghost")).status_code == 404


def test_patch_updates_fields_and_indexes(client):
    resp = client.patch(f"{LISTINGS}/MLS_A/A1", json={"status": "PENDING", "city": "dallas"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "pending"
    dallas = client.get(f"{LISTINGS}?city=Dallas").get_json()["data"]
    assert ("MLS_A", "A1") in {(d["source"], d["id"]) for d in dallas}


def test_patch_invalid_value_400_and_no_change(client):
    resp = client.patch(f"{LISTINGS}/MLS_A/A1", json={"price": -5})
    assert resp.status_code == 400
    assert client.get(f"{LISTINGS}/MLS_A/A1").get_json()["price"] == 500000


def test_patch_immutable_identity_400(client):
    resp = client.patch(f"{LISTINGS}/MLS_A/A1", json={"source": "MLS_Z"})
    assert resp.status_code == 400


def test_delete(client):
    assert client.delete(f"{LISTINGS}/MLS_A/A1").status_code == 204
    assert client.get(f"{LISTINGS}/MLS_A/A1").status_code == 404
    assert client.delete(f"{LISTINGS}/MLS_A/A1").status_code == 404
    # Same id in the other feed is untouched.
    assert client.get(f"{LISTINGS}/MLS_B/A1").status_code == 200


def test_crud_persists_when_enabled(data_file):
    app = create_app({"DATA_FILE": str(data_file), "PERSIST_CHANGES": True, "REFERENCE_DATE": TODAY})
    app.test_client().delete(f"{LISTINGS}/MLS_A/A1")
    saved = json.loads(data_file.read_text())
    assert ("MLS_A", "A1") not in {(r["source"], r["id"]) for r in saved}
    assert len(saved) == len(FIXTURE_RECORDS) - 1


# ---- misc ------------------------------------------------------------------------


def test_method_not_allowed_is_json(client):
    resp = client.delete(LISTINGS)
    assert resp.status_code == 405
    assert resp.get_json()["error"]["code"] == "method_not_allowed"
    assert "GET" in resp.headers["Allow"]


def test_unknown_route_is_json_404(client):
    resp = client.get("/api/v1/nothing")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["status"] == 404


def test_oversized_body_413(client):
    resp = client.post(LISTINGS, data="x" * (2 * 1024 * 1024), content_type="application/json")
    assert resp.status_code == 413


def test_unexpected_error_is_json_500(app, monkeypatch):
    import app.routes as routes

    def boom(*_a, **_k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(routes, "search", boom)
    resp = app.test_client().get(LISTINGS)
    assert resp.status_code == 500
    body = resp.get_json()["error"]
    assert body["code"] == "internal_error"
    assert "kaboom" not in body["message"]  # internals are not leaked


def test_health(client):
    body = client.get("/api/v1/health").get_json()
    assert body == {"status": "ok", "listings": len(FIXTURE_RECORDS), "ingest": {"skipped": 0, "duplicates": 0}}


def test_locations(client):
    body = client.get("/api/v1/locations").get_json()
    assert {"state": "TX", "count": 5} in body["states"]
    assert {"city": "Austin", "state": "TX", "count": 4} in body["cities"]


def test_docs_and_spec(client):
    spec = client.get("/openapi.json").get_json()
    assert spec["openapi"].startswith("3.")
    assert {"/api/v1/listings", "/api/v1/listings/{source}/{listing_id}"} <= set(spec["paths"])
    documented = {p["name"] for p in spec["paths"]["/api/v1/listings"]["get"]["parameters"]}
    from app.search import SEARCH_PARAMS
    assert documented == SEARCH_PARAMS  # docs never drift from the parser
    assert b"swagger-ui" in client.get("/docs").data
    assert client.get("/").status_code == 302


def test_cors_headers(client):
    resp = client.get(LISTINGS, headers={"Origin": "http://localhost:3000"})
    assert resp.headers["Access-Control-Allow-Origin"] == "*"
    preflight = client.options(LISTINGS, headers={"Origin": "http://localhost:3000",
                                                  "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 200
    assert "POST" in preflight.headers["Access-Control-Allow-Methods"]


@pytest.mark.parametrize("origin, allowed", [("http://app.example.com", True), ("http://evil.example", False)])
def test_cors_allowlist(data_file, origin, allowed):
    app = create_app({"DATA_FILE": str(data_file), "CORS_ORIGINS": "http://app.example.com"})
    resp = app.test_client().get(LISTINGS, headers={"Origin": origin})
    assert ("Access-Control-Allow-Origin" in resp.headers) is allowed


def test_bundled_sample_data_loads_cleanly():
    app = create_app({"REFERENCE_DATE": TODAY})
    body = app.test_client().get("/api/v1/health").get_json()
    assert body["listings"] == 80 and body["ingest"]["skipped"] == 0
