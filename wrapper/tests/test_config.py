from rail_k8s.config import WrapperSettings
from rail_k8s.store import RemoteQdrantStore


def test_defaults_and_env_override():
    assert WrapperSettings.from_env({}).qdrant_timeout_seconds == 2
    assert WrapperSettings.from_env({"QDRANT_TIMEOUT_SECONDS": "7"}).qdrant_timeout_seconds == 7


def test_remote_store_passes_the_timeout_to_the_client():
    store = RemoteQdrantStore("http://localhost:6333", timeout=3)
    assert store.client._client._timeout == 3


def test_embed_threads_default_and_override():
    assert WrapperSettings.from_env({}).embed_threads == 0
    assert WrapperSettings.from_env({"EMBED_THREADS": "1"}).embed_threads == 1
