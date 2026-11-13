"""In-memory listing store backed by a JSON file (the "mock database").

- Identity is (source, id): ids are only unique within a feed.
- Secondary indexes on city / state / zip make location lookups O(1) to find
  the candidate set instead of scanning every listing.
- Listings are immutable dataclasses, so readers can safely work on a snapshot
  taken under the lock while writers swap objects in.
- Optional write-through persistence uses write-to-temp + os.replace so a crash
  never leaves a half-written data file.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .errors import ConflictError, NotFoundError, ValidationError
from .models import Listing, listing_from_dict

log = logging.getLogger(__name__)

Key = tuple[str, str]


class DataFileError(RuntimeError):
    """The data file is missing or not a JSON array; the app cannot start."""


class ListingRepository:
    def __init__(self, listings: Iterable[Listing] = (), persist_path: Path | None = None):
        self._lock = threading.RLock()
        self._items: dict[Key, Listing] = {}
        self._by_city: dict[str, set[Key]] = defaultdict(set)
        self._by_state: dict[str, set[Key]] = defaultdict(set)
        self._by_zip: dict[str, set[Key]] = defaultdict(set)
        self._persist_path = persist_path
        self.ingest_report: dict = {"loaded": 0, "skipped": 0, "duplicates": 0, "errors": []}
        for listing in listings:
            self._put(listing)

    # ---- loading -------------------------------------------------------------

    @classmethod
    def from_json_file(cls, path: str | Path, persist: bool = False) -> "ListingRepository":
        path = Path(path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise DataFileError(f"Data file not found: {path}") from None
        except json.JSONDecodeError as exc:
            raise DataFileError(f"Data file {path} is not valid JSON: {exc}") from None
        if isinstance(raw, dict) and isinstance(raw.get("listings"), list):
            raw = raw["listings"]
        if not isinstance(raw, list):
            raise DataFileError(f"Data file {path} must contain a JSON array of listings")

        repo = cls(persist_path=path if persist else None)
        repo._ingest(raw)
        return repo

    def _ingest(self, records: list) -> None:
        """Load feed records, skipping bad ones instead of failing the whole feed."""
        report = self.ingest_report
        for index, record in enumerate(records):
            try:
                listing = listing_from_dict(record)
            except ValidationError as exc:
                report["skipped"] += 1
                ident = record.get("id") if isinstance(record, dict) else None
                report["errors"].append({"index": index, "id": ident, "details": exc.details or exc.message})
                log.warning("Skipping invalid listing at index %d (id=%s): %s", index, ident, exc.details)
                continue
            if listing.key in self._items:
                # Same feed re-sent the record: last one wins, like an upsert.
                report["duplicates"] += 1
                log.warning("Duplicate listing %s:%s at index %d; keeping latest", *listing.key, index)
            self._put(listing)
        report["loaded"] = len(self._items)

    # ---- index maintenance ---------------------------------------------------

    def _put(self, listing: Listing) -> None:
        old = self._items.get(listing.key)
        if old is not None:
            self._unindex(old)
        self._items[listing.key] = listing
        self._by_city[listing.city_lc].add(listing.key)
        self._by_state[listing.state].add(listing.key)
        self._by_zip[listing.zip].add(listing.key)

    def _unindex(self, listing: Listing) -> None:
        for index, value in (
            (self._by_city, listing.city_lc),
            (self._by_state, listing.state),
            (self._by_zip, listing.zip),
        ):
            bucket = index.get(value)
            if bucket is not None:
                bucket.discard(listing.key)
                if not bucket:
                    del index[value]

    # ---- queries -------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def get(self, source: str, listing_id: str) -> Listing:
        listing = self._items.get((source.strip().upper(), listing_id.strip()))
        if listing is None:
            raise NotFoundError(f"Listing {listing_id!r} from source {source!r} was not found.")
        return listing

    def candidates(
        self,
        cities: Iterable[str] = (),
        states: Iterable[str] = (),
        zips: Iterable[str] = (),
    ) -> list[Listing]:
        """Snapshot of listings matching ALL given location groups (OR within a group)."""
        with self._lock:
            keys: set[Key] | None = None
            for index, wanted in ((self._by_city, cities), (self._by_state, states), (self._by_zip, zips)):
                wanted = list(wanted)
                if not wanted:
                    continue
                group: set[Key] = set()
                for value in wanted:
                    group |= index.get(value, set())
                keys = group if keys is None else keys & group
                if not keys:
                    return []
            if keys is None:
                return list(self._items.values())
            return [self._items[k] for k in keys]

    def locations(self) -> dict:
        with self._lock:
            listings = list(self._items.values())
        cities: dict[tuple[str, str], int] = defaultdict(int)
        states: dict[str, int] = defaultdict(int)
        zips: dict[tuple[str, str, str], int] = defaultdict(int)
        for item in listings:
            cities[(item.city, item.state)] += 1
            states[item.state] += 1
            zips[(item.zip, item.city, item.state)] += 1
        return {
            "states": [{"state": s, "count": n} for s, n in sorted(states.items())],
            "cities": [{"city": c, "state": s, "count": n} for (c, s), n in sorted(cities.items())],
            "zips": [{"zip": z, "city": c, "state": s, "count": n} for (z, c, s), n in sorted(zips.items())],
        }

    # ---- mutations -----------------------------------------------------------

    def create(self, listing: Listing) -> Listing:
        with self._lock:
            if listing.key in self._items:
                raise ConflictError(
                    f"Listing {listing.id!r} from source {listing.source!r} already exists. "
                    "Use PUT or PATCH to modify it."
                )
            self._put(listing)
            self._persist()
        return listing

    def replace(self, listing: Listing) -> Listing:
        with self._lock:
            if listing.key not in self._items:
                raise NotFoundError(f"Listing {listing.id!r} from source {listing.source!r} was not found.")
            self._put(listing)
            self._persist()
        return listing

    def delete(self, source: str, listing_id: str) -> None:
        with self._lock:
            listing = self.get(source, listing_id)
            self._unindex(listing)
            del self._items[listing.key]
            self._persist()

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        data = [item.to_dict() for item in sorted(self._items.values(), key=lambda x: x.key)]
        directory = self._persist_path.parent
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".listings-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
                fh.write("\n")
            os.replace(tmp, self._persist_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
