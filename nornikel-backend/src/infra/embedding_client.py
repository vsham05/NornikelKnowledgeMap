import logging
import re

import httpx

from settings import Settings

logger = logging.getLogger(__name__)

# Instruction-tuned embedding models need asymmetric prefixes (query vs document).
# See: https://huggingface.co/mixedbread-ai/mxbai-embed-large-v1
MXBAI_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
NOMIC_QUERY_PREFIX = "search_query: "
NOMIC_DOCUMENT_PREFIX = "search_document: "


def query_embedding_prefix(model: str) -> str | None:
    m = (model or "").strip().lower()
    if "mxbai" in m:
        return MXBAI_QUERY_PREFIX
    if "nomic" in m:
        return NOMIC_QUERY_PREFIX
    return None


def document_embedding_prefix(model: str) -> str | None:
    m = (model or "").strip().lower()
    if "nomic" in m:
        return NOMIC_DOCUMENT_PREFIX
    return None


class EmbeddingClient:
    """Embeddings via Ollama native /api/embed (LangChain OpenAI shim breaks on Ollama)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.embedding_model
        base = settings.embedding_base_url or settings.llm_base_url
        self.ollama_base = base.replace("/v1", "").rstrip("/")
        self._query_prefix = query_embedding_prefix(self.model)
        self._document_prefix = document_embedding_prefix(self.model)
        if self._query_prefix:
            logger.info(
                "Embedding client: %s @ %s (query prefix enabled for retrieval)",
                self.model,
                self.ollama_base,
            )
        else:
            logger.info(f"Initialized embedding client: {self.model} @ {self.ollama_base}")

    def _prepare_for_index(self, text: str) -> str:
        cleaned = text.strip()
        if self._document_prefix and not cleaned.startswith(self._document_prefix):
            return f"{self._document_prefix}{cleaned}"
        return cleaned

    def _prepare_for_query(self, text: str) -> str:
        cleaned = text.strip()
        if self._query_prefix and not cleaned.startswith(self._query_prefix):
            return f"{self._query_prefix}{cleaned}"
        return cleaned

    async def _request_embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict = {"model": self.model, "input": texts[0] if len(texts) == 1 else texts}

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.ollama_base}/api/embed", json=payload)
            if response.status_code == 400 and len(texts) > 1:
                vectors: list[list[float]] = []
                for text in texts:
                    vectors.extend(await self._request_embeddings([text]))
                return vectors
            response.raise_for_status()
            data = response.json()

        embeddings = data.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            return embeddings

        single = data.get("embedding")
        if isinstance(single, list):
            return [single]

        raise ValueError(f"Unexpected Ollama embed response: {list(data.keys())}")

    async def embed_text(self, text: str, *, for_query: bool = False) -> list[float]:
        prepared = self._prepare_for_query(text) if for_query else self._prepare_for_index(text)
        vectors = await self._request_embeddings([prepared])
        return vectors[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean = [t.strip() for t in texts if t and t.strip()]
        if not clean:
            return []
        prepared = [self._prepare_for_index(t) for t in clean]
        logger.info(f"Generating embeddings for {len(prepared)} texts")
        vectors = await self._request_embeddings(prepared)
        logger.info(f"Generated {len(vectors)} embeddings")
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(query, for_query=True)
