"""Upstream's query embedder with a fixed number of ONNX Runtime threads.

ONNX Runtime starts one thread per core it can see, and a container sees every core of the node
(8 here), whatever its CPU limit. Inside a 1-CPU limit those threads are throttled, which adds
latency, and without a limit one pod takes the whole node (docs/DESIGN.md D17). Upstream's
LocalEmbedder does not expose the setting, so this repeats its four-line constructor with
``threads``; tests/test_contract.py checks the attributes it sets.
"""

from __future__ import annotations

from rail_rag.embeddings import BGE_QUERY_PREFIX, CACHE_DIR, LocalEmbedder


class ThreadedEmbedder(LocalEmbedder):
    def __init__(self, model_name: str, threads: int, batch_size: int = 32):
        from fastembed import TextEmbedding

        self.model = TextEmbedding(model_name, cache_dir=str(CACHE_DIR), threads=threads)
        self.batch_size = batch_size
        self.dim = len(self._encode(["probe"])[0])
        self.query_prefix = BGE_QUERY_PREFIX if "bge" in model_name.lower() else ""
        self.threads = threads
