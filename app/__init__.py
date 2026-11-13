"""MLS listing search API — application factory."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from flask import Flask, Response, redirect, request

from .config import Config
from .docs import docs
from .errors import register_error_handlers
from .repository import ListingRepository
from .routes import api

__version__ = "1.0.0"


def create_app(overrides: Mapping[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.json.sort_keys = app.config["JSON_SORT_KEYS"]

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    repo = app.config.get("LISTINGS_REPOSITORY") or ListingRepository.from_json_file(
        app.config["DATA_FILE"], persist=app.config["PERSIST_CHANGES"]
    )
    app.extensions["listings_repo"] = repo
    app.logger.info("Loaded %d listings (%d skipped)", len(repo), repo.ingest_report["skipped"])

    app.register_blueprint(api)
    app.register_blueprint(docs)
    register_error_handlers(app)
    _install_cors(app)

    @app.get("/")
    def index():
        return redirect("/docs")

    return app


def _install_cors(app: Flask) -> None:
    """Minimal CORS so a browser frontend on another origin can call the API."""
    allowed = {o.strip() for o in app.config["CORS_ORIGINS"].split(",") if o.strip()}

    @app.after_request
    def add_cors_headers(response: Response) -> Response:
        origin = request.headers.get("Origin")
        if "*" in allowed:
            response.headers["Access-Control-Allow-Origin"] = "*"
        elif origin and origin in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers.add("Vary", "Origin")
        else:
            return response
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Expose-Headers"] = "Location"
        return response
