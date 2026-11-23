import pytest
from rail_rag.chunking import load_passages
from rail_rag.embeddings import LocalEmbedder
from rail_rag.vectorstore import QdrantStore

from rail_k8s.store import RemoteQdrantStore


@pytest.fixture(scope="session")
def embedder():
    return LocalEmbedder()  # the model baked into the image


@pytest.fixture(scope="session")
def passages():
    return load_passages()[:30]


class MemoryStore(RemoteQdrantStore):
    """A RemoteQdrantStore whose client is in-process, so tests need no server."""

    def __init__(self):
        QdrantStore.__init__(self, ":memory:")


@pytest.fixture
def loaded_store(embedder, passages):
    store = MemoryStore()
    store.reset(embedder.dim)
    store.upsert(passages, embedder.embed_documents([p.embed_text for p in passages]))
    return store
