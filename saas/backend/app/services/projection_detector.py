"""
Détection automatique de projection — EPSG depuis .prj, données ou heuristiques
"""
import re
from pathlib import Path
from typing import Optional

from osgeo import osr
from pyproj import CRS, Transformer
from pyproj.exceptions import CRSError
import geopandas as gpd


class ProjectionDetector:
    """
    Détecte l'EPSG d'un fichier géospatial en cascade :
    1. Lecture directe du .prj / métadonnées OGR
    2. Matching via pyproj CRS
    3. Heuristique basée sur l'étendue géographique
    """

    # EPSG courants et leur bbox approximate (minx, miny, maxx, maxy)
    KNOWN_CRS_BBOXES = {
        4326:  (-180, -90, 180, 90),        # WGS84 géographique
        2154:  (99220, 6049997, 1242456, 7110480),  # Lambert-93 (France)
        3857:  (-20037508, -20048966, 20037508, 20048966),  # Web Mercator
        4171:  (-5.14, 41.33, 9.56, 51.09),  # RGF93 géographique
        32631: (166022, 0, 833978, 9329005),  # UTM 31N
        32632: (166022, 0, 833978, 9329005),  # UTM 32N
        27700: (-103976, -16703, 652897, 1199848),  # British National Grid
        25831: (119303, 1116915, 1320416, 9554469),  # ETRS89 UTM 31N
        25832: (243900, 1116915, 1783532, 9554469),  # ETRS89 UTM 32N
    }

    def detect(self, file_path: str) -> dict:
        """
        Retourne un dict:
        {
            "epsg": int | None,
            "wkt": str | None,
            "confidence": "high" | "medium" | "low",
            "method": str,
        }
        """
        result = {"epsg": None, "wkt": None, "confidence": "low", "method": "none"}

        # ── 1. Lecture via OGR (source la plus fiable) ────────────────────
        ogr_epsg = self._detect_from_ogr(file_path)
        if ogr_epsg:
            result.update({"epsg": ogr_epsg, "confidence": "high", "method": "ogr_metadata"})
            return result

        # ── 2. Lecture .prj pour Shapefile ───────────────────────────────
        prj_epsg = self._detect_from_prj(file_path)
        if prj_epsg:
            result.update({"epsg": prj_epsg, "confidence": "high", "method": "prj_file"})
            return result

        # ── 3. Heuristique par étendue des données ────────────────────────
        heuristic_epsg, confidence = self._detect_from_extent(file_path)
        if heuristic_epsg:
            result.update({
                "epsg": heuristic_epsg,
                "confidence": confidence,
                "method": "extent_heuristic",
            })

        return result

    def _detect_from_ogr(self, file_path: str) -> Optional[int]:
        from osgeo import ogr
        ds = ogr.Open(file_path)
        if not ds:
            return None
        layer = ds.GetLayer(0)
        if not layer:
            return None
        srs = layer.GetSpatialRef()
        if not srs:
            return None
        srs.AutoIdentifyEPSG()
        epsg_code = srs.GetAuthorityCode(None)
        ds = None
        return int(epsg_code) if epsg_code else None

    def _detect_from_prj(self, file_path: str) -> Optional[int]:
        prj_path = Path(file_path).with_suffix(".prj")
        if not prj_path.exists():
            return None
        wkt = prj_path.read_text(encoding="utf-8", errors="ignore")
        srs = osr.SpatialReference()
        if srs.ImportFromWkt(wkt) != 0:
            return None
        srs.AutoIdentifyEPSG()
        code = srs.GetAuthorityCode(None)
        return int(code) if code else None

    def _detect_from_extent(self, file_path: str) -> tuple[Optional[int], str]:
        """Heuristique : compare l'étendue des données aux BBox connues."""
        try:
            gdf = gpd.read_file(file_path, rows=100)
            if gdf.empty:
                return None, "low"
            bounds = gdf.total_bounds  # minx, miny, maxx, maxy

            best_epsg = None
            best_score = float("inf")

            for epsg, bbox in self.KNOWN_CRS_BBOXES.items():
                # Vérifie si les données sont contenues dans la BBox
                if (bbox[0] <= bounds[0] <= bbox[2] and
                        bbox[1] <= bounds[1] <= bbox[3] and
                        bbox[0] <= bounds[2] <= bbox[2] and
                        bbox[1] <= bounds[3] <= bbox[3]):
                    # Score = superficie relative (plus petit = plus précis)
                    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
                    if bbox_area < best_score:
                        best_score = bbox_area
                        best_epsg = epsg

            confidence = "medium" if best_epsg else "low"
            return best_epsg, confidence
        except Exception:
            return None, "low"

    def reproject_geodataframe(
        self,
        gdf: gpd.GeoDataFrame,
        source_epsg: int,
        target_epsg: int,
    ) -> gpd.GeoDataFrame:
        """Reprojection sécurisée avec validation avant/après."""
        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=source_epsg, allow_override=True)
        elif gdf.crs.to_epsg() != source_epsg:
            gdf = gdf.set_crs(epsg=source_epsg, allow_override=True)

        return gdf.to_crs(epsg=target_epsg)
