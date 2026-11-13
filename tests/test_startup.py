from __future__ import annotations

from app.config import ROOT, Settings
from app.deps import connect_and_ingest
from app.rag.chunking import load_runbooks


def test_unreachable_qdrant_falls_back_to_in_memory(tmp_path):
    # Port 1 on localhost refuses connections immediately, like a suspended or wrong Qdrant URL.
    settings = Settings(_env_file=None, embeddings="hash", qdrant_url="http://127.0.0.1:1", runtime_dir=tmp_path)
    chunks = load_runbooks(ROOT / "data" / "runbooks")

    store, n = connect_and_ingest(settings, chunks, attempts=1)

    assert store.backend == "qdrant-embedded"
    assert store.fallback_reason
    assert n == len(chunks) and store.count() == n
