"""Loads the passages into the Qdrant server. Run as a Kubernetes Job; safe to run twice.

If the collection already holds the expected number of passages the job does nothing, so a
Helm upgrade that re-creates the Job does not rebuild an index that is already right.
"""

from __future__ import annotations

import logging
import resource
import sys
import time

from rail_rag.chunking import load_passages
from rail_rag.config import get_settings
from rail_rag.embeddings import LocalEmbedder

from rail_k8s.config import WrapperSettings
from rail_k8s.logs import configure_logging
from rail_k8s.store import RemoteQdrantStore

log = logging.getLogger("rail_k8s.index_job")
WAIT_SECONDS = 120
# Measured on the 1,589-passage corpus (docs/DESIGN.md D15): batch 8 peaked at 565 MiB in 243 s,
# batch 32 (upstream's default) at 1,582 MiB in 1,054 s.
EMBED_BATCH_SIZE = 8


def wait_for_qdrant(store: RemoteQdrantStore, seconds: int = WAIT_SECONDS) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            store.client.get_collections()
            return
        except Exception as exc:
            if time.monotonic() > deadline:
                raise
            log.info("waiting for qdrant", extra={"error": type(exc).__name__})
            time.sleep(2)


def _default_embedder() -> LocalEmbedder:
    return LocalEmbedder(get_settings().embedding_model, batch_size=EMBED_BATCH_SIZE)


def run(store: RemoteQdrantStore, embedder_factory=None) -> str:
    passages = load_passages()
    wait_for_qdrant(store)
    try:
        have = store.count() if store.client.collection_exists(store.collection) else -1
    except Exception:
        have = -1
    if have == len(passages):
        log.info("index already complete", extra={"passages": have})
        return "skipped"
    t0 = time.perf_counter()
    embedder = (embedder_factory or _default_embedder)()
    vectors = embedder.embed_documents([p.embed_text for p in passages])
    t1 = time.perf_counter()
    store.reset(embedder.dim)
    store.upsert(passages, vectors)
    log.info(
        "index built",
        extra={"passages": store.count(), "embed_s": round(t1 - t0, 1),
               "upload_s": round(time.perf_counter() - t1, 1), "was": have,
               "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024},
    )
    return "built"


def main() -> int:
    w = WrapperSettings.from_env()
    configure_logging(w.log_level, w.log_format)
    run(RemoteQdrantStore(w.qdrant_url, timeout=30))
    return 0


if __name__ == "__main__":
    sys.exit(main())
