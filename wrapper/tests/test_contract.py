"""Fails if upstream changes something the wrapper depends on. Run after bumping the commit pin."""

import inspect

from rail_rag import api, graph, integrity, pipeline, tracing, vectorstore


def params(fn):
    return list(inspect.signature(fn).parameters)


def test_pipeline_constructor():
    assert params(pipeline.Pipeline.__init__) == [
        "self", "llm", "embedder", "store", "cfg", "store_name", "tracer"
    ]


def test_pipeline_methods_the_api_calls():
    for name in ("ask", "health"):
        assert callable(getattr(pipeline.Pipeline, name))
    assert params(pipeline.Pipeline.ask)[:2] == ["self", "question"]


def test_create_app_accepts_a_pipeline_and_limiter():
    assert params(api.create_app) == ["pipeline", "limiter"]


def test_qdrant_store_parts_the_remote_store_replaces():
    store = vectorstore.QdrantStore(":memory:")
    assert {"collection", "_sparse", "client"} <= set(vars(store))
    for name in ("reset", "upsert", "search", "count"):
        assert callable(getattr(store, name))


def test_graph_and_tracing_pieces():
    assert {"k", "min_score", "hybrid"} <= set(graph.GraphConfig.__dataclass_fields__)
    assert callable(tracing.make_tracer)
    assert params(integrity.PinnedStore.__init__) == ["self", "store", "pins"]
    assert callable(integrity.load_pins)
