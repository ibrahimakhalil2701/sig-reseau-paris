-- =============================================================================
-- SCHEMA BASE DE DONNÉES — GeoConvert SaaS
-- Stack : PostgreSQL 15 + PostGIS 3.4
-- Auteur : Ibrahima Khalil Mbacke
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- Recherche texte rapide
CREATE EXTENSION IF NOT EXISTS postgis;

-- =============================================================================
-- PLANS & ABONNEMENTS
-- =============================================================================

CREATE TYPE plan_type AS ENUM ('free', 'starter', 'pro', 'enterprise');
CREATE TYPE job_status AS ENUM ('pending', 'processing', 'success', 'failed', 'expired');

-- =============================================================================
-- UTILISATEURS
-- =============================================================================

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    full_name       VARCHAR(255),
    company         VARCHAR(255),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
    is_superuser    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users (email);

-- Trigger updated_at automatique
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- ABONNEMENTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS subscriptions (
    id                         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan                       plan_type NOT NULL DEFAULT 'free',
    stripe_customer_id         VARCHAR(255) UNIQUE,
    stripe_subscription_id     VARCHAR(255) UNIQUE,
    conversions_used_this_month INTEGER NOT NULL DEFAULT 0
                               CHECK (conversions_used_this_month >= 0),
    current_period_start       TIMESTAMPTZ,
    current_period_end         TIMESTAMPTZ,
    is_active                  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                 TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id)
);

CREATE INDEX idx_subscriptions_stripe_customer ON subscriptions (stripe_customer_id);

-- Reset mensuel des quotas (à appeler via pg_cron ou Celery Beat)
CREATE OR REPLACE FUNCTION reset_monthly_quotas()
RETURNS void AS $$
BEGIN
    UPDATE subscriptions
    SET conversions_used_this_month = 0
    WHERE current_period_end < NOW();
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- API KEYS
-- =============================================================================

