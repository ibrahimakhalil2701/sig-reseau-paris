# GeoConvert SaaS — Architecture Technique Complète

> Plateforme de conversion intelligente de fichiers géospatiaux
> Stack : Python · FastAPI · GDAL · PostGIS · Celery · Redis · MinIO · Docker

---

## 1. Vue d'ensemble de l'architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        UTILISATEUR FINAL                             │
│          Navigateur Web / Client API (Python SDK, cURL)             │
└─────────────────────────┬───────────────────────────────────────────┘
                          │ HTTPS
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    COUCHE RÉSEAU / CDN                               │
│   Cloudflare CDN → Nginx reverse-proxy → Rate limiting / WAF        │
└─────────────────────────┬───────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
   ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
   │  API        │ │  Frontend   │ │  Flower      │
   │  FastAPI    │ │  React/Next │ │  (monitoring)│
   │  :8000      │ │  :3000      │ │  :5555       │
   └──────┬──────┘ └─────────────┘ └──────────────┘
          │
   ┌──────┴──────────────────────────────────────┐
   │           BUS DE MESSAGES                    │
   │           Redis :6379                        │
   │   Broker Celery + Cache sessions             │
   └──────┬──────────────────────────────────────┘
          │
   ┌──────┴──────────────────────────────────────┐
   │         WORKERS GÉOSPATIAUX                  │
   │         Celery Workers (x2-N)                │
   │   GDAL · Shapely · GeoPandas · PyProj        │
   └──────┬──────────────────────────────────────┘
          │
   ┌──────┴──────────┬───────────────────────────┐
   ▼                 ▼                            ▼
┌──────────┐  ┌──────────────┐           ┌──────────────┐
│ PostGIS  │  │  MinIO/S3    │           │  Sentry      │
│ :5432    │  │  :9000       │           │  (erreurs)   │
│ Metadata │  │  Fichiers    │           └──────────────┘
│ Jobs/    │  │  Upload/     │
│ Users    │  │  Outputs     │
└──────────┘  └──────────────┘
```

---

## 2. Architecture technique détaillée

### 2.1 Backend — FastAPI (Python 3.12)

| Composant | Technologie | Rôle |
|-----------|-------------|------|
| Framework | FastAPI 0.111 | API REST async, documentation OpenAPI auto |
| Serveur | Uvicorn + Gunicorn | 4 workers ASGI, production-ready |
| Auth | JWT (python-jose) + bcrypt | Tokens access 60min / refresh 30j |
| Validation | Pydantic v2 | Validation stricte des inputs |
| ORM | SQLAlchemy 2.0 async | Requêtes non-bloquantes |
| Migrations | Alembic | Versionning du schéma DB |

**Structure du projet :**
```
saas/backend/app/
├── main.py                    # Entrée FastAPI + middlewares
├── config.py                  # Settings centralisés (pydantic-settings)
├── models/
│   ├── user.py               # User, Subscription, ApiKey
│   └── conversion.py         # ConversionJob
├── api/v1/
│   ├── auth.py               # /register, /login, /refresh, /me
│   ├── upload.py             # POST /upload (multipart)
│   ├── convert.py            # POST /convert, GET /{id}/status
│   └── download.py           # GET /download/{id}
├── services/
│   ├── gdal_processor.py     # Orchestrateur pipeline GDAL
│   ├── projection_detector.py # Détection EPSG automatique
│   ├── geometry_cleaner.py   # Correction géométries (Shapely 2.x)
│   ├── attribute_normalizer.py # Nettoyage attributs
│   └── quality_reporter.py   # Rapport qualité + score 0-100
├── core/
│   ├── database.py           # Engine async SQLAlchemy
│   ├── security.py           # JWT, bcrypt, API keys, magic bytes
│   ├── storage.py            # Abstraction Local/S3/MinIO
│   └── celery_app.py         # Configuration Celery
└── workers/
    └── conversion_tasks.py   # Tasks Celery async
