"""Settings the wrapper owns, read from environment variables (set by the chart's ConfigMap).

Upstream's own Settings object ignores unknown variables, so the two never collide.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WrapperSettings:
    qdrant_url: str = "http://localhost:6333"
    generator_provider: str = "fake"  # "fake", or an upstream provider such as "gemini"
    generator_timeout_seconds: float = 20.0
    fake_latency_min_ms: int = 300
    fake_latency_max_ms: int = 900
    fake_seed: int = 0
    log_level: str = "INFO"
    log_format: str = "json"  # "json" or "text"
    index_poll_seconds: float = 2.0  # how often startup re-checks Qdrant while the index loads

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> WrapperSettings:
        e = os.environ if env is None else env
        d = cls()
        return cls(
            qdrant_url=e.get("QDRANT_URL", d.qdrant_url),
            generator_provider=e.get("GENERATOR_PROVIDER", d.generator_provider),
            generator_timeout_seconds=float(
                e.get("GENERATOR_TIMEOUT_SECONDS", d.generator_timeout_seconds)
            ),
            fake_latency_min_ms=int(e.get("FAKE_LATENCY_MIN_MS", d.fake_latency_min_ms)),
            fake_latency_max_ms=int(e.get("FAKE_LATENCY_MAX_MS", d.fake_latency_max_ms)),
            fake_seed=int(e.get("FAKE_SEED", d.fake_seed)),
            log_level=e.get("LOG_LEVEL", d.log_level).upper(),
            log_format=e.get("LOG_FORMAT", d.log_format).lower(),
            index_poll_seconds=float(e.get("INDEX_POLL_SECONDS", d.index_poll_seconds)),
        )
