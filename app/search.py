"""Query-string parsing, filtering, ranking, and pagination."""

from __future__ import annotations

import heapq
import math
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from typing import Mapping

from . import normalize as norm
from .errors import ValidationError
from .models import STATUSES, Listing
from .repository import ListingRepository
from .scoring import Score, score_listing

SORTS = ("relevance", "price_asc", "price_desc", "newest")
SEARCH_PARAMS = frozenset({
    "minPrice", "maxPrice", "minBedrooms", "city", "state", "zip", "keyword",
    "status", "source", "targetBudget", "sort", "page", "pageSize",
})
MAX_KEYWORD_TERMS = 10
_TERM = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass(frozen=True)
class SearchParams:
    min_price: float | None = None
    max_price: float | None = None
    min_bedrooms: int | None = None
    cities: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    zips: tuple[str, ...] = ()
    keyword_terms: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()
    target_budget: float | None = None
    sort: str = "relevance"
    page: int = 1
    page_size: int = 20
    # Raw keyword kept for echoing back to the client.
    keyword: str | None = field(default=None, compare=False)

    def echo(self) -> dict:
        """The effective (normalized) query, so the UI can show what was applied."""
        out = {
            "minPrice": self.min_price,
            "maxPrice": self.max_price,
            "minBedrooms": self.min_bedrooms,
            "city": [norm.normalize_city(c) for c in self.cities] or None,
            "state": list(self.states) or None,
            "zip": list(self.zips) or None,
            "keyword": self.keyword,
            "status": list(self.statuses) or None,
            "source": list(self.sources) or None,
            "targetBudget": self.target_budget,
            "sort": self.sort,
        }
        return {k: v for k, v in out.items() if v is not None}


@dataclass(frozen=True, slots=True)
class ScoredListing:
    listing: Listing
    score: Score


@dataclass(frozen=True)
class SearchResult:
    items: list[ScoredListing]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        return math.ceil(self.total / self.page_size) if self.total else 0


# ---- parsing -------------------------------------------------------------------


def _number(args: Mapping[str, str], name: str, errors: list, *, positive: bool = False) -> float | None:
    raw = args.get(name)
    if raw is None or raw.strip() == "":
        return None
    try:
        value = norm.parse_price(raw) if positive else float(raw)
    except ValueError:
        errors.append({"field": name, "message": f"must be a positive number, got {raw!r}"})
        return None
    if not math.isfinite(value) or value < 0:
        errors.append({"field": name, "message": f"must be a non-negative number, got {raw!r}"})
        return None
    return value


def _integer(args: Mapping[str, str], name: str, errors: list, *, minimum: int, maximum: int | None = None,
             default: int | None = None) -> int | None:
    raw = args.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        errors.append({"field": name, "message": f"must be an integer, got {raw!r}"})
        return default
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"between {minimum} and {maximum}" if maximum is not None else f">= {minimum}"
        errors.append({"field": name, "message": f"must be {bound}, got {value}"})
        return default
    return value


def _csv(args: Mapping[str, str], name: str) -> list[str]:
    """Comma-separated and/or repeated params: ?city=Austin,Dallas&city=Houston."""
    getlist = getattr(args, "getlist", None)
    raws = getlist(name) if getlist else ([args[name]] if name in args else [])
    return [part.strip() for raw in raws for part in raw.split(",") if part.strip()]


