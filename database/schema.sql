-- =============================================
-- SCHEMA BASE DE DONNEES RESEAU EAU PARIS
-- Projet : SIG Full Stack | Ibrahima Khalil Mbacke
-- SRID : 2154 (RGF93 Lambert-93)
-- =============================================

-- Extensions PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ─── RESEAU AEP (EAU POTABLE) ────────────────

CREATE TABLE IF NOT EXISTS aep_canalisation (
    id           SERIAL PRIMARY KEY,
    id_cana      VARCHAR(20) UNIQUE NOT NULL,
    materiau     VARCHAR(10) CHECK (materiau IN ('PVC','PEHD','FON','ACI','AC','INC')),
    diametre_mm  INTEGER CHECK (diametre_mm > 0),
    annee_pose   SMALLINT CHECK (annee_pose BETWEEN 1850 AND 2030),
    pression_bar NUMERIC(5,2),
    etat         VARCHAR(10) CHECK (etat IN ('BON','DEG','HS','INC')) DEFAULT 'INC',
    secteur      VARCHAR(50),
    arrondissement SMALLINT CHECK (arrondissement BETWEEN 1 AND 20),
    source       VARCHAR(20) DEFAULT 'IGN_BDTOPO',
    date_maj     TIMESTAMP DEFAULT NOW(),
    geom         GEOMETRY(LINESTRING, 2154) NOT NULL
);

CREATE TABLE IF NOT EXISTS aep_vanne (
    id           SERIAL PRIMARY KEY,
    id_vanne     VARCHAR(20) UNIQUE NOT NULL,
    type_vanne   VARCHAR(20),
    etat         VARCHAR(10) CHECK (etat IN ('BON','DEG','HS','INC')) DEFAULT 'INC',
    arrondissement SMALLINT,
    date_maj     TIMESTAMP DEFAULT NOW(),
    geom         GEOMETRY(POINT, 2154) NOT NULL
);

CREATE TABLE IF NOT EXISTS aep_compteur (
    id           SERIAL PRIMARY KEY,
    id_compteur  VARCHAR(20) UNIQUE NOT NULL,
    n_abonne     VARCHAR(30),
    index_actuel NUMERIC(10,3),
    date_releve  DATE,
    arrondissement SMALLINT,
    geom         GEOMETRY(POINT, 2154) NOT NULL
);

-- ─── ASSAINISSEMENT ──────────────────────────

CREATE TABLE IF NOT EXISTS ass_collecteur (
    id           SERIAL PRIMARY KEY,
    id_collect   VARCHAR(20) UNIQUE NOT NULL,
    type_eau     VARCHAR(15) CHECK (type_eau IN ('USEE','PLUVIAL','UNITAIRE')),
    diametre_mm  INTEGER,
    pente        NUMERIC(5,3),
    etat         VARCHAR(10) CHECK (etat IN ('BON','DEG','HS','INC')) DEFAULT 'INC',
    arrondissement SMALLINT,
    date_maj     TIMESTAMP DEFAULT NOW(),
    geom         GEOMETRY(LINESTRING, 2154) NOT NULL
);

-- ─── EXPLOITATION ─────────────────────────────

CREATE TABLE IF NOT EXISTS exploitation_incident (
    id               SERIAL PRIMARY KEY,
    ref_incident     VARCHAR(20) UNIQUE,
    type_inc         VARCHAR(30),
    gravite          VARCHAR(10) CHECK (gravite IN ('CRI','MAJ','MIN','INF')),
    statut           VARCHAR(15) DEFAULT 'OUVERT'
                     CHECK (statut IN ('OUVERT','EN_COURS','RESOLU','FERME')),
    description      TEXT,
    date_signalement TIMESTAMP DEFAULT NOW(),
    date_resolution  TIMESTAMP,
    technicien       VARCHAR(50),
    id_cana_lie      INTEGER REFERENCES aep_canalisation(id),
    arrondissement   SMALLINT,
    geom             GEOMETRY(POINT, 2154)
);

-- ─── INDEX SPATIAUX ──────────────────────────

CREATE INDEX IF NOT EXISTS idx_aep_cana_geom     ON aep_canalisation USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_aep_vanne_geom    ON aep_vanne USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_aep_compteur_geom ON aep_compteur USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_ass_collect_geom  ON ass_collecteur USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_incident_geom     ON exploitation_incident USING GIST (geom);

-- ─── INDEX ATTRIBUTAIRES ─────────────────────

CREATE INDEX IF NOT EXISTS idx_aep_cana_etat     ON aep_canalisation (etat);
CREATE INDEX IF NOT EXISTS idx_aep_cana_arrdt    ON aep_canalisation (arrondissement);
CREATE INDEX IF NOT EXISTS idx_incident_statut   ON exploitation_incident (statut);
CREATE INDEX IF NOT EXISTS idx_incident_gravite  ON exploitation_incident (gravite);

-- ─── VUES UTILES ─────────────────────────────

CREATE OR REPLACE VIEW v_bilan_reseau AS
SELECT
    arrondissement,
    COUNT(*) AS nb_troncons,
    ROUND(SUM(ST_Length(geom::geography))::NUMERIC / 1000, 2) AS km_total,
    COUNT(*) FILTER (WHERE etat = 'BON')  AS nb_bon,
    COUNT(*) FILTER (WHERE etat = 'DEG')  AS nb_degrade,
    COUNT(*) FILTER (WHERE etat = 'HS')   AS nb_hors_service
FROM aep_canalisation
GROUP BY arrondissement
ORDER BY arrondissement;

CREATE OR REPLACE VIEW v_incidents_ouverts AS
SELECT
    i.id, i.ref_incident, i.gravite, i.statut,
    i.date_signalement, i.arrondissement,
    c.id_cana, c.materiau, c.diametre_mm
FROM exploitation_incident i
LEFT JOIN aep_canalisation c ON i.id_cana_lie = c.id
WHERE i.statut IN ('OUVERT','EN_COURS')
ORDER BY
    CASE i.gravite WHEN 'CRI' THEN 1 WHEN 'MAJ' THEN 2 WHEN 'MIN' THEN 3 ELSE 4 END,
    i.date_signalement DESC;