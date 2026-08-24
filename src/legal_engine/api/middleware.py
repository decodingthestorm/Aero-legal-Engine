"""Correlation ID propagation and domain-exception -> HTTP error mapping.

Every LegalEngineError subclass (NotEPRFragmentError, ParseError,
UnbalancedCycleError, RobotsDisallowedError, WALIntegrityError, ...) maps to
a 400 here. That's intentionally coarse — a production gateway would likely
want per-exception status codes (e.g. RobotsDisallowedError as 403), but
that's a product decision about what each failure mode should mean to API
consumers, not something to guess at while the only consumer is this
codebase's own test suite.
"""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from legal_engine.core.exceptions import LegalEngineError
from legal_engine.core.logging import get_logger

logger = get_logger(__name__)


def add_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response

    @app.exception_handler(LegalEngineError)
    async def legal_engine_error_handler(request: Request, exc: LegalEngineError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.warning("legal_engine_error", error=str(exc), correlation_id=correlation_id)
        return JSONResponse(
            status_code=400,
            content={
                "error": exc.__class__.__name__,
                "detail": str(exc),
                "correlation_id": correlation_id,
            },
        )
