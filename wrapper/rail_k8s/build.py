"""Builds upstream's Pipeline from the wrapper's pieces.

This mirrors ``Pipeline.from_settings`` (upstream, 8 lines) because that method hard-wires the
local store and the real providers. tests/test_contract.py pins the parts it relies on.
"""

from __future__ import annotations

from rail_rag.config import get_settings
from rail_rag.embeddings import LocalEmbedder
from rail_rag.graph import GraphConfig
from rail_rag.integrity import PinnedStore, load_pins
from rail_rag.pipeline import Pipeline
from rail_rag.providers import make_llm
from rail_rag.tracing import make_tracer

from rail_k8s.config import WrapperSettings
from rail_k8s.llm import DeadlineLLM, FakeLLM, InstrumentedLLM
from rail_k8s.store import RemoteQdrantStore, TimedEmbedder, TimedStore


def make_generator(w: WrapperSettings, s):
    if w.generator_provider == "fake":
        return InstrumentedLLM(FakeLLM(w.fake_latency_min_ms, w.fake_latency_max_ms, w.fake_seed))
    real = make_llm(w.generator_provider, s.api_key(w.generator_provider), s.generator_model)
    return InstrumentedLLM(DeadlineLLM(real, w.generator_timeout_seconds))


def build_pipeline(w: WrapperSettings | None = None, store=None, embedder=None) -> Pipeline:
    w = w or WrapperSettings.from_env()
    s = get_settings()
    cfg = GraphConfig(k=s.top_k, min_score=s.min_score, hybrid=s.search_mode == "hybrid")
    embedder = embedder or LocalEmbedder(s.embedding_model)
    store = TimedStore(store or RemoteQdrantStore(w.qdrant_url))
    if s.corpus_pin:
        store = PinnedStore(store, load_pins())
    return Pipeline(
        make_generator(w, s),
        TimedEmbedder(embedder),
        store,
        cfg,
        store_name="qdrant-server",
        tracer=make_tracer(s),
    )
