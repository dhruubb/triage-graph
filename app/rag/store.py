"""Qdrant-backed runbook store with hybrid retrieval.

retrieve() runs dense and sparse searches in one Qdrant query, fuses them with
Reciprocal Rank Fusion, adds a small bonus for chunks tagged with the ticket's
service, groups chunks by runbook, and then pulls the full runbook (every section)
for the top matches so the planner sees remediation and rollback steps together.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.rag.chunking import Chunk
from app.rag.embeddings import DenseEmbedder, SparseBM25

SERVICE_BONUS = 0.15
NAMESPACE = uuid.UUID("5b7c2f3e-9a41-4c8e-8f0e-6f5c1d2a7b90")


@dataclass
class Retrieval:
    runbooks: list[dict]  # [{runbook_id, title, score, matched_sections, services}]
    chunks: list[dict]    # full sections of the top runbooks
    query: str


class RunbookStore:
    def __init__(self, client: QdrantClient, collection: str, dense: DenseEmbedder, sparse: SparseBM25, url: str = ""):
        self.client = client
        self.url = url
        self.collection = f"{collection}_{dense.tag}"
        self.dense = dense
        self.sparse = sparse

    @classmethod
    def connect(cls, url: str, api_key: str, collection: str, dense: DenseEmbedder,
                sparse: SparseBM25 | None = None) -> RunbookStore:
        client = QdrantClient(url=url, api_key=api_key or None, timeout=30) if url else QdrantClient(":memory:")
        return cls(client, collection, dense, sparse or SparseBM25(), url)

    @property
    def backend(self) -> str:
        if not self.url:
            return "qdrant-embedded"
        return "qdrant-cloud" if "cloud.qdrant.io" in self.url else "qdrant-server"

    def ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            self.collection,
            vectors_config={"dense": models.VectorParams(size=self.dense.dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        if self.url:  # payload indexes matter on a server (Qdrant Cloud strict mode can require them)
            for field in ("services", "runbook_id"):
                self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)

    def ingest(self, chunks: list[Chunk]) -> int:
        """Idempotent: point ids are derived from chunk ids, so re-running overwrites."""
        self.ensure_collection()
        texts = [c.text for c in chunks]
        self.sparse.fit(texts)
        dense_vecs = self.dense.embed(texts)
        points = []
        for c, dv in zip(chunks, dense_vecs):
            idx, vals = self.sparse.encode_document(c.text)
            points.append(models.PointStruct(
                id=str(uuid.uuid5(NAMESPACE, c.id)),
                vector={"dense": dv, "sparse": models.SparseVector(indices=idx, values=vals)},
                payload=c.payload(),
            ))
        self.client.upsert(self.collection, points=points, wait=True)
        return len(points)

    def count(self) -> int:
        try:
            return self.client.count(self.collection, exact=True).count
        except Exception:
            return 0

    def search(self, query: str, limit: int = 12) -> list[dict]:
        dv = self.dense.embed([query])[0]
        idx, vals = self.sparse.encode_query(query)
        prefetch = [models.Prefetch(query=dv, using="dense", limit=limit)]
        if idx:
            prefetch.append(models.Prefetch(query=models.SparseVector(indices=idx, values=vals),
                                            using="sparse", limit=limit))
        res = self.client.query_points(self.collection, prefetch=prefetch,
                                       query=models.FusionQuery(fusion=models.Fusion.RRF),
                                       limit=limit, with_payload=True)
        return [{**p.payload, "score": float(p.score)} for p in res.points]

    def retrieve(self, query: str, service: str | None = None, k: int = 3) -> Retrieval:
        hits = self.search(query)
        for h in hits:
            if service and service in h.get("services", []):
                h["score"] += SERVICE_BONUS
        by_runbook: dict[str, dict] = {}
        for h in sorted(hits, key=lambda x: x["score"], reverse=True):
            rb = by_runbook.setdefault(h["runbook_id"], {
                "runbook_id": h["runbook_id"], "title": h["title"], "services": h["services"],
                "score": h["score"], "matched_sections": [],
            })
            rb["matched_sections"].append(h["section"])
        ranked = sorted(by_runbook.values(), key=lambda r: r["score"], reverse=True)[:k]
        for r in ranked:
            r["score"] = round(min(r["score"], 1.0), 3)
        chunks = self.fetch_runbooks([r["runbook_id"] for r in ranked])
        return Retrieval(runbooks=ranked, chunks=chunks, query=query)

    def fetch_runbooks(self, runbook_ids: list[str]) -> list[dict]:
        if not runbook_ids:
            return []
        points, _ = self.client.scroll(
            self.collection,
            scroll_filter=models.Filter(must=[models.FieldCondition(key="runbook_id", match=models.MatchAny(any=runbook_ids))]),
            limit=100, with_payload=True,
        )
        order = {rb: i for i, rb in enumerate(runbook_ids)}
        section_order = {"symptoms": 0, "diagnosis": 1, "remediation": 2, "rollback": 3, "escalation": 4}
        chunks = [dict(p.payload) for p in points]
        chunks.sort(key=lambda c: (order.get(c["runbook_id"], 99), section_order.get(c["section"].lower(), 9)))
        return chunks
