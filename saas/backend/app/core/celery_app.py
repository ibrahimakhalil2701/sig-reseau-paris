"""
Configuration Celery — Worker de traitement géospatial asynchrone
"""
from celery import Celery

from app.config import settings

celery_app = Celery(
    "geoconvert",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.workers.conversion_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Timeout strict par job
    task_soft_time_limit=settings.CONVERSION_TIMEOUT_SECONDS,
    task_time_limit=settings.CONVERSION_TIMEOUT_SECONDS + 30,
    # Retry automatique sur erreur réseau
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # 1 tâche à la fois par worker
    # Résultats conservés 24h
    result_expires=86400,
    # Routage par priorité
    task_routes={
        "app.workers.conversion_tasks.convert_file": {"queue": "conversion"},
        "app.workers.conversion_tasks.cleanup_expired_files": {"queue": "maintenance"},
    },
    task_queues={
        "conversion": {"exchange": "conversion", "routing_key": "conversion"},
        "maintenance": {"exchange": "maintenance", "routing_key": "maintenance"},
    },
)
