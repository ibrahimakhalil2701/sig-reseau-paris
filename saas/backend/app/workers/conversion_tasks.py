"""
Workers Celery — Traitement asynchrone des conversions géospatiales
"""
import os
import traceback
import uuid
from datetime import datetime, timedelta

from celery import current_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core.celery_app import celery_app
from app.models.conversion import ConversionJob, JobStatus
from app.services.gdal_processor import GDALProcessor

# Session synchrone pour Celery (pas async)
sync_engine = create_engine(
    settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"),
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)


@celery_app.task(
    bind=True,
    name="app.workers.conversion_tasks.convert_file",
    max_retries=2,
    default_retry_delay=10,
    acks_late=True,
)
def convert_file(self, job_id: str) -> dict:
    """
    Worker principal de conversion géospatiale.
    Exécuté de façon isolée dans un worker Celery.
    """
    with SyncSession() as db:
        job = db.query(ConversionJob).filter(ConversionJob.id == uuid.UUID(job_id)).first()
        if not job:
            return {"error": f"Job {job_id} introuvable"}

        # ── Marquer comme en cours ────────────────────────────────────────
        job.status = JobStatus.PROCESSING
        job.started_at = datetime.utcnow()
        db.commit()

        try:
            # ── Mise à jour de progression ─────────────────────────────────
            current_task.update_state(
                state="PROGRESS",
                meta={"step": "reading_file", "progress": 10}
            )

            # ── Résoudre le fichier source ─────────────────────────────────
            input_path = _resolve_input_path(job.input_storage_path)

            # ── Lancer le processeur GDAL ──────────────────────────────────
            processor = GDALProcessor()
            current_task.update_state(
                state="PROGRESS",
                meta={"step": "processing", "progress": 30}
            )

            result = processor.process(
                input_path=input_path,
                output_format=job.output_format,
                target_epsg=job.target_epsg,
                fix_geometries=job.fix_geometries == "true",
                normalize_attributes=job.normalize_attributes == "true",
                encoding=job.encoding or "UTF-8",
            )

            current_task.update_state(
                state="PROGRESS",
                meta={"step": "saving_output", "progress": 80}
            )

            # ── Stocker le fichier de sortie ───────────────────────────────
            output_storage_path = _store_output(result.output_path, job_id)
            output_size = os.path.getsize(result.output_path)

            # ── Mettre à jour le job ───────────────────────────────────────
            job.status = JobStatus.SUCCESS
            job.completed_at = datetime.utcnow()
            job.output_storage_path = output_storage_path
            job.output_file_size_bytes = output_size
            job.feature_count_input = result.quality_report["summary"]["features_input"]
            job.feature_count_output = result.feature_count
            job.detected_epsg = result.source_epsg
            job.processing_time_seconds = result.processing_time_s
            job.quality_report = result.quality_report
            job.geometry_errors_found = result.geometry_stats.get("invalid_before", 0)
            job.geometry_errors_fixed = result.geometry_stats.get("fixed", 0)
            job.null_geometry_count = result.geometry_stats.get("null_geometry", 0)
            job.duplicate_count = result.geometry_stats.get("duplicates_removed", 0)
            job.download_expires_at = datetime.utcnow() + timedelta(hours=24)

            # URL de téléchargement
            job.download_url = f"/api/v1/download/{job_id}"

            db.commit()

            return {
                "job_id": job_id,
                "status": "success",
                "feature_count": result.feature_count,
                "quality_score": result.quality_report.get("quality_score", 0),
            }

        except SoftTimeLimitExceeded:
            _mark_failed(db, job, "Timeout dépassé (10 minutes). Fichier trop volumineux.")
            return {"job_id": job_id, "status": "timeout"}

        except Exception as exc:
            error_tb = traceback.format_exc()
            _mark_failed(db, job, str(exc), error_tb)

            # Retry automatique pour erreurs transitoires
            if "Connection" in str(exc) or "timeout" in str(exc).lower():
                raise self.retry(exc=exc)

            return {"job_id": job_id, "status": "failed", "error": str(exc)}


@celery_app.task(name="app.workers.conversion_tasks.cleanup_expired_files")
def cleanup_expired_files():
    """
    Tâche de maintenance : supprime les fichiers expirés (>24h).
    À planifier toutes les heures via Celery Beat.
    """
    from app.core.storage import get_storage
    import asyncio

    with SyncSession() as db:
        expired_jobs = db.query(ConversionJob).filter(
            ConversionJob.download_expires_at < datetime.utcnow(),
            ConversionJob.output_storage_path.isnot(None),
            ConversionJob.status == JobStatus.SUCCESS,
        ).all()

        storage = get_storage()
        cleaned = 0
        for job in expired_jobs:
            try:
                # Suppression synchrone (storage.delete est async → run_sync)
                import asyncio
                asyncio.run(storage.delete(job.output_storage_path))
                job.output_storage_path = None
                job.status = JobStatus.EXPIRED
                cleaned += 1
            except Exception:
                pass

        db.commit()
        return {"cleaned_files": cleaned}


# ── Helpers privés ────────────────────────────────────────────────────────────

def _resolve_input_path(storage_path: str) -> str:
    """Retourne le chemin local — télécharge depuis S3 si nécessaire."""
    if storage_path.startswith("s3://"):
        from app.core.storage import get_storage
        import asyncio, tempfile
        storage = get_storage()
        content = asyncio.run(storage.read(storage_path))
        suffix = "." + storage_path.split(".")[-1]
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.write(content)
        tmp.close()
        return tmp.name
    return storage_path


def _store_output(output_path: str, job_id: str) -> str:
    """Stocke le fichier de sortie et retourne le chemin de stockage."""
    if settings.STORAGE_BACKEND in ("s3", "minio"):
        from app.core.storage import get_storage
        import asyncio
        storage = get_storage()
        with open(output_path, "rb") as f:
            path = asyncio.run(storage.save(f, os.path.basename(output_path), "outputs"))
        os.remove(output_path)  # Nettoyage local
        return path
    return output_path


def _mark_failed(db: Session, job: ConversionJob, error: str, tb: str = "") -> None:
    job.status = JobStatus.FAILED
    job.completed_at = datetime.utcnow()
    job.error_message = error[:2000]
    job.error_traceback = tb[:5000]
    db.commit()
