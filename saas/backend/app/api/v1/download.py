"""
API Download — Téléchargement sécurisé des fichiers convertis
- URL signées S3 ou téléchargement direct local
- Vérification propriétaire du job
- Expiration automatique (24h)
"""
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.config import settings
from app.core.database import get_db
from app.core.storage import get_storage
from app.models.conversion import ConversionJob, JobStatus
from app.models.user import User

router = APIRouter(prefix="/download", tags=["Download"])


class DownloadUrlResponse(BaseModel):
    job_id: str
    download_url: str
    filename: str
    expires_at: datetime
    file_size_bytes: int | None


@router.get("/{job_id}", response_model=DownloadUrlResponse)
async def get_download_url(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Génère une URL de téléchargement signée valable 1h.
    Le fichier est supprimé automatiquement après 24h.
    """
    result = await db.execute(
        select(ConversionJob).where(
            ConversionJob.id == uuid.UUID(job_id),
            ConversionJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable.")

    if job.status != JobStatus.SUCCESS:
        raise HTTPException(
            status_code=400,
            detail=f"Conversion non terminée. Statut actuel : {job.status.value}",
        )

    if not job.output_storage_path:
        raise HTTPException(status_code=404, detail="Fichier de sortie introuvable.")

    if job.download_expires_at and job.download_expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=410,
            detail="Le fichier a expiré. Relancez la conversion.",
        )

    storage = get_storage()
    download_url = await storage.get_url(job.output_storage_path, expires_in=3600)

    # Construire le nom de sortie
    ext_map = {
        "GeoJSON": ".geojson",
        "ESRI Shapefile": ".zip",
        "GPKG": ".gpkg",
        "KML": ".kml",
        "DXF": ".dxf",
        "CSV": ".csv",
        "FlatGeobuf": ".fgb",
        "OpenFileGDB": ".zip",
    }
    ext = ext_map.get(job.output_format, ".bin")
    stem = Path(job.original_filename).stem
    output_filename = f"{stem}_converted{ext}"

    return DownloadUrlResponse(
        job_id=str(job.id),
        download_url=download_url,
        filename=output_filename,
        expires_at=job.download_expires_at or datetime.utcnow() + timedelta(hours=1),
        file_size_bytes=job.output_file_size_bytes,
    )


@router.get("/file", include_in_schema=False)
async def serve_local_file(
    path: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Endpoint de téléchargement direct pour le backend local.
    En production S3, c'est remplacé par des URL signées.
    """
    # Vérification sécurité : le fichier doit appartenir à l'utilisateur
    result = await db.execute(
        select(ConversionJob).where(
            ConversionJob.output_storage_path == path,
            ConversionJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=403, detail="Accès refusé.")

    if not Path(path).exists():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    return FileResponse(
        path=path,
        filename=Path(path).name,
        media_type="application/octet-stream",
    )