CREATE TABLE IF NOT EXISTS api_keys (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_prefix   VARCHAR(10) NOT NULL,
    key_hash     VARCHAR(64) UNIQUE NOT NULL,  -- SHA-256
    name         VARCHAR(100),
    last_used_at TIMESTAMPTZ,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_user ON api_keys (user_id);
CREATE INDEX idx_api_keys_hash ON api_keys (key_hash);

-- =============================================================================
-- JOBS DE CONVERSION
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversion_jobs (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    celery_task_id          VARCHAR(255),

    -- Fichier source
    original_filename       VARCHAR(500) NOT NULL,
    input_storage_path      VARCHAR(1000) NOT NULL,
    input_file_size_bytes   BIGINT,
    detected_format         VARCHAR(50),
    detected_epsg           INTEGER,
    detected_geometry_type  VARCHAR(50),
    feature_count_input     INTEGER,

    -- Paramètres de conversion
    output_format           VARCHAR(50) NOT NULL,
    target_epsg             INTEGER,
    fix_geometries          VARCHAR(10) DEFAULT 'true',
    normalize_attributes    VARCHAR(10) DEFAULT 'true',
    encoding                VARCHAR(20) DEFAULT 'UTF-8',
    options                 JSONB DEFAULT '{}',

    -- Résultat
    status                  job_status NOT NULL DEFAULT 'pending',
    output_storage_path     VARCHAR(1000),
    output_file_size_bytes  BIGINT,
    feature_count_output    INTEGER,
    processing_time_seconds NUMERIC(10, 3),
    download_url            VARCHAR(1000),
    download_expires_at     TIMESTAMPTZ,

    -- Rapport qualité
    quality_report          JSONB,
    geometry_errors_found   INTEGER DEFAULT 0,
    geometry_errors_fixed   INTEGER DEFAULT 0,
    null_geometry_count     INTEGER DEFAULT 0,
    duplicate_count         INTEGER DEFAULT 0,

    -- Erreur
    error_message           TEXT,
    error_traceback         TEXT,

    -- Timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at              TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ
);

-- Index pour requêtes fréquentes
CREATE INDEX idx_jobs_user_id      ON conversion_jobs (user_id);
CREATE INDEX idx_jobs_status       ON conversion_jobs (status);
CREATE INDEX idx_jobs_created_at   ON conversion_jobs (created_at DESC);
CREATE INDEX idx_jobs_celery_id    ON conversion_jobs (celery_task_id);
CREATE INDEX idx_jobs_quality      ON conversion_jobs USING GIN (quality_report);
CREATE INDEX idx_jobs_expires      ON conversion_jobs (download_expires_at)
    WHERE status = 'success';

-- =============================================================================
-- ANALYTICS & USAGE (pour le dashboard admin)
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_events (
    id              BIGSERIAL PRIMARY KEY,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type      VARCHAR(50) NOT NULL,  -- 'conversion', 'upload', 'download'
    metadata        JSONB DEFAULT '{}',
    ip_address      INET,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Partition par mois (créer manuellement ou via script)
CREATE TABLE usage_events_2025_01 PARTITION OF usage_events
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE usage_events_2025_02 PARTITION OF usage_events
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-02');
CREATE TABLE usage_events_2026_01 PARTITION OF usage_events
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE usage_events_2026_02 PARTITION OF usage_events
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE usage_events_2026_03 PARTITION OF usage_events
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
CREATE TABLE usage_events_default PARTITION OF usage_events DEFAULT;

CREATE INDEX idx_usage_user     ON usage_events (user_id, created_at DESC);
CREATE INDEX idx_usage_type     ON usage_events (event_type, created_at DESC);

-- =============================================================================
-- VUES ANALYTIQUES
-- =============================================================================

-- Dashboard admin : conversions par plan ce mois
CREATE OR REPLACE VIEW v_conversions_by_plan AS
SELECT
    s.plan,
    COUNT(j.id)                                         AS total_jobs,
    COUNT(j.id) FILTER (WHERE j.status = 'success')     AS successful,
    COUNT(j.id) FILTER (WHERE j.status = 'failed')      AS failed,
    ROUND(AVG(j.processing_time_seconds)::NUMERIC, 2)   AS avg_processing_s,
    ROUND(AVG((j.quality_report->>'quality_score')::NUMERIC), 1) AS avg_quality_score,
    SUM(j.output_file_size_bytes) / 1048576              AS total_output_mb
FROM conversion_jobs j
JOIN users u ON j.user_id = u.id
JOIN subscriptions s ON u.id = s.user_id
WHERE j.created_at >= DATE_TRUNC('month', NOW())
GROUP BY s.plan;

-- Format populaires
CREATE OR REPLACE VIEW v_popular_formats AS
SELECT
    output_format,
    COUNT(*) AS usage_count,
    ROUND(AVG(processing_time_seconds)::NUMERIC, 2) AS avg_seconds
FROM conversion_jobs
WHERE status = 'success'
  AND created_at >= NOW() - INTERVAL '30 days'
GROUP BY output_format
ORDER BY usage_count DESC;

-- Utilisateurs actifs ce mois
CREATE OR REPLACE VIEW v_active_users AS
SELECT
    u.id,
    u.email,
    u.company,
    s.plan,
    s.conversions_used_this_month,
    COUNT(j.id) AS total_conversions_ever,
    MAX(j.created_at) AS last_conversion
FROM users u
JOIN subscriptions s ON u.id = s.user_id
LEFT JOIN conversion_jobs j ON u.id = j.user_id
GROUP BY u.id, u.email, u.company, s.plan, s.conversions_used_this_month
ORDER BY s.conversions_used_this_month DESC;

-- =============================================================================
-- DONNÉES INITIALES
-- =============================================================================

-- Compte admin par défaut (mot de passe : à changer en production !)
INSERT INTO users (email, hashed_password, full_name, is_superuser, is_verified)
VALUES (
    'admin@geoconvert.io',
    '$2b$12$placeholder_hash_change_in_production',
    'Admin GeoConvert',
    TRUE,
    TRUE
) ON CONFLICT DO NOTHING;
