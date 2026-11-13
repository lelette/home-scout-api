"""OpenAPI 3.1 spec (served at /openapi.json) and Swagger UI (served at /docs)."""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from .models import STATUSES
from .search import SORTS

docs = Blueprint("docs", __name__)

SWAGGER_UI_VERSION = "5.17.14"


def _error(description: str) -> dict:
    return {"description": description, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}


def _query(name: str, schema: dict, description: str, example=None) -> dict:
    param = {"name": name, "in": "query", "required": False, "schema": schema, "description": description}
    if example is not None:
        param["example"] = example
    return param


PATH_PARAMS = [
    {"name": "source", "in": "path", "required": True, "schema": {"type": "string"}, "example": "MLS_A",
     "description": "Feed the listing came from (case-insensitive)."},
    {"name": "listing_id", "in": "path", "required": True, "schema": {"type": "string"}, "example": "A-1001",
     "description": "Listing id, unique within its source."},
]

LISTING_PROPERTIES = {
    "id": {"type": "string", "example": "A-1001", "description": "Unique per source."},
    "source": {"type": "string", "example": "MLS_A", "description": "Feed name; stored upper-case."},
    "address": {"type": "string", "example": "1208 W 6th St"},
    "city": {"type": "string", "example": "Austin", "description": "Normalized to title case."},
    "state": {"type": "string", "example": "TX",
              "description": "Accepts names or codes ('texas', 'Tx'); stored as a 2-letter code."},
    "zip": {"type": "string", "example": "78703", "description": "Accepts ZIP+4; stored as 5 digits."},
    "price": {"oneOf": [{"type": "number"}, {"type": "string"}], "example": "$525,000",
              "description": "List price in USD. Accepts '$525,000' or 525000; returned as a number."},
    "bedrooms": {"type": "integer", "minimum": 0, "example": 3},
    "bathrooms": {"type": "number", "minimum": 0, "multipleOf": 0.25, "example": 2.5},
    "sqft": {"type": "integer", "minimum": 1, "example": 1850},
    "latitude": {"type": "number", "minimum": -90, "maximum": 90, "example": 30.2711},
    "longitude": {"type": "number", "minimum": -180, "maximum": 180, "example": -97.7612},
    "listedDate": {"type": "string", "format": "date", "example": "2026-10-01"},
    "status": {"type": "string", "enum": list(STATUSES), "example": "active"},
    "description": {"type": "string", "example": "Renovated bungalow with a pool and updated kitchen."},
}
REQUIRED = [k for k in LISTING_PROPERTIES if k != "description"]


