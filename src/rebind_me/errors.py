"""Error codes shared by the store, engine and API.

Codes are part of the public contract and must never change once published.
"""

from __future__ import annotations

ERROR_STATUS: dict[str, int] = {
    # 400
    "SCHEMA_ERROR": 400,
    "UNKNOWN_BUTTON": 400,
    "INVALID_KEY_CODE": 400,
    "INVALID_MODE": 400,
    "INVALID_TRIGGER_MODE": 400,
    "MAPPING_LIMIT": 400,
    "PRESET_LIMIT": 400,
    # 401
    "INVALID_TOKEN": 401,
    "MISSING_TOKEN": 401,
    # 403
    "ORIGIN_NOT_ALLOWED": 403,
    # 404
    "NOT_FOUND": 404,
    "UNKNOWN_PRESET": 404,
    # 405
    "METHOD_NOT_ALLOWED": 405,
    # 408
    "CAPTURE_TIMEOUT": 408,
    # 409
    "STALE_STORE": 409,
    "CAPTURE_IN_PROGRESS": 409,
    # 422
    "INJECTION_FAILED": 422,
    # 500
    "INTERNAL_ERROR": 500,
    # 503
    "DEVICE_NOT_CONNECTED": 503,
    "DEVICE_IO_ERROR": 503,
}


class RebindError(Exception):
    """An error that maps to the API error envelope."""

    def __init__(self, code: str, message: str = "", status: int | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status = status if status is not None else ERROR_STATUS.get(code, 500)


def to_int(value: object, message: str) -> int:
    """Coerce ``value`` to ``int``, raising ``SCHEMA_ERROR`` on garbage.

    Validators must never leak a native ``ValueError`` / ``TypeError``: those
    bypass the API error envelope and surface as 500 instead of 400.
    """
    try:
        return int(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        raise RebindError("SCHEMA_ERROR", message)


def to_float(value: object, message: str) -> float:
    """Coerce ``value`` to ``float``; see :func:`to_int`."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        raise RebindError("SCHEMA_ERROR", message)


__all__ = ["ERROR_STATUS", "RebindError", "to_float", "to_int"]
