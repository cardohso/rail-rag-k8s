"""Qdrant as a server, and timing around the pieces the pipeline calls."""

from __future__ import annotations

import time

from rail_rag.vectorstore import QdrantStore

from rail_k8s.metrics import BACKEND_ERRORS, EMBED_DURATION, RETRIEVAL_DURATION


class BackendUnavailable(RuntimeError):
    """Qdrant could not be reached or answered with an error."""


class RemoteQdrantStore(QdrantStore):
    """Upstream's QdrantStore, pointed at a Qdrant server instead of a local folder.

    Upstream only builds an in-process client. Every method uses ``self.client``, so replacing
    the client is the whole change; tests/test_contract.py fails if upstream renames those parts.
    """

    def __init__(
        self, url: str, collection: str = "rail-tsi", sparse_encoder=None, timeout: int = 5
    ):
        from qdrant_client import QdrantClient

        self.collection = collection
        self._sparse = sparse_encoder
        self.client = QdrantClient(url=url, timeout=timeout, prefer_grpc=False)


class TimedStore:
    """Times searches and turns any Qdrant failure into BackendUnavailable (a fast 503)."""

    def __init__(self, store):
        self.store = store

    def search(self, vector, k: int = 5, text: str | None = None):
        start = time.perf_counter()
        try:
            return self.store.search(vector, k=k, text=text)
        except Exception as exc:
            BACKEND_ERRORS.labels("qdrant").inc()
            raise BackendUnavailable(f"qdrant search failed: {type(exc).__name__}") from exc
        finally:
            RETRIEVAL_DURATION.observe(time.perf_counter() - start)

    def __getattr__(self, name):  # count, reset, upsert, ...
        return getattr(self.store, name)


class TimedEmbedder:
    def __init__(self, embedder):
        self.embedder = embedder
        self.dim = embedder.dim

    def embed_query(self, text: str):
        with EMBED_DURATION.time():
            return self.embedder.embed_query(text)

    def embed_documents(self, texts):
        return self.embedder.embed_documents(texts)
