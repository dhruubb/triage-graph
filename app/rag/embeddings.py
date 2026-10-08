"""Dense and sparse encoders for hybrid search.

Dense:  BAAI/bge-small-en-v1.5 through FastEmbed (ONNX, runs on CPU, no API key).
        HashDense is a dependency-free stand-in used in tests and offline CI.
Sparse: a BM25-style term-frequency encoder. Qdrant applies IDF on the server
        (Modifier.IDF), so exact terms like "OOMKilled" or "EAI_AGAIN" still match
        when the dense model misses them.
"""

from __future__ import annotations

import math
import os
import re
import zlib
from collections import Counter
from typing import Protocol

TOKEN_RE = re.compile(r"[a-z0-9_]+")
STOPWORDS = set(
    "a an and are as at be by for from has have if in into is it its of on or the this to was were "
    "with when while which who will not no than then that there these they we our you your i".split()
)


def tokenize(text: str) -> list[str]:
    tokens = []
    for t in TOKEN_RE.findall(text.lower()):
        if len(t) < 2 or t in STOPWORDS:
            continue
        if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]  # light stemming: "pods" -> "pod"
        tokens.append(t)
    return tokens


class DenseEmbedder(Protocol):
    tag: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedDense:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name, cache_dir=os.getenv("FASTEMBED_CACHE_PATH"))
        self.tag = slug_model(model_name)
        self.dim = len(next(iter(self._model.embed(["dimension probe"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts)]


class HashDense:
    """Feature-hashing embedder: deterministic, no downloads. For tests and CI only."""

    tag = "hash384"
    dim = 384

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self.dim
            toks = tokenize(text)
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for g in grams:
                h = zlib.crc32(g.encode())
                vec[h % self.dim] += 1.0 if (h >> 16) & 1 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SparseBM25:
    """BM25 term weights (TF saturation + length normalisation). IDF is applied by Qdrant."""

    def __init__(self, k1: float = 1.2, b: float = 0.75, avg_len: float = 60.0):
        self.k1, self.b, self.avg_len = k1, b, avg_len

    @staticmethod
    def _index(token: str) -> int:
        return zlib.crc32(token.encode()) & 0x7FFFFFFF

    def fit(self, texts: list[str]) -> SparseBM25:
        lengths = [len(tokenize(t)) for t in texts] or [60]
        self.avg_len = sum(lengths) / len(lengths)
        return self

    def encode_document(self, text: str) -> tuple[list[int], list[float]]:
        toks = tokenize(text)
        tf = Counter(toks)
        dl = len(toks) or 1
        weights: dict[int, float] = {}
        for tok, f in tf.items():
            w = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg_len))
            idx = self._index(tok)
            weights[idx] = weights.get(idx, 0.0) + w
        return list(weights.keys()), list(weights.values())

    def encode_query(self, text: str) -> tuple[list[int], list[float]]:
        idxs = sorted({self._index(t) for t in tokenize(text)})
        return idxs, [1.0] * len(idxs)


def slug_model(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.split("/")[-1].lower()).strip("-")


def build_dense(kind: str, model_name: str) -> DenseEmbedder:
    if kind == "hash":
        return HashDense()
    return FastEmbedDense(model_name)
