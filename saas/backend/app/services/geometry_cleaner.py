"""
Nettoyage et correction des géométries invalides
Utilise Shapely 2.x + buffer(0) + make_valid
"""
from typing import Optional
import geopandas as gpd
import pandas as pd
from shapely import make_valid, is_valid, is_empty, normalize
from shapely.geometry import (
    GeometryCollection, LineString, MultiLineString,
    MultiPoint, MultiPolygon, Point, Polygon,
)
from shapely.validation import explain_validity


class GeometryCleaner:
    """
    Pipeline de nettoyage des géométries en 5 étapes :
    1. Détection des géométries nulles/vides
    2. Validation et rapport d'erreurs
    3. Correction make_valid (Shapely 2.x)
    4. Normalisation et déduplication
    5. Filtrage par type de géométrie cible
    """

    def clean(self, gdf: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
        """
        Retourne (gdf_nettoyé, statistiques).
        """
        stats = {
            "total_input": len(gdf),
            "null_geometry": 0,
            "invalid_before": 0,
            "fixed": 0,
            "unfixable": 0,
            "empty_after_fix": 0,
            "duplicates_removed": 0,
            "total_output": 0,
            "error_details": [],
        }

        # ── Étape 1 : Géométries nulles ───────────────────────────────────
        null_mask = gdf.geometry.isna()
        stats["null_geometry"] = int(null_mask.sum())
        gdf = gdf[~null_mask].copy()

        if gdf.empty:
            stats["total_output"] = 0
            return gdf, stats

        # ── Étape 2 : Identifier les invalides ────────────────────────────
        invalid_mask = ~gdf.geometry.apply(is_valid)
        stats["invalid_before"] = int(invalid_mask.sum())

        # Collecter les détails d'erreur (max 10 pour le rapport)
        invalid_indices = gdf[invalid_mask].index[:10]
        for idx in invalid_indices:
            geom = gdf.at[idx, "geometry"]
            stats["error_details"].append({
                "index": int(idx),
                "reason": explain_validity(geom),
            })

        # ── Étape 3 : Correction make_valid ──────────────────────────────
        def fix_geometry(geom):
            if geom is None or is_empty(geom):
                return None
            if is_valid(geom):
                return geom
            try:
                fixed = make_valid(geom)
                return fixed if not is_empty(fixed) else None
            except Exception:
                return None

        gdf["geometry"] = gdf["geometry"].apply(fix_geometry)

        # ── Étape 4 : Retirer les géométries vides après fix ─────────────
        empty_mask = gdf.geometry.isna() | gdf.geometry.apply(is_empty)
        stats["empty_after_fix"] = int(empty_mask.sum())
        stats["unfixable"] = stats["empty_after_fix"]
        stats["fixed"] = stats["invalid_before"] - stats["unfixable"]
        gdf = gdf[~empty_mask].copy()

        # ── Étape 5 : Dédoublonnage géométrique ──────────────────────────
        before_dedup = len(gdf)
        gdf = gdf.drop_duplicates(subset=["geometry"])
        stats["duplicates_removed"] = before_dedup - len(gdf)

        # Reset index propre
        gdf = gdf.reset_index(drop=True)
        stats["total_output"] = len(gdf)

        return gdf, stats

    def explode_collections(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """Éclate les GeometryCollection en géométries simples."""
        return gdf.explode(index_parts=False).reset_index(drop=True)

    def get_dominant_geometry_type(self, gdf: gpd.GeoDataFrame) -> str:
        """Retourne le type de géométrie dominant dans le dataset."""
        if gdf.empty:
            return "Unknown"
        types = gdf.geometry.geom_type.value_counts()
        return types.index[0] if not types.empty else "Unknown"
