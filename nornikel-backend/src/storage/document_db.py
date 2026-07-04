import logging
from io import BytesIO
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
    
    def upload_image_bytes(
        self,
        document_id: str,
        image_id: str,
        data: bytes,
        ext: str,
    ) -> str:
        """Store extracted figure bytes; returns MinIO object key."""
        safe_ext = (ext or "png").lower().lstrip(".")
        object_name = f"documents/{document_id}/images/{image_id}.{safe_ext}"
        content_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }.get(safe_ext, "application/octet-stream")
        self.client.put_object(
            self.bucket,
            object_name,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return object_name

    def get_image_bytes(self, object_name: str) -> tuple[bytes, str]:
        response = self.client.get_object(self.bucket, object_name)
        try:
            data = response.read()
            content_type = response.headers.get("Content-Type", "image/png")
            return data, content_type
        finally:
            response.close()
            response.release_conn()

    def delete_document_images(self, document_id: str) -> None:
        prefix = f"documents/{document_id}/images/"
        try:
            objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
            for obj in objects:
                if obj.object_name:
                    self.client.remove_object(self.bucket, obj.object_name)
        except Exception as exc:
            logger.warning("MinIO image cleanup for %s: %s", document_id, exc)

    def save_document(self, document: DocumentDTO):
        """Сохраняет метаданные документа (TODO: в Postgres)."""
        # TODO: Сохранение в Postgres
        logger.info(f"Saved document metadata: {document.id}")
    
    def save_image(self, image: ImageDTO):
        """Сохраняет метаданные изображения (TODO: в Postgres)."""
        # TODO: Сохранение в Postgres
        logger.info(f"Saved image metadata: {image.id}")