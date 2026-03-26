from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Protocol

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding provider interface
# ---------------------------------------------------------------------------

class EmbeddingProvider(Protocol):
    """Interface for pluggable embedding backends."""
    @property
    def dim(self) -> int: ...
    def embed(self, text: str) -> list[float]: ...


# ---------------------------------------------------------------------------
# Provider 1: Local deterministic hash (demo/dev — 64-dim)
# ---------------------------------------------------------------------------

class LocalHashEmbeddingProvider:
    """Deterministic SHA-256 hash-based embedding for local-first / offline usage.

    LIMITATIONS (development only):
      - 64 dimensions vs. 384-1536 in production embeddings
      - No semantic understanding — purely lexical hashing
      - Retrieval recall/precision will be significantly lower than
        sentence-transformers or OpenAI embeddings

    Adequate for:  functional testing, CI, air-gapped demos.
    NOT suitable for:  production retrieval quality benchmarks.
    """

    def __init__(self, dim: int = 64) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        return text_to_embedding(text, dim=self._dim)


# ---------------------------------------------------------------------------
# Provider 2: Sentence-Transformers (production — 384-dim)
# ---------------------------------------------------------------------------

class SentenceTransformerEmbeddingProvider:
    """Production-grade embeddings via sentence-transformers.

    Models:
      - all-MiniLM-L6-v2  (384-dim, 80MB, fast)     — default
      - all-mpnet-base-v2  (768-dim, 420MB, accurate)
      - e5-large-v2        (1024-dim, best quality)

    Requires:  pip install sentence-transformers
    """

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2') -> None:
        self._model_name = model_name
        self._model = None
        self._dim = 384  # will be set after model loads

    @property
    def dim(self) -> int:
        return self._dim

    def _load(self):
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
            self._dim = self._model.get_sentence_embedding_dimension()
            logger.info(
                'SentenceTransformer loaded.',
                extra={'model': self._model_name, 'dim': self._dim},
            )
        except ImportError:
            raise RuntimeError(
                'sentence-transformers not installed. '
                'Run: pip install sentence-transformers'
            )

    def embed(self, text: str) -> list[float]:
        self._load()
        embedding = self._model.encode(text, normalize_embeddings=True)
        return embedding.tolist()


# ---------------------------------------------------------------------------
# Provider 3: OpenAI-compatible API (production — 1536/3072-dim)
# ---------------------------------------------------------------------------

class ApiEmbeddingProvider:
    """Embeddings via OpenAI-compatible HTTP API.

    Supports OpenAI, Azure OpenAI, Cohere, or any compatible endpoint.
    """

    def __init__(
        self,
        *,
        api_url: str = 'https://api.openai.com/v1/embeddings',
        api_key: str = '',
        model: str = 'text-embedding-3-small',
        dim: int = 1536,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._api_url = api_url
        self._api_key = api_key
        self._model = model
        self._dim = dim
        self._timeout = timeout_seconds

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, text: str) -> list[float]:
        import httpx
        response = httpx.post(
            self._api_url,
            headers={'Authorization': f'Bearer {self._api_key}'},
            json={'input': text, 'model': self._model},
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data['data'][0]['embedding'][:self._dim]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_embedding_provider(
    backend: str = 'local',
    **kwargs,
) -> EmbeddingProvider:
    """Create embedding provider based on configuration.

    backend options:
      - 'local'               — LocalHashEmbeddingProvider (64-dim, dev only)
      - 'sentence-transformer' — SentenceTransformerEmbeddingProvider (384-dim)
      - 'api'                 — ApiEmbeddingProvider (1536-dim)
    """
    backend = backend.strip().lower()
    if backend == 'sentence-transformer':
        return SentenceTransformerEmbeddingProvider(
            model_name=kwargs.get('model_name', 'all-MiniLM-L6-v2'),
        )
    if backend == 'api':
        return ApiEmbeddingProvider(
            api_url=kwargs.get('api_url', 'https://api.openai.com/v1/embeddings'),
            api_key=kwargs.get('api_key', ''),
            model=kwargs.get('model', 'text-embedding-3-small'),
            dim=int(kwargs.get('dim', 1536)),
        )
    return LocalHashEmbeddingProvider(dim=int(kwargs.get('dim', 64)))


# ---------------------------------------------------------------------------
# Legacy function (backward compatible)
# ---------------------------------------------------------------------------

def text_to_embedding(text: str, dim: int = 64) -> list[float]:
    """
    Deterministic local embedding for local-first usage.
    This avoids external embedding providers while keeping vector retrieval functional.

    WARNING: 64-dim hash-based embeddings are functional for demos but
    are NOT production-grade. For real retrieval quality, use
    SentenceTransformerEmbeddingProvider (384-dim) or ApiEmbeddingProvider (1536-dim).
    See create_embedding_provider() for the upgrade path.
    """
    vec = [0.0] * dim
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if not tokens:
        return vec

    for token in tokens:
        h = hashlib.sha256(token.encode("utf-8")).hexdigest()
        idx = int(h[:8], 16) % dim
        sign = -1.0 if int(h[8:10], 16) % 2 else 1.0
        weight = 1.0 + (int(h[10:12], 16) / 255.0)
        vec[idx] += sign * weight

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def vector_to_pg_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"

