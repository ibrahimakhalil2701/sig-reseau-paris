"""
load_ign_wfs.py
Chargement des canalisations BD TOPO IGN (WFS) dans PostGIS
Territoire : Paris intra-muros (BBOX Lambert-93)
Auteur : Ibrahima Khalil Mbacke
"""

import geopandas as gpd
from sqlalchemy import create_engine, text
import requests
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

DB_URL = "postgresql://sig_user:SigParis2024!@localhost:5432/reseau_eau_paris"

# BBOX Paris intra-muros en WGS84 (lat_min, lon_min, lat_max, lon_max)
BBOX_PARIS_WGS84 = "2.2242,48.8155,2.4697,48.9022"

WFS_BASE = "https://data.geopf.fr/wfs/ows"

COUCHES_IGN = {
    "canalisation": {
        "typename": "BDTOPO_V3:canalisation",
        "table_dest": "aep_canalisation_ign",
        "description": "Canalisations BD TOPO Paris"
    }
}

# ─── FONCTIONS ────────────────────────────────────────────────────────────────

def charger_wfs(typename: str, bbox: str) -> gpd.GeoDataFrame:
    """Charger une couche WFS IGN et retourner un GeoDataFrame."""
    url = (
        f"{WFS_BASE}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
        f"&TYPENAMES={typename}"
        f"&BBOX={bbox},urn:ogc:def:crs:EPSG::4326"
        f"&outputFormat=application/json"
        f"&count=5000"
    )
    logger.info(f"Chargement WFS : {typename}")
    logger.info(f"URL : {url}")

    response = requests.get(url, timeout=60)
    response.raise_for_status()

    gdf = gpd.read_file(response.text)
    logger.info(f"Entites chargees : {len(gdf)}")
    return gdf

def reprojeter_lambert93(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reprojeter en Lambert-93 (EPSG:2154)."""
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    if gdf.crs.to_epsg() != 2154:
        gdf = gdf.to_crs(epsg=2154)
        logger.info("Reprojection EPSG:2154 effectuee")
    return gdf


def calculer_longueur(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Calculer la longueur geodesique en metres."""
    gdf_geo = gdf.to_crs(epsg=4326)
    gdf['longueur_m'] = gdf_geo.geometry.to_crs('+proj=cea').length.round(2)
    return gdf


def ecrire_postgis(gdf: gpd.GeoDataFrame, table: str, engine) -> None:
    """Ecrire le GeoDataFrame dans PostGIS."""
    gdf.to_postgis(
        table, engine,
        if_exists='replace',
        index=False,
        chunksize=500
    )
    logger.info(f"Table '{table}' creee dans PostGIS ({len(gdf)} entites)")


def creer_index_spatial(table: str, engine) -> None:
    """Creer l'index spatial GIST."""
    with engine.connect() as conn:
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_geom "
            f"ON {table} USING GIST (geometry)"
        ))
        conn.commit()
    logger.info(f"Index spatial cree sur {table}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=== CHARGEMENT DONNEES IGN BD TOPO → POSTGIS ===")
    engine = create_engine(DB_URL)

    for nom, config in COUCHES_IGN.items():
        try:
            # 1. Charger depuis WFS IGN
            gdf = charger_wfs(config["typename"], BBOX_PARIS_WGS84)
            if gdf.empty:
                logger.warning(f"Aucune donnee pour {nom}")
                continue

            # 2. Reprojeter Lambert-93
            gdf = reprojeter_lambert93(gdf)

            # 3. Calculer longueurs
            if gdf.geometry.geom_type.iloc[0] in ['LineString', 'MultiLineString']:
                gdf = calculer_longueur(gdf)

            # 4. Ecrire dans PostGIS
            ecrire_postgis(gdf, config["table_dest"], engine)

            # 5. Index spatial
            creer_index_spatial(config["table_dest"], engine)

            logger.info(f"[OK] {nom} charge avec succes")

        except Exception as e:
            logger.error(f"[ERREUR] {nom} : {e}")

    logger.info("=== CHARGEMENT TERMINE ===")


if __name__ == "__main__":
    main()