def build_spec() -> dict:
    from . import __version__

    cfg = current_app.config
    listing_out = {
        "type": "object",
        "properties": {**LISTING_PROPERTIES, "price": {"type": "number", "example": 525000}},
        "required": list(LISTING_PROPERTIES),
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "MLS Listing Search API",
            "version": __version__,
            "description": (
                "Search, rank, and manage real-estate listings aggregated from multiple MLS feeds.\n\n"
                "**Identity:** listing ids are only unique per feed, so every listing is addressed as "
                "`/listings/{source}/{id}`.\n\n"
                "**Ranking:** `relevanceScore` is in [0, 1]. With `targetBudget`: "
                "`0.6 * budgetFit + 0.4 * recency`; without it: `recency`. "
                "`budgetFit = 0.5 ** ((d / tol) ** 2)` where `d` is the relative price deviation and "
                "`tol` is 10% over budget / 25% under. `recency = 0.5 ** (ageDays / 30)`. "
                "See README.md for the reasoning.\n\n"
                "**Errors** always use the `Error` envelope with a machine-readable `code` and, for "
                "validation problems, a per-field `details` list."
            ),
        },
        "servers": [{"url": "/"}],
        "tags": [
            {"name": "Search", "description": "Filter, rank, and paginate listings."},
            {"name": "Listings", "description": "CRUD for individual listings."},
            {"name": "Meta", "description": "Health and reference data."},
        ],
        "paths": {
            "/api/v1/listings": {
                "get": {
                    "tags": ["Search"],
                    "summary": "Search listings",
                    "description": (
                        "All filters are optional and combine with AND. `city`, `state`, `zip`, `status` and "
                        "`source` accept comma-separated or repeated values, which combine with OR "
                        "(e.g. `city=Austin,Round Rock`). Omit every filter to list everything.\n\n"
                        "Unknown parameters are rejected (400) to catch typos; parameters starting with `_` "
                        "(cache-busters) are ignored."
                    ),
                    "operationId": "searchListings",
                    "parameters": [
                        _query("minPrice", {"type": "number", "minimum": 0}, "Minimum list price (inclusive).", 300000),
                        _query("maxPrice", {"type": "number", "minimum": 0}, "Maximum list price (inclusive).", 700000),
                        _query("minBedrooms", {"type": "integer", "minimum": 0}, "Minimum bedrooms (inclusive).", 3),
                        _query("city", {"type": "string"}, "City name(s), case/whitespace-insensitive.", "Austin"),
                        _query("state", {"type": "string"}, "State code(s) or name(s).", "TX"),
                        _query("zip", {"type": "string"}, "5-digit ZIP(s); ZIP+4 accepted.", "78704"),
                        _query("keyword", {"type": "string"},
                               "Free text matched against the description. Every word must appear at the start "
                               "of a word ('pool' matches 'pools', not 'whirlpool'). Case-insensitive.",
                               "pool renovated"),
                        _query("status", {"type": "string"}, f"One or more of: {', '.join(STATUSES)}.", "active"),
                        _query("source", {"type": "string"}, "Feed name(s).", "MLS_A"),
                        _query("targetBudget", {"type": "number", "exclusiveMinimum": 0},
                               "Ideal price. Enables budget-fit scoring.", 500000),
                        _query("sort", {"type": "string", "enum": list(SORTS), "default": "relevance"},
                               "Result ordering. Scores are returned for every ordering."),
                        _query("page", {"type": "integer", "minimum": 1, "default": 1},
                               "1-based page number. Pages past the end return an empty `data` array."),
                        _query("pageSize", {"type": "integer", "minimum": 1, "maximum": cfg["MAX_PAGE_SIZE"],
                                            "default": cfg["DEFAULT_PAGE_SIZE"]}, "Results per page."),
                    ],
                    "responses": {
                        "200": {"description": "A page of ranked results.",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SearchResponse"}}}},
                        "400": _error("Invalid parameter(s); see `details`."),
                    },
                },
                "post": {
                    "tags": ["Listings"],
                    "summary": "Create a listing",
                    "operationId": "createListing",
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/ListingInput"}}}},
                    "responses": {
                        "201": {"description": "Created. `Location` header points at the new listing.",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Listing"}}}},
                        "400": _error("Validation failed."),
                        "409": _error("A listing with this source + id already exists."),
                        "415": _error("Body is not JSON."),
                    },
                },
            },
            "/api/v1/listings/{source}/{listing_id}": {
                "parameters": PATH_PARAMS,
                "get": {
                    "tags": ["Listings"], "summary": "Get a listing", "operationId": "getListing",
                    "responses": {
                        "200": {"description": "The listing.",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Listing"}}}},
                        "404": _error("Not found."),
                    },
                },
                "put": {
                    "tags": ["Listings"], "summary": "Replace a listing",
                    "description": "Full replacement. `id`/`source` may be omitted; if present they must match the URL.",
                    "operationId": "replaceListing",
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/ListingInput"}}}},
                    "responses": {
                        "200": {"description": "Updated.",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Listing"}}}},
                        "400": _error("Validation failed."), "404": _error("Not found."), "415": _error("Body is not JSON."),
                    },
                },
                "patch": {
                    "tags": ["Listings"], "summary": "Partially update a listing",
                    "description": "Only the supplied fields change. `id` and `source` are immutable.",
                    "operationId": "updateListing",
                    "requestBody": {"required": True, "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/ListingPatch"},
                        "example": {"status": "pending", "price": 499000}}}},
                    "responses": {
                        "200": {"description": "Updated.",
                                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Listing"}}}},
                        "400": _error("Validation failed."), "404": _error("Not found."), "415": _error("Body is not JSON."),
                    },
                },
                "delete": {
                    "tags": ["Listings"], "summary": "Delete a listing", "operationId": "deleteListing",
                    "responses": {"204": {"description": "Deleted."}, "404": _error("Not found.")},
                },
            },
            "/api/v1/locations": {
                "get": {
                    "tags": ["Meta"], "summary": "Distinct states, cities and ZIPs with listing counts",
                    "description": "Useful for populating location dropdowns / autocomplete in the frontend.",
                    "operationId": "listLocations",
                    "responses": {"200": {"description": "Location facets.", "content": {"application/json": {
                        "schema": {"$ref": "#/components/schemas/Locations"}}}}},
                },
            },
            "/api/v1/health": {
                "get": {
                    "tags": ["Meta"], "summary": "Health check", "operationId": "health",
                    "responses": {"200": {"description": "Service is up.", "content": {"application/json": {
                        "schema": {"type": "object", "properties": {
                            "status": {"type": "string", "example": "ok"},
                            "listings": {"type": "integer"},
                            "ingest": {"type": "object", "properties": {
                                "skipped": {"type": "integer"}, "duplicates": {"type": "integer"}}},
                        }}}}}},
                },
            },
        },
        "components": {
            "schemas": {
                "Listing": listing_out,
                "ListingInput": {"type": "object", "properties": LISTING_PROPERTIES, "required": REQUIRED,
                                 "additionalProperties": False},
                "ListingPatch": {"type": "object", "properties": LISTING_PROPERTIES, "additionalProperties": False},
                "RankedListing": {"allOf": [{"$ref": "#/components/schemas/Listing"}, {"type": "object", "properties": {
                    "rank": {"type": "integer", "description": "1-based position across all pages.", "example": 1},
                    "relevanceScore": {"type": "number", "minimum": 0, "maximum": 1, "example": 0.8731},
                    "scoreBreakdown": {"type": "object", "properties": {
                        "budget": {"type": ["number", "null"], "description": "null when no targetBudget."},
                        "recency": {"type": "number"}}},
                }}]},
                "SearchResponse": {"type": "object", "properties": {
                    "data": {"type": "array", "items": {"$ref": "#/components/schemas/RankedListing"}},
                    "pagination": {"type": "object", "properties": {
                        "page": {"type": "integer"}, "pageSize": {"type": "integer"},
                        "totalItems": {"type": "integer"}, "totalPages": {"type": "integer"},
                        "hasNext": {"type": "boolean"}, "hasPrevious": {"type": "boolean"}}},
                    "query": {"type": "object", "description": "The normalized filters that were applied."},
                }},
                "Locations": {"type": "object", "properties": {
                    "states": {"type": "array", "items": {"type": "object", "properties": {
                        "state": {"type": "string"}, "count": {"type": "integer"}}}},
                    "cities": {"type": "array", "items": {"type": "object", "properties": {
                        "city": {"type": "string"}, "state": {"type": "string"}, "count": {"type": "integer"}}}},
                    "zips": {"type": "array", "items": {"type": "object", "properties": {
                        "zip": {"type": "string"}, "city": {"type": "string"}, "state": {"type": "string"},
                        "count": {"type": "integer"}}}},
                }},
                "Error": {"type": "object", "properties": {"error": {"type": "object", "properties": {
                    "status": {"type": "integer", "example": 400},
                    "code": {"type": "string", "example": "validation_error"},
                    "message": {"type": "string", "example": "Invalid search parameters."},
                    "details": {"type": "array", "items": {"type": "object", "properties": {
                        "field": {"type": "string", "example": "minPrice"},
                        "message": {"type": "string", "example": "must be less than or equal to maxPrice"}}}},
                }, "required": ["status", "code", "message"]}}},
            },
        },
    }


@docs.get("/openapi.json")
def openapi_json():
    return jsonify(build_spec())


@docs.get("/docs")
def swagger_ui():
    v = SWAGGER_UI_VERSION
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>MLS Listing Search API — Docs</title>
<link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@{v}/swagger-ui.css"></head>
<body><div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@{v}/swagger-ui-bundle.js" crossorigin></script>
<script>window.ui = SwaggerUIBundle({{url: "/openapi.json", dom_id: "#swagger-ui", deepLinking: true}});</script>
</body></html>"""
