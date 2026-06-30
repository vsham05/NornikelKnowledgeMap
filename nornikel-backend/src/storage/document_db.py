import logging
from pathlib import Path

from minio import Minio

from domain.dto.document import DocumentDTO
from domain.dto.image import ImageDTO
from settings import Settings

logger = logging.getLogger(__name__)


class DocumentDB:
    """Работа с MinIO объектным хранилищем."""
    
    def __init__(self, settings: Settings):
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure
        )
        self.bucket = settings.minio_bucket
        
        # Создаем bucket если его нет
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)
            logger.info(f"Created bucket: {self.bucket}")
        
        logger.info("Connected to MinIO")
    
    def upload_file(self, local_path: Path, object_name: str) -> str:
        """Загружает файл в MinIO."""
        self.client.fput_object(
            self.bucket,
            object_name,
            str(local_path)
        )
        logger.info(f"Uploaded file: {object_name}")
        return f"{self.bucket}/{object_name}"
    
    def save_document(self, document: DocumentDTO):
        """Сохраняет метаданные документа (TODO: в Postgres)."""
        # TODO: Сохранение в Postgres
        logger.info(f"Saved document metadata: {document.id}")
    
    def save_image(self, image: ImageDTO):
        """Сохраняет метаданные изображения (TODO: в Postgres)."""
        # TODO: Сохранение в Postgres
        logger.info(f"Saved image metadata: {image.id}")