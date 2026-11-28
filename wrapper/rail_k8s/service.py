"""Startup state and the object upstream's /ask endpoint talks to.

Upstream's api builds its pipeline inside the lifespan, so the port stays closed while the model
loads. Here the port opens at once and a background thread does the loading, so /startupz can
say what the pod is waiting for. Until the pipeline is ready, /ask answers 503.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from fastapi import HTTPException

from rail_k8s.metrics import ASK_OUTCOMES, READY, STARTUP_SECONDS
from rail_k8s.store import BackendUnavailable

log = logging.getLogger("rail_k8s.service")


class _NoTracer:
    enabled = False

    def flush(self) -> None:
        pass


class Service:
    """Stands in for upstream's Pipeline in ``app.state.pipeline``."""

    def __init__(
        self,
        build: Callable[[], object],
        expected_passages: Callable[[], int],
        poll_seconds: float = 2.0,
    ):
        self._build, self._expected, self._poll = build, expected_passages, poll_seconds
        self.pipeline = None
        self.phase = "starting"  # starting, loading-model, waiting-for-index, ready, failed
        self.detail = ""
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._load, name="startup", daemon=True)

    def start(self) -> None:
        self._t0 = time.monotonic()
        self._thread.start()

    def _set(self, phase: str, detail: str = "") -> None:
        self.phase, self.detail = phase, detail
        log.info("startup phase", extra={"phase": phase, "detail": detail})

    def _load(self) -> None:
        try:
            self._set("loading-model")
            expected = self._expected()
            pipeline = self._build()
            self._set("waiting-for-index", f"want {expected} passages")
            last = None
            while True:
                try:
                    n = pipeline.store.count()
                    detail = f"qdrant has {n} of {expected} passages"
                except Exception as exc:  # collection missing, Qdrant not up yet
                    n, detail = -1, f"qdrant not ready: {type(exc).__name__}"
                if n == expected:
                    break
                if detail != last:
                    self._set("waiting-for-index", detail)
                    last = detail
                time.sleep(self._poll)
            self.pipeline = pipeline
            seconds = time.monotonic() - self._t0
            STARTUP_SECONDS.set(seconds)
            READY.set(1)
            self._set("ready", f"{n} passages, {seconds:.1f} s")
        except Exception as exc:
            log.exception("startup failed")
            self._set("failed", f"{type(exc).__name__}: {exc}")

    @property
    def ready(self) -> bool:
        return self.phase == "ready"

    # --- what upstream's endpoints call -------------------------------------------------------
    @property
    def tracer(self):
        return self.pipeline.tracer if self.pipeline else _NoTracer()

    def ask(self, question: str):
        if not self.ready:
            raise HTTPException(503, "The service is starting; try again shortly.")
        try:
            result = self.pipeline.ask(question)
        except BackendUnavailable as exc:
            raise HTTPException(503, "The document store is unavailable; try again shortly.") from exc
        ASK_OUTCOMES.labels(result.refusal_reason or "other" if result.refused else "answered").inc()
        return result

    def health(self) -> dict:
        return {"phase": self.phase, **(self.pipeline.health() if self.ready else {})}
