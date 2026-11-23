from rail_k8s import index_job
from tests.conftest import MemoryStore


def test_builds_then_skips(monkeypatch, embedder, passages):
    monkeypatch.setattr(index_job, "load_passages", lambda: passages)
    store = MemoryStore()
    assert index_job.run(store, lambda: embedder) == "built"
    assert store.count() == len(passages)
    assert index_job.run(store, lambda: embedder) == "skipped"


def test_rebuilds_when_the_count_is_wrong(monkeypatch, embedder, passages):
    monkeypatch.setattr(index_job, "load_passages", lambda: passages)
    store = MemoryStore()
    store.reset(embedder.dim)
    store.upsert(passages[:5], embedder.embed_documents([p.embed_text for p in passages[:5]]))
    assert index_job.run(store, lambda: embedder) == "built"
    assert store.count() == len(passages)
