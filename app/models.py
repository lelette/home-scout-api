"""Listing model, validation, and (de)serialization."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Callable

from . import normalize as norm
from .errors import ValidationError

STATUSES = ("active", "pending", "sold")

MAX_TEXT = {"id": 100, "source": 50, "address": 300, "city": 100, "description": 5000}


@dataclass(frozen=True, slots=True)
class Listing:
    id: str
    source: str
    address: str
    city: str
    state: str
    zip: str
    price: float
    bedrooms: int
    bathrooms: float
    sqft: int
    latitude: float
    longitude: float
    listed_date: date
    status: str
    description: str = ""
    # Derived, precomputed once so search never re-lowercases text per request.
    description_lc: str = field(default="", init=False, repr=False, compare=False)
    city_lc: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "description_lc", self.description.casefold())
        object.__setattr__(self, "city_lc", norm.city_key(self.city))

    @property
    def key(self) -> tuple[str, str]:
        """Listings are only unique per source, so the identity is (source, id)."""
        return (self.source, self.id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "address": self.address,
            "city": self.city,
            "state": self.state,
            "zip": self.zip,
            "price": int(self.price) if self.price.is_integer() else self.price,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "sqft": self.sqft,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "listedDate": self.listed_date.isoformat(),
            "status": self.status,
            "description": self.description,
        }


# --- field parsers: each takes the raw JSON value and returns the clean value or
# raises ValueError with a human-readable message.


def _text(name: str, allow_empty: bool = False) -> Callable[[Any], str]:
    def parse(value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        text = norm.collapse_ws(value)
        if not text and not allow_empty:
            raise ValueError("must not be empty")
        if len(text) > MAX_TEXT[name]:
            raise ValueError(f"must be at most {MAX_TEXT[name]} characters")
        return text

    return parse


def _int(minimum: int, maximum: int) -> Callable[[Any], int]:
    def parse(value: Any) -> int:
        # bool is a subclass of int in Python; `true` is not a bedroom count.
        if isinstance(value, bool):
            raise ValueError("must be an integer")
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        if not isinstance(value, int):
            raise ValueError("must be an integer")
        if not minimum <= value <= maximum:
            raise ValueError(f"must be between {minimum} and {maximum}")
        return value

    return parse


def _float(minimum: float, maximum: float) -> Callable[[Any], float]:
    def parse(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("must be a number")
        if not math.isfinite(value):
            raise ValueError("must be a finite number")
        if not minimum <= value <= maximum:
            raise ValueError(f"must be between {minimum} and {maximum}")
        return float(value)

    return parse


def _bathrooms(value: Any) -> float:
    baths = _float(0, 50)(value)
    if (baths * 4) % 1:
        raise ValueError("must be a multiple of 0.25 (e.g. 2, 2.5, 2.75)")
    return baths


def _status(value: Any) -> str:
    if not isinstance(value, str) or value.strip().lower() not in STATUSES:
        raise ValueError(f"must be one of: {', '.join(STATUSES)}")
    return value.strip().lower()


def _source(value: Any) -> str:
    return _text("source")(value).upper()


def _wrap(fn: Callable[[str], Any]) -> Callable[[Any], Any]:
    def parse(value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return fn(value)

    return parse


def _zip(value: Any) -> str:
    if not isinstance(value, (str, int)):
        raise ValueError("must be a string")
    return norm.normalize_zip(value)


# JSON field name -> (dataclass attribute, parser, required)
FIELD_SPECS: dict[str, tuple[str, Callable[[Any], Any], bool]] = {
    "id": ("id", _text("id"), True),
    "source": ("source", _source, True),
    "address": ("address", _text("address"), True),
    "city": ("city", _wrap(norm.normalize_city), True),
    "state": ("state", _wrap(norm.normalize_state), True),
    "zip": ("zip", _zip, True),
    "price": ("price", norm.parse_price, True),
    "bedrooms": ("bedrooms", _int(0, 100), True),
    "bathrooms": ("bathrooms", _bathrooms, True),
    "sqft": ("sqft", _int(1, 1_000_000), True),
    "latitude": ("latitude", _float(-90, 90), True),
    "longitude": ("longitude", _float(-180, 180), True),
    "listedDate": ("listed_date", norm.parse_iso_date, True),
    "status": ("status", _status, True),
    "description": ("description", _text("description", allow_empty=True), False),
}
IMMUTABLE_FIELDS = ("id", "source")


def _parse_fields(payload: Any, required: bool) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object.")

    errors: list[dict] = []
    for unknown in sorted(set(payload) - set(FIELD_SPECS)):
        errors.append({"field": unknown, "message": "unknown field"})

    values: dict[str, Any] = {}
    for name, (attr, parser, is_required) in FIELD_SPECS.items():
        if name not in payload or payload[name] is None:
            if required and is_required:
                errors.append({"field": name, "message": "is required"})
            continue
        try:
            values[attr] = parser(payload[name])
        except ValueError as exc:
            errors.append({"field": name, "message": str(exc)})

    if errors:
        raise ValidationError("Listing failed validation.", errors)
    return values


def listing_from_dict(payload: Any) -> Listing:
    """Validate + normalize a full listing (ingest, POST, PUT)."""
    return Listing(**_parse_fields(payload, required=True))


def apply_patch(existing: Listing, payload: Any) -> Listing:
    """Validate a partial update (PATCH) and return the merged listing."""
    merged = replace(existing, **_parse_fields(payload, required=False))
    check_identity(existing.key, merged)
    return merged


def check_identity(existing_key: tuple[str, str], listing: Listing) -> None:
    """PUT bodies may repeat id/source, but they must match the URL."""
    errors = []
    if listing.source != existing_key[0]:
        errors.append({"field": "source", "message": "cannot be changed; must match the URL"})
    if listing.id != existing_key[1]:
        errors.append({"field": "id", "message": "cannot be changed; must match the URL"})
    if errors:
        raise ValidationError("Listing identity cannot be changed.", errors)

