"""
Gestion du stockage — Local, S3, MinIO
Strategy pattern : même interface quel que soit le backend.
"""
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError

from app.config import settings


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, file_obj: BinaryIO, filename: str, folder: str) -> str:
        """Sauvegarde un fichier et retourne le chemin/clé de stockage."""

    @abstractmethod
    async def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
        """Génère une URL de téléchargement (signée ou directe)."""

    @abstractmethod
    async def delete(self, storage_path: str) -> None:
        """Supprime un fichier du stockage."""

    @abstractmethod
    async def read(self, storage_path: str) -> bytes:
        """Lit le contenu d'un fichier."""


class LocalStorage(StorageBackend):
    """Stockage local — développement et petits déploiements."""

    def __init__(self):
        Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        Path(settings.OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    async def save(self, file_obj: BinaryIO, filename: str, folder: str = "uploads") -> str:
        base = settings.UPLOAD_DIR if folder == "uploads" else settings.OUTPUT_DIR
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        path = os.path.join(base, unique_name)
        with open(path, "wb") as f:
            f.write(file_obj.read())
        return path

    async def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
        # En local, on retourne juste le chemin — l'API sert le fichier directement
        return f"/api/v1/download/file?path={storage_path}"

    async def delete(self, storage_path: str) -> None:
        if os.path.exists(storage_path):
            os.remove(storage_path)

    async def read(self, storage_path: str) -> bytes:
        with open(storage_path, "rb") as f:
            return f.read()


class S3Storage(StorageBackend):
    """Stockage AWS S3 / MinIO — production."""

    def __init__(self):
        kwargs = {
            "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
            "region_name": settings.AWS_REGION,
        }
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        self.client = boto3.client("s3", **kwargs)

    async def save(self, file_obj: BinaryIO, filename: str, folder: str = "uploads") -> str:
        bucket = settings.S3_BUCKET_UPLOADS if folder == "uploads" else settings.S3_BUCKET_OUTPUTS
        key = f"{folder}/{uuid.uuid4().hex}/{filename}"
        self.client.upload_fileobj(file_obj, bucket, key)
        return f"s3://{bucket}/{key}"

    async def get_url(self, storage_path: str, expires_in: int = 3600) -> str:
        # storage_path format: s3://bucket/key
        parts = storage_path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def delete(self, storage_path: str) -> None:
        parts = storage_path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        self.client.delete_object(Bucket=bucket, Key=key)

    async def read(self, storage_path: str) -> bytes:
        parts = storage_path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()


def get_storage() -> StorageBackend:
    if settings.STORAGE_BACKEND == "s3" or settings.STORAGE_BACKEND == "minio":
        return S3Storage()
    return LocalStorage()