```

### 2.2 Pipeline de conversion (GDALProcessor)

```
Fichier uploadé (ZIP/SHP/GeoJSON/GPKG/KML/DXF/CSV)
    │
    ▼ _extract_if_zip()
    │  ↳ Extraction automatique des archives ZIP
    │
    ▼ ProjectionDetector.detect()
    │  ↳ 1. Métadonnées OGR (haute confiance)
    │  ↳ 2. Lecture fichier .prj (haute confiance)
    │  ↳ 3. Heuristique étendue géographique (moyenne confiance)
    │
    ▼ GeometryCleaner.clean()
    │  ↳ 1. Suppression géométries nulles
    │  ↳ 2. Identification invalides (explain_validity)
    │  ↳ 3. Correction make_valid() (Shapely 2.x)
    │  ↳ 4. Suppression géométries vides post-correction
    │  ↳ 5. Déduplication géométrique
    │
    ▼ AttributeNormalizer.normalize()
    │  ↳ 1. Nettoyage noms colonnes → snake_case ASCII
    │  ↳ 2. Troncature DBF (10 chars pour Shapefile)
    │  ↳ 3. Suppression colonnes fantômes (FID, OBJECTID…)
    │  ↳ 4. Conversion types (str→numeric, str→datetime)
    │  ↳ 5. Nettoyage valeurs texte (strip, caractères contrôle)
    │  ↳ 6. Standardisation nulls (NULL/N/A/- → None)
    │
    ▼ ProjectionDetector.reproject_geodataframe()
    │  ↳ Reprojection EPSG source → EPSG cible (si demandé)
    │
    ▼ _write_file()
    │  ↳ Écriture GDAL dans le format cible
    │  ↳ ZIP automatique pour Shapefile (multi-fichiers)
    │
    ▼ QualityReporter.generate()
       ↳ Score 0-100 sur 5 dimensions
       ↳ Rapport JSON complet
       ↳ Recommandations textuelles
```

### 2.3 Base de données — PostgreSQL 15 + PostGIS 3.4

**Tables principales :**

```sql
users           -- Comptes utilisateurs
subscriptions   -- Plan + quotas + Stripe IDs
api_keys        -- Clés API (hash SHA-256 uniquement stocké)
conversion_jobs -- Jobs avec statut, rapport qualité (JSONB)
usage_events    -- Analytics partitionnées par mois
```

**Optimisations :**
- Index GIN sur `quality_report` (JSONB) pour filtrage analytics
- Index partiel sur `download_expires_at WHERE status='success'`
- Partitionnement par mois sur `usage_events`
- Pool PostgreSQL : 200 connexions max, shared_buffers 512MB

### 2.4 File d'attente — Celery + Redis

```
Queue "conversion"   → Workers géospatiaux (2 instances, 4G RAM chacun)
Queue "maintenance"  → Celery Beat (cleanup fichiers expirés, reset quotas)

Retry policy:
  - 2 retries max sur erreurs réseau/transitoires
  - Soft time limit: 600s (10 min)
  - Hard time limit: 630s
  - max-tasks-per-child: 50 (évite fuites mémoire GDAL)
```

### 2.5 Stockage — MinIO (S3-compatible)

```
Bucket: geoconvert-uploads/   → Fichiers sources (rétention 48h)
Bucket: geoconvert-outputs/   → Fichiers convertis (rétention 24h)

URL signées: expires_in=3600s (1h)
Cleanup: Celery Beat toutes les heures
```

---

## 3. Sécurité

### 3.1 Upload sécurisé

```python
# 1. Validation extension (whitelist)
ALLOWED_EXTENSIONS = {shp, geojson, gpkg, kml, dxf, csv, zip, gpx, fgb}

# 2. Validation magic bytes (anti-spoofing)
MAGIC_BYTES = {
    "zip":   b"PK\x03\x04",
    "gpkg":  b"SQLite format 3",
    "kml":   b"<?xml",
}

# 3. Limite taille par plan
Free/Starter : 100 Mo
Pro          : 2 Go
Enterprise   : 20 Go

# 4. Nom fichier sanitisé (uuid4 + nom original)
safe_filename = f"{uuid.uuid4().hex}_{Path(filename).name}"

