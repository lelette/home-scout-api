"""Normalization helpers for inconsistent multi-source MLS data.

Feeds disagree on formatting ("Austin " vs "austin", "Texas" vs "TX",
"78701-1234" vs "78701", "$450,000" vs "450000"). Everything is normalized
once at ingest/write time so that filtering and indexing can use cheap
exact-match lookups at query time.
"""

from __future__ import annotations

import re
from datetime import date, datetime

US_STATES = {
    "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR",
    "CALIFORNIA": "CA", "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE",
    "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA", "HAWAII": "HI",
    "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
    "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS",
    "MISSOURI": "MO", "MONTANA": "MT", "NEBRASKA": "NE", "NEVADA": "NV",
    "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM", "NEW YORK": "NY",
    "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
    "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI",
    "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX",
    "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
    "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
}
STATE_CODES = frozenset(US_STATES.values())

_WS = re.compile(r"\s+")
_ZIP = re.compile(r"^(\d{5})(?:[-\s]?\d{4})?$")
_PRICE_JUNK = re.compile(r"[\s$,]|USD", re.IGNORECASE)


def collapse_ws(value: str) -> str:
    return _WS.sub(" ", value).strip()


def normalize_city(value: str) -> str:
    """'  san   ANTONIO ' -> 'San Antonio'. Keeps internal punctuation."""
    city = collapse_ws(value).rstrip(".,")
    if not city:
        raise ValueError("must not be empty")
    return " ".join(word[:1].upper() + word[1:].lower() for word in city.split(" "))


def city_key(value: str) -> str:
    """Case-insensitive key used for indexing and filter matching."""
    return collapse_ws(value).rstrip(".,").casefold()


def normalize_state(value: str) -> str:
    """'tx', 'Tex', 'Texas', ' TX. ' -> 'TX'. Raises ValueError if unknown."""
    state = collapse_ws(value).rstrip(".").upper()
    if state in STATE_CODES:
        return state
    if state in US_STATES:
        return US_STATES[state]
    if state.replace(".", "") in STATE_CODES:  # "T.X."
        return state.replace(".", "")
    raise ValueError(f"unknown US state {value!r}")


def normalize_zip(value: str | int) -> str:
    """'78701-1234', '78701 1234', 78701, ' 78701 ' -> '78701'.

    Integers are left-padded because some feeds drop leading zeros (02134 -> 2134).
    """
    if isinstance(value, bool):
        raise ValueError("must be a 5-digit ZIP code")
    if isinstance(value, int):
        value = f"{value:05d}"
    match = _ZIP.match(value.strip())
    if not match:
        raise ValueError(f"invalid ZIP code {value!r}; expected 5 digits or ZIP+4")
    return match.group(1)


def parse_price(value: str | int | float) -> float:
    """'$450,000', '450000.00', 'USD 450,000', 450000 -> 450000.0."""
    if isinstance(value, bool):
        raise ValueError("must be a number or numeric string")
    if isinstance(value, (int, float)):
        price = float(value)
    elif isinstance(value, str):
        cleaned = _PRICE_JUNK.sub("", value)
        try:
            price = float(cleaned)
        except ValueError:
            raise ValueError(f"invalid price {value!r}") from None
    else:
        raise ValueError("must be a number or numeric string")
    if price != price or price in (float("inf"), float("-inf")):
        raise ValueError("must be a finite number")
    if price <= 0:
        raise ValueError("must be greater than 0")
    return price


def parse_iso_date(value: str) -> date:
    """Accepts '2026-10-01' and full ISO datetimes ('2026-10-01T12:00:00Z')."""
    if not isinstance(value, str):
        raise ValueError("must be an ISO-8601 date string")
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        raise ValueError(f"invalid ISO date {value!r}") from None
