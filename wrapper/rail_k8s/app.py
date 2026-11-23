"""The ASGI app: upstream's api, plus probes, /metrics, request IDs and per-request logs.

Run: uvicorn rail_k8s.app:app
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from rail_rag.api import create_app
from rail_rag.chunking import load_passages

from rail_k8s.build import build_pipeline
from rail_k8s.config import WrapperSettings
from rail_k8s.logs import configure_logging, request_id_var
from rail_k8s.metrics import HTTP_DURATION, HTTP_REQUESTS, IN_FLIGHT
from rail_k8s.service import Service

log = logging.getLogger("rail_k8s.http")

# Not counted as load: probes and scrapes must not move the autoscaler or fill the logs.
QUIET_PATHS = {"/livez", "/readyz", "/startupz", "/metrics"}
_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


class ObservabilityMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware): no extra task per request, and the in-flight gauge
    stays exact. Sets the request ID, counts in-flight requests, times and logs each request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        incoming = _SAFE_ID.sub("", headers.get(b"x-request-id", b"").decode("latin-1"))[:64]
        rid = incoming or uuid.uuid4().hex
        token = request_id_var.set(rid)
        quiet = scope["path"] in QUIET_PATHS
        status = 500
        if not quiet:
            IN_FLIGHT.inc()
        start = time.perf_counter()

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": [*message.get("headers", []),
                                                  (b"x-request-id", rid.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            elapsed = time.perf_counter() - start
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            if not quiet:
                IN_FLIGHT.dec()
                HTTP_REQUESTS.labels(scope["method"], route, str(status)).inc()
                HTTP_DURATION.labels(route).observe(elapsed)
            log.log(
                logging.DEBUG if quiet else logging.INFO,
                "request",
                extra={"method": scope["method"], "path": scope["path"], "route": route,
                       "status": status, "duration_ms": round(elapsed * 1000, 1)},
            )
            request_id_var.reset(token)


def make_app(service: Service | None = None) -> FastAPI:
    w = WrapperSettings.from_env()
    configure_logging(w.log_level, w.log_format)
    service = service or Service(
        build=lambda: build_pipeline(w),
        expected_passages=lambda: len(load_passages()),
        poll_seconds=w.index_poll_seconds,
    )
    app = create_app(pipeline=service)  # type: ignore[arg-type]  # Service quacks like Pipeline
    app.state.service = service

    upstream_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(a):
        service.start()
        async with upstream_lifespan(a):
            yield

    app.router.lifespan_context = lifespan

    def probe(ok: bool) -> Response:
        body = f'{{"phase": "{service.phase}", "detail": {_json(service.detail)}}}'
        return Response(body, status_code=200 if ok else 503, media_type="application/json")

    @app.get("/livez", include_in_schema=False)
    def livez() -> Response:
        return Response('{"status": "alive"}', media_type="application/json")

    @app.get("/startupz", include_in_schema=False)
    def startupz() -> Response:
        return probe(service.ready)

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> Response:
        # Local state only. Qdrant is shared by every pod, so checking it here would take all
        # pods out of the Service at once (docs/DESIGN.md D5).
        return probe(service.ready)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.add_middleware(ObservabilityMiddleware)
    return app


def _json(text: str) -> str:
    import json

    return json.dumps(text)


app = make_app()
