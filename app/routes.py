"""HTTP layer: /api/v1 listings CRUD + search."""

from __future__ import annotations

from datetime import date, datetime, timezone

from flask import Blueprint, Response, current_app, jsonify, request, url_for

from .errors import UnsupportedMediaTypeError, ValidationError
from .models import apply_patch, check_identity, listing_from_dict
from .repository import ListingRepository
from .search import ScoredListing, parse_search_params, search

api = Blueprint("api", __name__, url_prefix="/api/v1")


def _repo() -> ListingRepository:
    return current_app.extensions["listings_repo"]


def _today() -> date:
    ref = current_app.config.get("REFERENCE_DATE")
    if ref:
        return date.fromisoformat(ref) if isinstance(ref, str) else ref
    return datetime.now(timezone.utc).date()


def _json_body() -> object:
    if not request.is_json:
        raise UnsupportedMediaTypeError("Request body must be JSON (Content-Type: application/json).")
    body = request.get_json(silent=True)
    if body is None:
        raise ValidationError("Request body is not valid JSON.")
    return body


def _location(listing) -> str:
    return url_for("api.get_listing", source=listing.source, listing_id=listing.id)


def _result_item(rank: int, scored: ScoredListing) -> dict:
    score = scored.score
    item = scored.listing.to_dict()
    item["rank"] = rank
    item["relevanceScore"] = round(score.total, 4)
    item["scoreBreakdown"] = {
        "budget": None if score.budget is None else round(score.budget, 4),
        "recency": round(score.recency, 4),
    }
    return item


@api.get("/health")
def health():
    repo = _repo()
    report = repo.ingest_report
    return jsonify({
        "status": "ok",
        "listings": len(repo),
        "ingest": {"skipped": report["skipped"], "duplicates": report["duplicates"]},
    })


@api.get("/listings")
def search_listings():
    cfg = current_app.config
    params = parse_search_params(request.args, cfg["DEFAULT_PAGE_SIZE"], cfg["MAX_PAGE_SIZE"])
    result = search(_repo(), params, _today())
    offset = (result.page - 1) * result.page_size
    return jsonify({
        "data": [_result_item(offset + i + 1, s) for i, s in enumerate(result.items)],
        "pagination": {
            "page": result.page,
            "pageSize": result.page_size,
            "totalItems": result.total,
            "totalPages": result.total_pages,
            "hasNext": result.page < result.total_pages,
            "hasPrevious": result.page > 1 and result.total > 0,
        },
        "query": params.echo(),
    })


@api.get("/locations")
def locations():
    return jsonify(_repo().locations())


@api.post("/listings")
def create_listing():
    listing = _repo().create(listing_from_dict(_json_body()))
    response = jsonify(listing.to_dict())
    response.status_code = 201
    response.headers["Location"] = _location(listing)
    return response


@api.get("/listings/<source>/<listing_id>")
def get_listing(source: str, listing_id: str):
    return jsonify(_repo().get(source, listing_id).to_dict())


@api.put("/listings/<source>/<listing_id>")
def replace_listing(source: str, listing_id: str):
    repo = _repo()
    existing = repo.get(source, listing_id)
    body = _json_body()
    if isinstance(body, dict):
        # id/source come from the URL; the body may omit them.
        body = {"source": existing.source, "id": existing.id, **body}
    listing = listing_from_dict(body)
    check_identity(existing.key, listing)
    return jsonify(repo.replace(listing).to_dict())


@api.patch("/listings/<source>/<listing_id>")
def update_listing(source: str, listing_id: str):
    repo = _repo()
    listing = apply_patch(repo.get(source, listing_id), _json_body())
    return jsonify(repo.replace(listing).to_dict())


@api.delete("/listings/<source>/<listing_id>")
def delete_listing(source: str, listing_id: str):
    _repo().delete(source, listing_id)
    return Response(status=204)
