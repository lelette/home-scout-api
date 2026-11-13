"""Consistent JSON error envelope for every failure the API can return.

    {"error": {"status": 400, "code": "validation_error",
               "message": "...", "details": [{"field": "price", "message": "..."}]}}
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class APIError(Exception):
    status = 500
    code = "internal_error"

    def __init__(self, message: str, details: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class ValidationError(APIError):
    status = 400
    code = "validation_error"


class NotFoundError(APIError):
    status = 404
    code = "not_found"


class ConflictError(APIError):
    status = 409
    code = "conflict"


class UnsupportedMediaTypeError(APIError):
    status = 415
    code = "unsupported_media_type"


def _response(status: int, code: str, message: str, details: list[dict] | None = None):
    body = {"error": {"status": status, "code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return _response(err.status, err.code, err.message, err.details)

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        code = (err.name or "error").lower().replace(" ", "_")
        response = _response(err.code or 500, code, err.description or err.name)
        if err.code == 405 and err.valid_methods:
            response[0].headers["Allow"] = ", ".join(sorted(err.valid_methods))
        return response

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        log.exception("Unhandled error")
        return _response(500, "internal_error", "An unexpected error occurred.")
