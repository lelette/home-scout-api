"""Configuration, overridable through environment variables."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # auto generated JSON file used as the mock database.
    DATA_FILE = os.environ.get("LISTINGS_DATA_FILE", str(PROJECT_ROOT / "data" / "listings.json"))
    # Write CRUD changes back to DATA_FILE. Off by default so the sample data stays pristine.
    PERSIST_CHANGES = _bool("LISTINGS_PERSIST", False)
    DEFAULT_PAGE_SIZE = int(os.environ.get("DEFAULT_PAGE_SIZE", "20"))
    MAX_PAGE_SIZE = int(os.environ.get("MAX_PAGE_SIZE", "100"))
    # Comma-separated list of allowed browser origins for the frontend, or "*".
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
    # Fixed "today" for recency scoring (YYYY-MM-DD). Empty = real UTC date.
    REFERENCE_DATE = os.environ.get("REFERENCE_DATE") or None
    JSON_SORT_KEYS = False
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024  # 1 MiB request bodies