# 5. Isolation par utilisateur
storage_path = f"uploads/{user_id}/{uuid}/{filename}"
```

### 3.2 Authentification

```
JWT Access Token  : 60 minutes, HS256, payload {sub, exp, type}
JWT Refresh Token : 30 jours
API Keys          : SHA-256 stocké uniquement (pas la clé complète)
Préfixe API Key   : "gc_live_" (identifiable dans les logs)
```

### 3.3 Middlewares de sécurité

```python
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
CORS: whitelist explicite des origines
Rate limiting: Nginx (100 req/min par IP sur /api/upload)
```

---

## 4. Modèle économique SaaS

### 4.1 Plans et Tarification

| Plan | Prix | Conversions/mois | Taille max | Formats | Support |
|------|------|-----------------|------------|---------|---------|
| **Free** | 0€ | 5 | 100 Mo | Tous | Community |
| **Starter** | 29€/mois | 100 | 100 Mo | Tous | Email 48h |
| **Pro** | 99€/mois | 1 000 | 2 Go | Tous + API | Email 24h |
| **Enterprise** | Sur devis | Illimité | 20 Go | Tous + API + SLA | Dédié |

### 4.2 Features différenciantes par plan

```
Free      → Web UI uniquement, watermark rapport qualité
Starter   → Web UI, pas de watermark, historique 30j
Pro       → API REST, webhooks, batch upload (ZIP multi-fichiers)
Enterprise → On-premise possible, SSO/SAML, SLA 99.9%, quota custom
```

### 4.3 Mécanisme d'upgrade (Stripe)

```
1. Utilisateur clique "Upgrade" → POST /api/v1/billing/checkout
2. Création Stripe Checkout Session
3. Redirect vers Stripe Hosted Page
4. Webhook Stripe → POST /api/v1/billing/webhook
5. Mise à jour subscription.plan en base
6. Email de confirmation (SendGrid)
```

### 4.4 Projections financières (conservatrice)

| Mois | Free | Starter | Pro | Enterprise | MRR |
|------|------|---------|-----|------------|-----|
| M3  | 500 | 20 | 5 | 0 | 1 075€ |
| M6  | 2000 | 80 | 25 | 1 | 5 395€ |
| M12 | 8000 | 300 | 100 | 5 | 20 695€ |
| M18 | 20000 | 800 | 350 | 15 | 62 150€ |

---

## 5. MVP 30 jours — Roadmap détaillée

### Semaine 1 (J1–J7) : Infrastructure de base
```
☑ Setup repository Git + CI/CD GitHub Actions
☑ Docker Compose : PostGIS + Redis + MinIO + API
☑ Schema PostgreSQL + migrations Alembic
☑ Endpoints Auth : /register, /login, /refresh, /me
☑ Upload sécurisé + validation magic bytes
☑ Tests unitaires Auth (pytest + httpx)
```

### Semaine 2 (J8–J14) : Core géospatial
```
☑ GDALProcessor : lecture multi-formats
☑ ProjectionDetector : cascade OGR → PRJ → heuristique
☑ GeometryCleaner : make_valid Shapely 2.x
☑ AttributeNormalizer : snake_case, types, nulls
☑ Conversion : GeoJSON ↔ Shapefile ↔ GPKG ↔ KML
☑ Tests d'intégration avec fichiers réels (BDTopo, OpenStreetMap)
```

### Semaine 3 (J15–J21) : Async + Rapport
```
☑ Celery workers + Redis broker
☑ Endpoint POST /convert → job async
☑ Polling statut GET /{id}/status
☑ QualityReporter : score 0-100, 5 dimensions
☑ Download sécurisé : URL signées MinIO
☑ Cleanup automatique (Celery Beat 24h)
```

### Semaine 4 (J22–J30) : Monétisation + Deploy
```
☑ Intégration Stripe : plans, webhook, upgrade
☑ Système de quotas (vérification avant chaque job)
☑ Monitoring : Sentry (erreurs) + Flower (workers)
☑ Deploy sur VPS (Hetzner CX21 ou Scaleway DEV1-M)
☑ Domaine + SSL Let's Encrypt (Traefik)
☑ Landing page minimaliste (Next.js ou Astro)
```

**Budget infrastructure MVP :**
```
VPS API (4 vCPU, 8GB) : 20€/mois
VPS Worker (4 vCPU, 8GB) : 20€/mois
Object Storage 100GB   : 5€/mois
Domain + SSL           : 15€/an
Total                  : ~47€/mois
```

---

## 6. Roadmap produit 6 mois

### M1–M2 : MVP et Validation
- Core conversion (7 formats)
- Authentification JWT
- Plans Free/Starter
- Landing page + onboarding email

### M3 : API et Intégrations
- API REST complète documentée (OpenAPI)
- SDK Python officiel (`pip install geoconvert`)
- Webhooks (notification fin de conversion)
- Plan Pro + API Keys

### M4 : Batch et Performance
- Upload par lot (ZIP multi-fichiers)
- File d'attente prioritaire pour Pro/Enterprise
- Conversion DXF/DWG avancée (couches, blocs)
- Cache résultats (même fichier → même hash → pas re-conversion)

### M5 : Analytics et Collaboration
- Dashboard utilisateur : historique, graphiques, rapport qualité
- Export rapport qualité PDF
- Partage de jobs entre membres d'une organisation
- Dashboard admin : métriques business

### M6 : Entreprise et Écosystème
- Plugin QGIS officiel (PyQGIS)
- Intégration ArcGIS Online
- On-premise Docker (Enterprise)
- SSO/SAML (Okta, Azure AD)
- API de validation INSPIRE (conformité directive européenne)

---

## 7. Stratégie de différenciation vs QGIS / FME

### 7.1 Problèmes des outils existants

| Outil | Problème |
|-------|----------|
| **QGIS** | Interface desktop, installation requise, pas d'API, pas de rapport qualité automatique |
| **FME** | 3 000-5 000€/licence, complexe, sur-ingénierie pour conversions simples |
| **ogr2ogr CLI** | Technique, pas d'interface, pas de correction auto, pas de rapport |
| **MyGeodata** | Pas de correction géométrique, rapport basique, quota faible Free |

### 7.2 Avantages compétitifs

```
✓ Zéro installation — 100% web, API REST
✓ Rapport qualité unique — score 0-100, recommandations textuelles
✓ Correction automatique — make_valid() sans intervention utilisateur
✓ Détection projection — plus besoin de connaître l'EPSG source
✓ Tarification usage — pay-per-conversion possible
✓ API Python-native — intégration dans pipelines ETL existants
✓ Open Core — couche géospatiale open-source, plateforme SaaS propriétaire
```

### 7.3 Positionnement marché

```
GeoConvert = "Cloudflare pour les données géospatiales"
→ Simple à utiliser pour le non-technicien (Web UI)
→ Puissant pour le développeur (API + SDK)
→ Pas de compromis sur la qualité (GDAL en backend)
```

### 7.4 Canaux d'acquisition

```
SEO/Content  : "convertir shapefile geojson", "reproject EPSG 2154 4326"
Communauté   : OSGeo, GIS Stack Exchange, Reddit r/gis
Intégrations : Plugin QGIS (visibilité massive), Plugin JOSM
Partnerships : IGN, collectivités territoriales, ESN SIG
Product-led  : Free tier généreux (5 conversions/mois gratuit)
```

---

## 8. Commandes de démarrage rapide

```bash
# 1. Démarrer la stack complète
cd saas/
docker compose up -d

# 2. Vérifier l'état des services
docker compose ps
curl http://localhost:8000/api/health

# 3. Accès interfaces
# API docs   : http://localhost:8000/api/docs
# Flower     : http://localhost:5555 (admin/FlowerPwd2024!)
# MinIO      : http://localhost:9001 (minio_admin/MinioPass2024!)

# 4. Test inscription + conversion
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"Test1234!","full_name":"Test"}'

# 5. Upload d'un fichier (avec TOKEN obtenu au login)
curl -X POST http://localhost:8000/api/v1/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@mon_fichier.geojson"

# 6. Lancer une conversion
curl -X POST http://localhost:8000/api/v1/convert \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"storage_path":"...", "original_filename":"mon_fichier.geojson",
       "output_format":"GPKG", "target_epsg":2154}'

# 7. Récupérer le statut
curl http://localhost:8000/api/v1/convert/$JOB_ID/status \
  -H "Authorization: Bearer $TOKEN"
```

---

*Architecture conçue par Ibrahima Khalil Mbacke — Mars 2026*
