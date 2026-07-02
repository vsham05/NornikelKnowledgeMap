import logging
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, MatchAny

from domain.dto.document import DocumentChunkDTO
from domain.dto.image import ImageDTO
from settings import Settings

logger = logging.getLogger(__name__)


class VectorDB:
    """Работа с Qdrant векторной БД."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = QdrantClient(
            url=settings.qdrant_url,
            check_compatibility=False,
        )
        self.text_collection = settings.qdrant_collection_text
        self.visual_collection = settings.qdrant_collection_visual
        
        # Создаем коллекции если их нет
        self._ensure_collections()
        
        logger.info("Connected to Qdrant")
    
    def _ensure_collections(self):
        """Создает коллекции если их нет."""
        collections = self.client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if self.text_collection not in collection_names:
            self.client.create_collection(
                collection_name=self.text_collection,
                vectors_config=VectorParams(
                    size=self.settings.embedding_dimensions,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created collection: {self.text_collection}")
        
        if self.visual_collection not in collection_names:
            self.client.create_collection(
                collection_name=self.visual_collection,
                vectors_config=VectorParams(size=512, distance=Distance.COSINE)
            )
            logger.info(f"Created collection: {self.visual_collection}")
    
    def save_text_chunk(self, chunk: DocumentChunkDTO, embedding: list[float]):
        """Сохраняет текстовый чанк с эмбеддингом."""
        self.client.upsert(
            collection_name=self.text_collection,
            points=[
                PointStruct(
                    id=str(chunk.id),
                    vector=embedding,
                    payload={
                        "document_id": str(chunk.document_id),
                        "text": chunk.text,
                        "page_number": chunk.page_number
                    }
                )
            ]
        )
        logger.info(f"Saved text chunk: {chunk.id}")
    
    def save_image(self, image: ImageDTO):
        """Сохраняет изображение с визуальным эмбеддингом."""
        if image.visual_embedding is None:
            logger.warning(f"Image {image.id} has no visual embedding")
            return
        
        self.client.upsert(
            collection_name=self.visual_collection,
            points=[
                PointStruct(
                    id=str(image.id),
                    vector=image.visual_embedding,
                    payload={
                        "document_id": str(image.document_id),
                        "file_path": image.file_path,
                        "ai_description": image.ai_description
                    }
                )
            ]
        )
        logger.info(f"Saved image: {image.id}")
    
    def delete_document_chunks(self, document_id: str):
        """Remove all vector entries for a document."""
        for collection in (self.text_collection, self.visual_collection):
            self.client.delete(
                collection_name=collection,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=document_id),
                        )
                    ]
                ),
            )
        logger.info(f"Deleted vector chunks for document: {document_id}")

    def clear_all_collections(self) -> None:
        """Drop and recreate vector collections (full vector index reset)."""
        for name in (self.text_collection, self.visual_collection):
            try:
                self.client.delete_collection(name)
                logger.info("Deleted Qdrant collection: %s", name)
            except Exception as exc:
                logger.warning("Could not delete collection %s: %s", name, exc)
        self._ensure_collections()

    def search_similar_text(
        self,
        query_embedding: list[float],
        limit: int = 10,
        *,
        document_id: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[dict]:
        """Search similar text chunks by embedding."""
        query_filter = None
        if document_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=document_id),
                    )
                ]
            )
        elif document_ids:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchAny(any=list(document_ids)),
                    )
                ]
            )
        response = self.client.query_points(
            collection_name=self.text_collection,
            query=query_embedding,
            limit=limit,
            query_filter=query_filter,
        )
        return [
            {
                "id": point.id,
                "score": point.score,
                "payload": point.payload,
            }
            for point in response.points
        ]

    def search_similar_images(self, query_embedding: list[float], limit: int = 10) -> list[dict]:
        """Search similar images by embedding."""
        response = self.client.query_points(
            collection_name=self.visual_collection,
            query=query_embedding,
            limit=limit,
        )
        return [
            {
                "id": point.id,
                "score": point.score,
                "payload": point.payload,
            }
            for point in response.points
        ]