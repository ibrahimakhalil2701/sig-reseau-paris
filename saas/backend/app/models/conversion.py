"""
Modèles SQLAlchemy — Jobs de conversion géospatiale
"""
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    JSON, BigInteger, Column, DateTime, Enum,
    Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class JobStatus(str, PyEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    EXPIRED = "expired"


class OutputFormat(str, PyEnum):
    GEOJSON = "GeoJSON"
    SHAPEFILE = "ESRI Shapefile"
    GPKG = "GPKG"
    KML = "KML"
    DXF = "DXF"
    CSV = "CSV"
    FILEGDB = "OpenFileGDB"
    FLATGEOBUF = "FlatGeobuf"


class ConversionJob(Base):
    __tablename__ = "conversion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    celery_task_id = Column(String(255), index=True)

    # ── Fichier source ────────────────────────────────────────────────────
    original_filename = Column(String(500), nullable=False)
    input_storage_path = Column(String(1000), nullable=False)
    input_file_size_bytes = Column(BigInteger)
    detected_format = Column(String(50))
    detected_epsg = Column(Integer)            # EPSG détecté automatiquement
    detected_geometry_type = Column(String(50))
    feature_count_input = Column(Integer)

    # ── Paramètres de conversion ──────────────────────────────────────────
    output_format = Column(String(50), nullable=False)
    target_epsg = Column(Integer)              # EPSG cible (optionnel)
    fix_geometries = Column(String(10), default="true")
    normalize_attributes = Column(String(10), default="true")
    encoding = Column(String(20), default="UTF-8")
    options = Column(JSON, default={})         # Options GDAL avancées

    # ── Résultat ──────────────────────────────────────────────────────────
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    output_storage_path = Column(String(1000))
    output_file_size_bytes = Column(BigInteger)
    feature_count_output = Column(Integer)
    processing_time_seconds = Column(Float)
    download_url = Column(String(1000))
    download_expires_at = Column(DateTime)

    # ── Rapport qualité ───────────────────────────────────────────────────
    quality_report = Column(JSON)              # Rapport complet JSON
    geometry_errors_found = Column(Integer, default=0)
    geometry_errors_fixed = Column(Integer, default=0)
    null_geometry_count = Column(Integer, default=0)
    duplicate_count = Column(Integer, default=0)

    # ── Erreur ────────────────────────────────────────────────────────────
    error_message = Column(Text)
    error_traceback = Column(Text)

    # ── Timestamps ───────────────────────────────────────────────────────
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    user = relationship("User", back_populates="conversion_jobs")
