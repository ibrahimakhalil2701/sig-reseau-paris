"""
GeoConvert SaaS — Point d'entrée FastAPI
"""
import time
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import auth, convert, download, upload
from app.config import settings
from app.core.database import engine, Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Shutdown
    await engine.dispose()


# ── Sentry ────────────────────────────────────────────────────────────────────
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=0.1,
    )


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## GeoConvert SaaS API

Plateforme de conversion intelligente de fichiers géospatiaux.

### Fonctionnalités
- **Upload** sécurisé (SHP, GeoJSON, GPKG, KML, DXF, CSV, FileGDB)
- **Conversion** entre tous les formats SIG majeurs
- **Détection automatique** de la projection (EPSG)
- **Reprojection** vers n'importe quel EPSG cible
- **Correction** des géométries invalides
- **Normalisation** des attributs
- **Rapport qualité** avec score 0-100
- **Téléchargement** sécurisé via URL signée (24h)

### Plans
| Plan | Conversions/mois | Taille max | Prix |
|------|-----------------|------------|------|
| Free | 5 | 100 Mo | Gratuit |
| Starter | 100 | 100 Mo | 29€/mois |
| Pro | 1 000 | 2 Go | 99€/mois |
| Enterprise | Illimité | 20 Go | Sur devis |
    """,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── Middlewares ───────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{time.perf_counter() - start:.3f}s"
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


# ── Routes ────────────────────────────────────────────────────────────────────

PREFIX = "/api/v1"

app.include_router(auth.router, prefix=PREFIX)
app.include_router(upload.router, prefix=PREFIX)
app.include_router(convert.router, prefix=PREFIX)
app.include_router(download.router, prefix=PREFIX)


@app.get("/api/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@app.get("/api/formats", tags=["Info"])
async def list_formats():
    """Liste les formats d'entrée et de sortie supportés."""
    from app.services.gdal_processor import GDALProcessor
    return {
        "input_formats": [
            "ESRI Shapefile (.shp + ZIP)",
            "GeoJSON (.geojson)",
            "GeoPackage (.gpkg)",
            "KML/KMZ (.kml, .kmz)",
            "DXF (.dxf)",
            "CSV géoréférencé (.csv)",
            "FileGDB (.gdb dans ZIP)",
            "FlatGeobuf (.fgb)",
        ],
        "output_formats": GDALProcessor.list_supported_formats(),
    }


# ── Gestionnaire d'erreurs global ─────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    if settings.DEBUG:
        import traceback
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc), "traceback": traceback.format_exc()},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne. Notre équipe a été notifiée."},
    )
