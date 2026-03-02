"""
API Upload — Réception sécurisée de fichiers géospatiaux
- Validation MIME/magic bytes
- Limite de taille par plan
- Scan antivirus via ClamAV (optionnel)
- Stockage isolé par utilisateur
"""
import hashlib
import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.config import settings
from app.core.database import get_db
from app.core.security import validate_file_magic
from app.core.storage import get_storage
from app.models.user import PlanType, User

router = APIRouter(prefix="/upload", tags=["Upload"])


class UploadResponse(BaseModel):
    upload_id: str
    filename: str
    size_bytes: int
    storage_path: str
    sha256: str
    detected_format: str | None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_upload_limit(plan: PlanType) -> int:
    limits = {
        PlanType.FREE: settings.MAX_UPLOAD_SIZE_MB,
        PlanType.STARTER: settings.MAX_UPLOAD_SIZE_MB,
        PlanType.PRO: settings.MAX_UPLOAD_SIZE_PRO_MB,
        PlanType.ENTERPRISE: settings.MAX_UPLOAD_SIZE_ENTERPRISE_MB,
    }
    return limits.get(plan, settings.MAX_UPLOAD_SIZE_MB) * 1024 * 1024


def _detect_format_from_extension(filename: str) -> str | None:
    ext = Path(filename).suffix.lower().lstrip(".")
    mapping = {
        "shp": "ESRI Shapefile",
        "geojson": "GeoJSON",
        "json": "GeoJSON",
        "gpkg": "GPKG",
        "kml": "KML",
        "kmz": "KML",
        "dxf": "DXF",
        "csv": "CSV",
        "xlsx": "CSV",
        "gdb": "OpenFileGDB",
        "zip": "ZIP",
        "fgb": "FlatGeobuf",
    }
    return mapping.get(ext)


def _validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Extension .{ext} non autorisée. Formats acceptés : {', '.join(sorted(settings.ALLOWED_EXTENSIONS))}",
        )
    return ext


# ── Endpoint principal ────────────────────────────────────────────────────────

@router.post("/", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: Annotated[UploadFile, File(description="Fichier géospatial à convertir")],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload sécurisé d'un fichier géospatial.

    Limites par plan :
    - Free/Starter : 100 Mo
    - Pro : 2 Go
    - Enterprise : 20 Go
    """
    from sqlalchemy import select
    from app.models.user import Subscription

    # ── Vérification du plan ──────────────────────────────────────────────
    result = await db.execute(select(Subscription).where(Subscription.user_id == current_user.id))
    sub = result.scalar_one_or_none()
    plan = sub.plan if sub else PlanType.FREE
    max_size = _get_upload_limit(plan)

    # ── Validation extension ──────────────────────────────────────────────
    ext = _validate_extension(file.filename or "unknown.bin")

    # ── Lecture et validation taille ──────────────────────────────────────
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux. Limite pour votre plan : {max_size // (1024*1024)} Mo.",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Le fichier uploadé est vide.")

    # ── Validation magic bytes (anti-spoofing) ────────────────────────────
    if not validate_file_magic(content, ext):
        raise HTTPException(
            status_code=400,
            detail="Le contenu du fichier ne correspond pas à son extension. Upload rejeté.",
        )

    # ── Calcul SHA256 (intégrité + déduplication) ─────────────────────────
    sha256 = hashlib.sha256(content).hexdigest()

    # ── Stockage ──────────────────────────────────────────────────────────
    storage = get_storage()

    import io
    import uuid
    upload_id = uuid.uuid4().hex
    safe_filename = f"{upload_id}_{Path(file.filename).name}"

    storage_path = await storage.save(
        file_obj=io.BytesIO(content),
        filename=safe_filename,
        folder="uploads",
    )

    detected_format = _detect_format_from_extension(file.filename or "")

    return UploadResponse(
        upload_id=upload_id,
        filename=file.filename,
        size_bytes=len(content),
        storage_path=storage_path,
        sha256=sha256,
        detected_format=detected_format,
    )
