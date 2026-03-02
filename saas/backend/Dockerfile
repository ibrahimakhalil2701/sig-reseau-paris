# =============================================================================
# GeoConvert SaaS — Dockerfile Backend
# Base : python-gdal officiel (GDAL pré-compilé avec tous les drivers)
# =============================================================================

FROM ghcr.io/osgeo/gdal:ubuntu-full-3.8.4 AS base

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    GDAL_DATA=/usr/share/gdal \
    PROJ_LIB=/usr/share/proj

# Dépendances système
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    python3-dev \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dépendances Python ────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── Code application ──────────────────────────────────────────────────────────
COPY app/ ./app/

# ── Utilisateur non-root (sécurité) ──────────────────────────────────────────
RUN groupadd -r geoconvert && useradd -r -g geoconvert geoconvert && \
    mkdir -p /tmp/geoconvert/uploads /tmp/geoconvert/outputs && \
    chown -R geoconvert:geoconvert /tmp/geoconvert /app

USER geoconvert

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# ── Commande par défaut (API) ─────────────────────────────────────────────────
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--log-level", "info"]

# ── Stage worker Celery (même image, commande différente) ─────────────────────
FROM base AS worker
CMD ["celery", "-A", "app.core.celery_app.celery_app", "worker", \
     "--loglevel=info", "--concurrency=2", "-Q", "conversion,maintenance"]
