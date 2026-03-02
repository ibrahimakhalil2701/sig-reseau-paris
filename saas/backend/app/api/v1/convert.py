"""
API Conversion — Lancement et suivi des jobs de conversion géospatiale
"""
import uuid
from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.conversion import ConversionJob, JobStatus, OutputFormat
from app.models.user import PlanType, Subscription, User

router = APIRouter(prefix="/convert", tags=["Conversion"])


# ── Schémas ───────────────────────────────────────────────────────────────────

class ConversionRequest(BaseModel):
    storage_path: str = Field(..., description="Chemin retourné par /upload")
    original_filename: str
    output_format: str = Field(..., description="GeoJSON | ESRI Shapefile | GPKG | KML | DXF | CSV | FlatGeobuf")
    target_epsg: Optional[int] = Field(None, description="EPSG cible (ex: 4326, 2154)")
    source_epsg: Optional[int] = Field(None, description="Forcer l'EPSG source si non détecté")
    fix_geometries: bool = Field(True, description="Corriger les géométries invalides")
    normalize_attributes: bool = Field(True, description="Nettoyer et normaliser les attributs")
    encoding: str = Field("UTF-8", description="Encodage de sortie (UTF-8 ou latin-1)")

    @validator("output_format")
    def validate_format(cls, v):
        valid = ["GeoJSON", "ESRI Shapefile", "GPKG", "KML", "DXF", "CSV", "FlatGeobuf", "OpenFileGDB"]
        if v not in valid:
            raise ValueError(f"Format invalide. Valeurs acceptées : {valid}")
        return v

    @validator("target_epsg", "source_epsg", pre=True)
    def validate_epsg(cls, v):
        if v is not None and (v < 1024 or v > 32767):
            raise ValueError("Code EPSG invalide (plage : 1024-32767)")
        return v


class ConversionJobResponse(BaseModel):
    job_id: str
    status: str
    message: str
    created_at: datetime
    estimated_wait_seconds: Optional[int] = None

    class Config:
        from_attributes = True


class ConversionStatusResponse(BaseModel):
    job_id: str
    status: str
    original_filename: str
    output_format: str
    detected_epsg: Optional[int]
    target_epsg: Optional[int]
    feature_count_input: Optional[int]
    feature_count_output: Optional[int]
    processing_time_seconds: Optional[float]
    quality_report: Optional[dict]
    download_url: Optional[str]
    download_expires_at: Optional[datetime]
    error_message: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    total: int
    jobs: list[ConversionStatusResponse]


# ── Vérification quota ────────────────────────────────────────────────────────

PLAN_LIMITS = {
    PlanType.FREE: 5,
    PlanType.STARTER: 100,
    PlanType.PRO: 1000,
    PlanType.ENTERPRISE: -1,
}


async def check_quota(user: User, db: AsyncSession) -> Subscription:
    result = await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    sub = result.scalar_one_or_none()
    if not sub:
        raise HTTPException(status_code=402, detail="Aucun abonnement trouvé.")

    limit = PLAN_LIMITS.get(sub.plan, 5)
    if limit != -1 and sub.conversions_used_this_month >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Quota mensuel atteint ({limit} conversions). "
                   f"Passez au plan supérieur sur geoconvert.io/pricing",
        )
    return sub


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=ConversionJobResponse, status_code=202)
async def create_conversion_job(
    payload: ConversionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Lance un job de conversion asynchrone.
    Retourne immédiatement un job_id pour polling.
    """
    sub = await check_quota(current_user, db)

    # Créer le job en base
    job = ConversionJob(
        user_id=current_user.id,
        original_filename=payload.original_filename,
        input_storage_path=payload.storage_path,
        output_format=payload.output_format,
        target_epsg=payload.target_epsg,
        fix_geometries=str(payload.fix_geometries).lower(),
        normalize_attributes=str(payload.normalize_attributes).lower(),
        encoding=payload.encoding,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.flush()  # Pour obtenir l'ID

    # Lancer le worker Celery
    from app.workers.conversion_tasks import convert_file
    task = convert_file.apply_async(
        args=[str(job.id)],
        task_id=str(job.id),
    )
    job.celery_task_id = task.id

    # Incrémenter compteur quota
    sub.conversions_used_this_month += 1
    await db.commit()

    return ConversionJobResponse(
        job_id=str(job.id),
        status="pending",
        message="Job de conversion créé. Interrogez /status pour suivre la progression.",
        created_at=job.created_at,
        estimated_wait_seconds=30,
    )


@router.get("/{job_id}/status", response_model=ConversionStatusResponse)
async def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retourne le statut et le résultat d'un job de conversion."""
    result = await db.execute(
        select(ConversionJob).where(
            ConversionJob.id == uuid.UUID(job_id),
            ConversionJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable.")

    return ConversionStatusResponse(
        job_id=str(job.id),
        status=job.status.value,
        original_filename=job.original_filename,
        output_format=job.output_format,
        detected_epsg=job.detected_epsg,
        target_epsg=job.target_epsg,
        feature_count_input=job.feature_count_input,
        feature_count_output=job.feature_count_output,
        processing_time_seconds=job.processing_time_seconds,
        quality_report=job.quality_report,
        download_url=job.download_url,
        download_expires_at=job.download_expires_at,
        error_message=job.error_message,
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


@router.get("/", response_model=JobListResponse)
async def list_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
):
    """Liste les jobs de conversion de l'utilisateur."""
    query = select(ConversionJob).where(ConversionJob.user_id == current_user.id)
    count_query = select(func.count()).select_from(ConversionJob).where(
        ConversionJob.user_id == current_user.id
    )

    if status_filter:
        try:
            s = JobStatus(status_filter)
            query = query.where(ConversionJob.status == s)
            count_query = count_query.where(ConversionJob.status == s)
        except ValueError:
            pass

    query = query.order_by(ConversionJob.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    total = await db.execute(count_query)

    jobs = result.scalars().all()
    return JobListResponse(
        total=total.scalar(),
        jobs=[
            ConversionStatusResponse(
                job_id=str(j.id),
                status=j.status.value,
                original_filename=j.original_filename,
                output_format=j.output_format,
                detected_epsg=j.detected_epsg,
                target_epsg=j.target_epsg,
                feature_count_input=j.feature_count_input,
                feature_count_output=j.feature_count_output,
                processing_time_seconds=j.processing_time_seconds,
                quality_report=None,  # Ne pas retourner le rapport complet en liste
                download_url=j.download_url,
                download_expires_at=j.download_expires_at,
                error_message=j.error_message,
                created_at=j.created_at,
                completed_at=j.completed_at,
            )
            for j in jobs
        ],
    )
