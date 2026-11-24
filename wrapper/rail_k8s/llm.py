"""Generators for the cluster: a deterministic fake, and a deadline around a real provider."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from rail_k8s.metrics import GENERATOR_CALLS, GENERATOR_DURATION

_PASSAGE_NUMBER = re.compile(r"^\[(\d+)\] ", re.MULTILINE)


class FakeLLM:
    """Answers like the real generator's three calls, without a model.

    Each call sleeps a delay between min and max milliseconds. The delay comes from a hash of
    (seed, prompt, text), so the same question always costs the same time, whichever pod or
    thread serves it, and a run can be repeated. rewrite, grade and generate are told apart by
    the schema argument, the same way upstream's graph calls them.
    """

    name = "fake:deterministic"

    def __init__(
        self,
        min_ms: int = 300,
        max_ms: int = 900,
        seed: int = 0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not 0 <= min_ms <= max_ms:
            raise ValueError(f"need 0 <= min_ms <= max_ms, got {min_ms}, {max_ms}")
        self.min_ms, self.max_ms, self.seed, self._sleep = min_ms, max_ms, seed, sleep

    def delay_seconds(self, system: str, user: str) -> float:
        digest = hashlib.sha256(f"{self.seed}\x00{system}\x00{user}".encode()).digest()
        fraction = int.from_bytes(digest[:8], "big") / 2**64
        return (self.min_ms + (self.max_ms - self.min_ms) * fraction) / 1000

    def complete(self, system: str, user: str, *, schema: dict | None = None) -> str:
        self._sleep(self.delay_seconds(system, user))
        if schema is None:  # rewrite: keep the question as the search query
            return user
        numbers = [int(n) for n in _PASSAGE_NUMBER.findall(user)]
        if "relevant" in schema.get("properties", {}):  # grade: the first three passages
            return '{"relevant": %s}' % numbers[:3]
        # generate: one cited sentence, so upstream's citation gate accepts it
        return '{"answer": "This is a fake answer used for load testing [1].", "insufficient": false}'


class DeadlineLLM:
    """Gives each call to a real provider a deadline; upstream's retries can run for minutes.

    A call that misses the deadline raises LLMUnavailable, which the api turns into a 503. Python
    cannot kill a thread, so the abandoned call finishes in the background; the pool is bounded
    so a stuck provider cannot pile up threads.
    """

    def __init__(self, inner, timeout_seconds: float, max_workers: int = 32):
        self.inner, self.timeout = inner, timeout_seconds
        self.name = inner.name
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="llm")

    def complete(self, system: str, user: str, *, schema: dict | None = None) -> str:
        from rail_rag.providers import LLMUnavailable

        future = self._pool.submit(self.inner.complete, system, user, schema=schema)
        try:
            return future.result(timeout=self.timeout)
        except FutureTimeout as exc:
            raise LLMUnavailable(f"no reply within {self.timeout:g} s") from exc


class InstrumentedLLM:
    """Counts and times every generator call, whichever generator is behind it."""

    def __init__(self, inner):
        self.inner, self.name = inner, inner.name

    def complete(self, system: str, user: str, *, schema: dict | None = None) -> str:
        start = time.perf_counter()
        try:
            out = self.inner.complete(system, user, schema=schema)
        except Exception:
            GENERATOR_CALLS.labels("error").inc()
            raise
        finally:
            GENERATOR_DURATION.observe(time.perf_counter() - start)
        GENERATOR_CALLS.labels("ok").inc()
        return out
