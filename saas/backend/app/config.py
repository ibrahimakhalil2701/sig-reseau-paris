"""
GeoConvert SaaS — Configuration centralisée
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────
    APP_NAME: str = "GeoConvert SaaS"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # ── Base de données ───────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://saas_user:SaasParis2024!@localhost:5432/geoconvert"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 40

    # ── Sécurité JWT ──────────────────────────────────────────────────────
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_32_BYTES_MIN"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ── Stockage fichiers ─────────────────────────────────────────────────
    # Mode: "local" | "s3" | "minio"
    STORAGE_BACKEND: str = "local"
    UPLOAD_DIR: str = "/tmp/geoconvert/uploads"
    OUTPUT_DIR: str = "/tmp/geoconvert/outputs"
    # S3 / MinIO
    S3_ENDPOINT_URL: str = ""
    S3_BUCKET_UPLOADS: str = "geoconvert-uploads"
    S3_BUCKET_OUTPUTS: str = "geoconvert-outputs"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "eu-west-3"

    # ── Limites upload ────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 100          # Free tier
    MAX_UPLOAD_SIZE_PRO_MB: int = 2000     # Pro tier
    MAX_UPLOAD_SIZE_ENTERPRISE_MB: int = 20000
    ALLOWED_EXTENSIONS: set = {
        "shp", "dbf", "shx", "prj", "cpg",  # Shapefile (ensemble)
        "geojson", "json",
        "kml", "kmz",
        "gpkg",
        "gdb",                              # FileGDB (dossier zippé)
        "dxf",
        "csv",
        "xlsx",
        "zip",                              # Archive multi-fichiers
    }

    # ── Celery / Redis ────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"
    CONVERSION_TIMEOUT_SECONDS: int = 600  # 10 min max par job

    # ── Plans & quotas ────────────────────────────────────────────────────
    PLAN_FREE_CONVERSIONS_PER_MONTH: int = 5
    PLAN_STARTER_CONVERSIONS_PER_MONTH: int = 100
    PLAN_PRO_CONVERSIONS_PER_MONTH: int = 1000
    PLAN_ENTERPRISE_CONVERSIONS_PER_MONTH: int = -1  # illimité

    # ── Stripe ────────────────────────────────────────────────────────────
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTER: str = "price_starter_id"
    STRIPE_PRICE_PRO: str = "price_pro_id"

    # ── Sentry monitoring ─────────────────────────────────────────────────
    SENTRY_DSN: str = ""

    # ── CORS ──────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list = [
        "https://geoconvert.io",
        "https://app.geoconvert.io",
        "http://localhost:3000",
    ]

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
