import logging

import httpx

from settings import Settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Embeddings via Ollama native /api/embed (LangChain OpenAI shim breaks on Ollama)."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.embedding_model
        base = settings.embedding_base_url or settings.llm_base_url
        self.ollama_base = base.replace("/v1", "").rstrip("/")
        logger.info(f"Initialized embedding client: {self.model} @ {self.ollama_base}")

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

    async def embed_text(self, text: str) -> list[float]:
        vectors = await self._request_embeddings([text.strip()])
        return vectors[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean = [t.strip() for t in texts if t and t.strip()]
        if not clean:
            return []
        logger.info(f"Generating embeddings for {len(clean)} texts")
        vectors = await self._request_embeddings(clean)
        logger.info(f"Generated {len(vectors)} embeddings")
        return vectors

    async def embed_query(self, query: str) -> list[float]:
        return await self.embed_text(query)
