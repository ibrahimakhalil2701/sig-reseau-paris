"""
Générateur de rapport qualité des données géospatiales
Produit un JSON structuré + score de qualité 0-100
"""
import json
from datetime import datetime
from typing import Any

import geopandas as gpd
import numpy as np
from shapely import is_valid


class QualityReporter:
    """
    Génère un rapport qualité complet sur un GeoDataFrame.
    Score global calculé à partir de 5 dimensions :
    - Complétude géométrique (25 pts)
    - Validité géométrique (25 pts)
    - Complétude attributaire (20 pts)
    - Cohérence de projection (15 pts)
    - Qualité des types de données (15 pts)
    """

    def generate(
        self,
        gdf_before: gpd.GeoDataFrame,
        gdf_after: gpd.GeoDataFrame,
        geometry_stats: dict,
        attribute_stats: dict,
        source_epsg: int | None,
        target_epsg: int | None,
        processing_time_s: float,
    ) -> dict:

        report = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "processing_time_seconds": round(processing_time_s, 2),
            "summary": self._build_summary(gdf_before, gdf_after),
            "geometry_quality": self._build_geometry_section(gdf_after, geometry_stats),
            "attribute_quality": self._build_attribute_section(gdf_after, attribute_stats),
            "projection": self._build_projection_section(source_epsg, target_epsg),
            "data_distribution": self._build_distribution_section(gdf_after),
            "quality_score": 0,
            "quality_grade": "F",
            "recommendations": [],
        }

        score, recommendations = self._compute_score(report, geometry_stats)
        report["quality_score"] = score
        report["quality_grade"] = self._score_to_grade(score)
        report["recommendations"] = recommendations

        return report

    # ── Sections ──────────────────────────────────────────────────────────

    def _build_summary(self, gdf_before, gdf_after) -> dict:
        return {
            "features_input": len(gdf_before),
            "features_output": len(gdf_after),
            "features_lost": len(gdf_before) - len(gdf_after),
            "columns_input": len(gdf_before.columns) - 1,   # -1 pour geometry
            "columns_output": len(gdf_after.columns) - 1,
            "geometry_type": self._get_geom_type(gdf_after),
            "bbox": self._get_bbox(gdf_after),
        }

    def _build_geometry_section(self, gdf, stats) -> dict:
        if gdf.empty:
            return {"valid_count": 0, "invalid_count": 0, "validity_rate": 0}
        valid_count = int(gdf.geometry.apply(is_valid).sum())
        total = len(gdf)
        return {
            "total": total,
            "valid_count": valid_count,
            "invalid_count": total - valid_count,
            "validity_rate": round(valid_count / total * 100, 1) if total else 0,
            "null_geometry_count": stats.get("null_geometry", 0),
            "empty_geometry_count": stats.get("empty_after_fix", 0),
            "duplicates_removed": stats.get("duplicates_removed", 0),
            "errors_found": stats.get("invalid_before", 0),
            "errors_fixed": stats.get("fixed", 0),
            "unfixable": stats.get("unfixable", 0),
            "error_sample": stats.get("error_details", [])[:5],
        }

    def _build_attribute_section(self, gdf, stats) -> dict:
        if gdf.empty:
            return {}
        cols = [c for c in gdf.columns if c != "geometry"]
        col_stats = {}
        for col in cols:
            series = gdf[col]
            null_count = int(series.isna().sum())
            col_stats[col] = {
                "dtype": str(series.dtype),
                "null_count": null_count,
                "null_rate": round(null_count / len(gdf) * 100, 1),
                "unique_count": int(series.nunique()),
            }
            if series.dtype in [np.float64, np.int64, np.float32, np.int32]:
                non_null = series.dropna()
                if not non_null.empty:
                    col_stats[col]["min"] = float(non_null.min())
                    col_stats[col]["max"] = float(non_null.max())
                    col_stats[col]["mean"] = round(float(non_null.mean()), 4)

        completeness = sum(
            1 for s in col_stats.values() if s["null_rate"] < 5
        ) / len(cols) * 100 if cols else 100

        return {
            "columns": col_stats,
            "total_columns": len(cols),
            "completeness_rate": round(completeness, 1),
            "columns_renamed": stats.get("columns_renamed", {}),
            "columns_dropped": stats.get("columns_dropped", []),
            "type_conversions": stats.get("type_conversions", {}),
            "null_values_standardized": stats.get("null_values_standardized", 0),
        }

    def _build_projection_section(self, source_epsg, target_epsg) -> dict:
        return {
            "source_epsg": source_epsg,
            "target_epsg": target_epsg,
            "reprojected": source_epsg != target_epsg if (source_epsg and target_epsg) else False,
        }

    def _build_distribution_section(self, gdf) -> dict:
        if gdf.empty:
            return {}
        bbox = self._get_bbox(gdf)
        return {
            "bbox": bbox,
            "area_km2": self._estimate_area_km2(gdf),
            "feature_density": round(len(gdf) / max(
                (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 0.001
            ), 4) if bbox else None,
        }

    # ── Score ─────────────────────────────────────────────────────────────

    def _compute_score(self, report: dict, geometry_stats: dict) -> tuple[int, list]:
        score = 0
        recs = []

        # Complétude géométrique (25 pts)
        geom = report["geometry_quality"]
        null_rate = geom.get("null_geometry_count", 0) / max(geom.get("total", 1), 1) * 100
        score += max(0, 25 - int(null_rate / 4))
        if null_rate > 5:
            recs.append("Attention : {:.1f}% de géométries nulles détectées.".format(null_rate))

        # Validité géométrique (25 pts)
        validity = geom.get("validity_rate", 100)
        score += int(validity / 4)
        if validity < 95:
            recs.append(f"Qualité géométrique : {validity}% valides. Vérifiez la source.")

        # Complétude attributaire (20 pts)
        attr = report["attribute_quality"]
        completeness = attr.get("completeness_rate", 100)
        score += int(completeness / 5)
        if completeness < 80:
            recs.append(f"Complétude attributaire faible : {completeness}%. Données manquantes.")

        # Projection connue (15 pts)
        proj = report["projection"]
        if proj.get("source_epsg"):
            score += 15
        else:
            score += 5
            recs.append("Projection non détectée. Spécifiez l'EPSG source manuellement.")

        # Qualité types (15 pts)
        type_score = 15
        for col_stats in attr.get("columns", {}).values():
            if col_stats["dtype"] == "object" and col_stats["unique_count"] > 50:
                type_score -= 2
        score += max(0, type_score)

        return min(100, max(0, score)), recs

    # ── Utilitaires ───────────────────────────────────────────────────────

    def _score_to_grade(self, score: int) -> str:
        if score >= 90: return "A"
        if score >= 80: return "B"
        if score >= 70: return "C"
        if score >= 60: return "D"
        return "F"

    def _get_geom_type(self, gdf) -> str:
        if gdf.empty or gdf.geometry.isna().all():
            return "Unknown"
        types = gdf.geometry.dropna().geom_type.value_counts()
        return types.index[0] if not types.empty else "Unknown"

    def _get_bbox(self, gdf) -> list | None:
        if gdf.empty or gdf.geometry.isna().all():
            return None
        b = gdf.total_bounds
        return [round(float(x), 6) for x in b]

    def _estimate_area_km2(self, gdf) -> float | None:
        try:
            area = gdf.to_crs(epsg=3857).geometry.union_all().area / 1_000_000
            return round(area, 2)
        except Exception:
            return None
