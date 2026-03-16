"""Интеграция с FastAPI."""

from .fastapi_endpoint import app, printer, PrintRequest, PrintResponse, StatusResponse

__all__ = [
    "app",
    "printer",
    "PrintRequest",
    "PrintResponse",
    "StatusResponse",
]