def parse_search_params(args: Mapping[str, str], default_page_size: int, max_page_size: int) -> SearchParams:
    errors: list[dict] = []

    unknown = sorted(k for k in args.keys() if k not in SEARCH_PARAMS and not k.startswith("_"))
    for name in unknown:
        errors.append({"field": name, "message": f"unknown query parameter; allowed: {', '.join(sorted(SEARCH_PARAMS))}"})

    min_price = _number(args, "minPrice", errors)
    max_price = _number(args, "maxPrice", errors)
    target = _number(args, "targetBudget", errors, positive=True)
    min_beds = _integer(args, "minBedrooms", errors, minimum=0)
    page = _integer(args, "page", errors, minimum=1, default=1)
    page_size = _integer(args, "pageSize", errors, minimum=1, maximum=max_page_size, default=default_page_size)

    if min_price is not None and max_price is not None and min_price > max_price:
        errors.append({"field": "minPrice", "message": "must be less than or equal to maxPrice"})

    states: list[str] = []
    for raw in _csv(args, "state"):
        try:
            states.append(norm.normalize_state(raw))
        except ValueError as exc:
            errors.append({"field": "state", "message": str(exc)})

    zips: list[str] = []
    for raw in _csv(args, "zip"):
        try:
            zips.append(norm.normalize_zip(raw))
        except ValueError as exc:
            errors.append({"field": "zip", "message": str(exc)})

    statuses = [s.lower() for s in _csv(args, "status")]
    for s in statuses:
        if s not in STATUSES:
            errors.append({"field": "status", "message": f"{s!r} is not one of: {', '.join(STATUSES)}"})

    sort = (args.get("sort") or "relevance").strip().lower()
    if sort not in SORTS:
        errors.append({"field": "sort", "message": f"must be one of: {', '.join(SORTS)}"})
 
    keyword = (args.get("keyword") or "").strip() or None
    terms: list[str] = []
    if keyword:
        terms = list(dict.fromkeys(t.casefold() for t in _TERM.findall(keyword)))
        if not terms:
            errors.append({"field": "keyword", "message": "must contain at least one letter or digit"})
        elif len(terms) > MAX_KEYWORD_TERMS:
            errors.append({"field": "keyword", "message": f"at most {MAX_KEYWORD_TERMS} terms are allowed"})

    if errors:
        raise ValidationError("Invalid search parameters.", errors)

    return SearchParams(
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_beds,
        cities=tuple(dict.fromkeys(norm.city_key(c) for c in _csv(args, "city"))),
        states=tuple(dict.fromkeys(states)),
        zips=tuple(dict.fromkeys(zips)),
        keyword_terms=tuple(terms),
        statuses=tuple(dict.fromkeys(statuses)),
        sources=tuple(dict.fromkeys(s.upper() for s in _csv(args, "source"))),
        target_budget=target,
        sort=sort,
        page=page,
        page_size=page_size,
        keyword=keyword,
    )


# ---- execution -----------------------------------------------------------------


def _keyword_matcher(terms: tuple[str, ...]):
    """All terms must appear, each at the start of a word ('pool' matches
    'pools' and 'pool-side' but not 'whirlpool')."""
    patterns = [(t, re.compile(r"(?<![\w])" + re.escape(t))) for t in terms]
    # The plain substring check is much cheaper and rejects most non-matches
    # before the regex runs.
    return lambda text: all(t in text and p.search(text) for t, p in patterns)


def _sort_key(sort: str):
    # Every ordering ends with a deterministic tie-breaker so pages never
    # shuffle between requests.
    if sort == "price_asc":
        return lambda s: (s.listing.price, -s.score.total, s.listing.key)
    if sort == "price_desc":
        return lambda s: (-s.listing.price, -s.score.total, s.listing.key)
    if sort == "newest":
        return lambda s: (-s.listing.listed_date.toordinal(), -s.score.total, s.listing.key)
    return lambda s: (-s.score.total, -s.listing.listed_date.toordinal(), s.listing.price, s.listing.key)


def search(repo: ListingRepository, params: SearchParams, today: date) -> SearchResult:
    candidates = repo.candidates(cities=params.cities, states=params.states, zips=params.zips)
    matches_keyword = _keyword_matcher(params.keyword_terms) if params.keyword_terms else None
    # Many listings share a price/date; memoize the math for this request.
    score = lru_cache(maxsize=None)(lambda price, listed: score_listing(price, listed, today, params.target_budget))

    scored: list[ScoredListing] = []
    for item in candidates:
        if params.min_price is not None and item.price < params.min_price:
            continue
        if params.max_price is not None and item.price > params.max_price:
            continue
        if params.min_bedrooms is not None and item.bedrooms < params.min_bedrooms:
            continue
        if params.statuses and item.status not in params.statuses:
            continue
        if params.sources and item.source not in params.sources:
            continue
        if matches_keyword and not matches_keyword(item.description_lc):
            continue
        scored.append(ScoredListing(item, score(item.price, item.listed_date)))

    start = (params.page - 1) * params.page_size
    end = start + params.page_size
    key = _sort_key(params.sort)
    if end < len(scored) // 4:
        # Early pages of big result sets: a heap select is O(n log k) vs a full sort.
        ranked = heapq.nsmallest(end, scored, key=key)
    else:
        ranked = sorted(scored, key=key)
    return SearchResult(
        items=ranked[start:end],
        total=len(scored),
        page=params.page,
        page_size=params.page_size,
    )
