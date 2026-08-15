"""Embedding providers.

* ``LocalHashEmbedder`` — deterministic hashed n-gram projection (offline dev/test;
  NOT production-grade semantic quality; clearly documented).
* ``OpenAIEmbedder`` — official embeddings API (requires key).
* ``OllamaEmbedder`` — local /api/embeddings.
"""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class Embedder(ABC):
    dim: int

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]


class LocalHashEmbedder(Embedder):
    """Deterministic feature-hashing embedder. Offline, zero dependencies.

    Projects word/char n-gram hashes into a fixed-dim unit vector. Suitable for
    dev, tests and self-hosted deployments without any model; semantic quality
    is far below real embeddings — production should configure OpenAI or Ollama.
    """

    name = "local-hash"

    def __init__(self, dim: int = 1536):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self.dim
            grams: set[str] = set(_tokens(text))
            for tok in _tokens(text):
                grams.add("w:" + tok)
            for i in range(len(text) - 2):
                grams.add("c:" + text[i : i + 3].lower())
            for gram in grams:
                idx = int(hashlib.sha256(gram.encode()).hexdigest()[:8], 16) % self.dim
                vec[idx] += 1.0
            norm = math.sqrt(sum(v * v for v in vec))
            if norm > 0:
                vec = [v / norm for v in vec]
            out.append(vec)
        return out


class OpenAIEmbedder(Embedder):
    name = "openai"

    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dim: int = 1536):
        self.api_key = api_key
        self.model = model
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            data.sort(key=lambda d: d["index"])
            return [list(map(float, d["embedding"])) for d in data]


class OllamaEmbedder(Embedder):
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dim = 0  # set from first response

    def embed(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=30.0) as client:
            out = []
            for text in texts:
                resp = client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                resp.raise_for_status()
                vec = [float(v) for v in resp.json()["embedding"]]
                self.dim = len(vec)
                out.append(vec)
            return out


def get_embedder(settings: Settings) -> Embedder:
    backend = settings.embedding_backend
    if backend == "openai":
        if not settings.openai_api_key:
            raise RuntimeError(
                "PRISM_EMBEDDING_BACKEND=openai requires PRISM_OPENAI_API_KEY"
            )
        return OpenAIEmbedder(
            settings.openai_api_key, settings.embedding_model or "text-embedding-3-small",
            settings.embedding_dim,
        )
    if backend == "ollama":
        return OllamaEmbedder(
            settings.ollama_base_url, settings.embedding_model or "nomic-embed-text"
        )
    return LocalHashEmbedder(settings.embedding_dim)
