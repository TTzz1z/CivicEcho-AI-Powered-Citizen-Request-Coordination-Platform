"""OpenAI-compatible embedding client with deterministic fallback.

When ``EMBEDDING_API_KEY`` is configured, calls the /embeddings endpoint of an
OpenAI-compatible service (e.g. DeepSeek, Volcengine Ark, Silicon Flow, OpenAI).
When unavailable, falls back to a deterministic hashing-based pseudo embedding
so that the RAG pipeline remains functional for demos and tests; the fallback
MUST NOT be used in production.

Round 2 changes:
- EmbeddingResult now carries prompt_tokens / total_tokens / usage_unavailable
  parsed from the model response `usage` block.
- `provider` property derived from base_url (mirrors LlmClient).
- `_call_api` returns full result so usage parsing can happen once.
"""
import hashlib
import json
import logging
import math
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import get_settings

logger = logging.getLogger(__name__)

EMBEDDING_VERSION = "v1"
FALLBACK_DIMENSIONS = 1024


@dataclass
class EmbeddingUsage:
    """Token usage for an embedding batch call."""
    prompt_tokens: int = 0
    total_tokens: int = 0
    unavailable: bool = False


@dataclass
class EmbeddingResult:
    success: bool
    vector: list[float] | None
    model: str
    dimensions: int
    error: str | None = None
    usage: EmbeddingUsage = None  # type: ignore[assignment]
    fallback: bool = False  # True when produced by _fallback_embedding

    def __post_init__(self):
        if self.usage is None:
            self.usage = EmbeddingUsage(unavailable=True)


def _parse_embedding_usage(usage_block: dict | None) -> EmbeddingUsage:
    if not usage_block or not isinstance(usage_block, dict):
        return EmbeddingUsage(unavailable=True)
    try:
        prompt = int(usage_block.get("prompt_tokens", 0) or 0)
        total = int(usage_block.get("total_tokens", prompt) or 0)
        if prompt == 0 and total == 0:
            return EmbeddingUsage(unavailable=True)
        return EmbeddingUsage(prompt_tokens=prompt, total_tokens=total or prompt)
    except (TypeError, ValueError):
        return EmbeddingUsage(unavailable=True)


class EmbeddingClient:
    """Calls OpenAI-compatible /embeddings endpoint."""

    def __init__(self):
        settings = get_settings()
        self.api_key = settings.embedding_api_key
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.timeout = settings.embedding_timeout_seconds

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def provider(self) -> str:
        host = (self.base_url or "").lower()
        if "siliconflow" in host:
            return "silicon_flow"
        if "deepseek" in host:
            return "deepseek"
        if "openai.com" in host:
            return "openai"
        if "volcengine" in host or "ark.cn-beijing" in host:
            return "volcengine"
        return host.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0][:60] or "unknown"

    def embed(self, text: str) -> EmbeddingResult:
        if not text or not text.strip():
            return EmbeddingResult(False, None, self.model or "fallback", self.dimensions,
                                   error="empty_text")
        if self.available:
            try:
                return self._call_api([text])[0]
            except Exception as exc:
                logger.warning("Embedding API failed, falling back: %s", exc)
        # Fallback: deterministic hashed pseudo-embedding
        return EmbeddingResult(
            success=True,
            vector=_fallback_embedding(text, self.dimensions or FALLBACK_DIMENSIONS),
            model="fallback-hash",
            dimensions=self.dimensions or FALLBACK_DIMENSIONS,
            fallback=True,
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []
        if self.available:
            try:
                return self._call_api(texts)
            except Exception as exc:
                logger.warning("Embedding batch API failed, falling back: %s", exc)
        return [EmbeddingResult(
            success=True,
            vector=_fallback_embedding(t, self.dimensions or FALLBACK_DIMENSIONS),
            model="fallback-hash",
            dimensions=self.dimensions or FALLBACK_DIMENSIONS,
            fallback=True,
        ) for t in texts]

    def _call_api(self, texts: list[str]) -> list[EmbeddingResult]:
        payload = json.dumps({
            "model": self.model,
            "input": texts,
            "dimensions": self.dimensions,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            result = json.loads(response.read())
        data_items = result.get("data", [])
        usage = _parse_embedding_usage(result.get("usage"))
        model_name = result.get("model", self.model)
        results: list[EmbeddingResult] = []
        for item in sorted(data_items, key=lambda x: x.get("index", 0)):
            vec = item.get("embedding")
            results.append(EmbeddingResult(
                success=True,
                vector=list(vec) if vec else None,
                model=model_name,
                dimensions=len(vec) if vec else self.dimensions,
                usage=usage,
            ))
        return results


def _fallback_embedding(text: str, dimensions: int) -> list[float]:
    """Deterministic hash-based pseudo-embedding for offline/dev use only.

    Generates a vector by hashing character n-grams. Two texts with similar
    character bigrams will have higher cosine similarity, providing a weak but
    non-random semantic signal so the RAG pipeline stays functional.
    """
    dimensions = max(64, dimensions)
    vec = [0.0] * dimensions
    text = text.lower()
    # Character bigrams (works for both Chinese and ASCII)
    for i in range(len(text) - 1):
        gram = text[i:i + 2]
        h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
        vec[h % dimensions] += 1.0
    # Unigrams for short text
    for ch in text:
        h = int(hashlib.md5(ch.encode("utf-8")).hexdigest(), 16)
        vec[h % dimensions] += 0.3
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client


def reset_embedding_client_for_tests() -> None:
    """Reset the singleton. For tests only."""
    global _client
    _client = EmbeddingClient()
