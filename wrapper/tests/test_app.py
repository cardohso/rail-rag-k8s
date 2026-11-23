import threading
import time

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from rail_k8s.app import make_app
from rail_k8s.build import build_pipeline
from rail_k8s.config import WrapperSettings
from rail_k8s.service import Service
from rail_k8s.store import TimedStore

FAST = WrapperSettings(generator_provider="fake", fake_latency_min_ms=0, fake_latency_max_ms=0)


def sample(name, **labels):
    return REGISTRY.get_sample_value(name, labels) or 0.0


def wait_until(fn, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def make_service(store, embedder, n, gate=None, poll=0.05):
    def build():
        if gate:
            gate.wait()
        return build_pipeline(FAST, store=store, embedder=embedder)

    return Service(build, lambda: n, poll_seconds=poll)


def test_probes_follow_startup_and_ask_waits(loaded_store, embedder, passages):
    gate = threading.Event()
    with TestClient(make_app(make_service(loaded_store, embedder, len(passages), gate))) as c:
        assert c.get("/livez").status_code == 200  # alive while still loading
        r = c.get("/startupz")
        assert r.status_code == 503 and r.json()["phase"] == "loading-model"
        assert c.get("/readyz").status_code == 503
        assert c.post("/ask", json={"question": "anything at all"}).status_code == 503
        gate.set()
        assert wait_until(lambda: c.get("/startupz").status_code == 200)
        assert c.get("/readyz").status_code == 200


def test_startup_waits_for_the_index(embedder, passages):
    from tests.conftest import MemoryStore

    empty = MemoryStore()  # no collection yet, like Qdrant before the index Job finishes
    with TestClient(make_app(make_service(empty, embedder, len(passages)))) as c:
        assert wait_until(lambda: c.get("/startupz").json()["phase"] == "waiting-for-index")
        assert c.get("/readyz").status_code == 503
        empty.reset(embedder.dim)
        empty.upsert(passages, embedder.embed_documents([p.embed_text for p in passages]))
        assert wait_until(lambda: c.get("/readyz").status_code == 200)


@pytest.fixture
def ready_client(loaded_store, embedder, passages):
    with TestClient(make_app(make_service(loaded_store, embedder, len(passages)))) as c:
        assert wait_until(lambda: c.get("/readyz").status_code == 200)
        yield c


def test_ask_returns_a_cited_answer_with_request_id(ready_client, passages):
    p = passages[0]
    question = f"{p.heading}. {p.text[:200]}"
    before = sample("rail_http_requests_total", method="POST", route="/ask", status="200")
    r = ready_client.post("/ask", json={"question": question}, headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is False and body["citations"]
    assert r.headers["x-request-id"] == "abc-123"
    assert sample("rail_http_requests_total", method="POST", route="/ask", status="200") == before + 1
    assert sample("rail_http_requests_in_flight") == 0
    assert sample("rail_generator_calls_total", outcome="ok") >= 3  # rewrite, grade, generate


def test_request_id_is_generated_and_sanitised(ready_client):
    assert len(ready_client.get("/health").headers["x-request-id"]) == 32
    r = ready_client.get("/health", headers={"X-Request-ID": "a b<script>"})
    assert r.headers["x-request-id"] == "abscript"


def test_probes_are_not_counted_as_load(ready_client):
    before = sum(s.value for m in REGISTRY.collect() if m.name == "rail_http_requests"
                 for s in m.samples if s.name == "rail_http_requests_total")
    for path in ("/livez", "/readyz", "/startupz", "/metrics"):
        ready_client.get(path)
    after = sum(s.value for m in REGISTRY.collect() if m.name == "rail_http_requests"
                for s in m.samples if s.name == "rail_http_requests_total")
    assert after == before


def test_unknown_paths_do_not_create_label_values(ready_client):
    ready_client.get("/no/such/thing/1234")
    assert sample("rail_http_requests_total", method="GET", route="unmatched", status="404") >= 1
    assert "/no/such/thing" not in ready_client.get("/metrics").text


def test_qdrant_failure_is_a_fast_503_and_counted(ready_client, passages):
    store = ready_client.app.state.service.pipeline.store.store  # PinnedStore -> TimedStore
    assert isinstance(store, TimedStore)

    def boom(*a, **k):
        raise ConnectionError("down")

    store.store.search = boom
    before = sample("rail_backend_errors_total", backend="qdrant")
    r = ready_client.post("/ask", json={"question": passages[0].text[:200]})
    assert r.status_code == 503
    assert sample("rail_backend_errors_total", backend="qdrant") == before + 1
    assert ready_client.get("/readyz").status_code == 200  # readiness ignores Qdrant (D5)
