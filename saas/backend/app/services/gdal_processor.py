"""
Processeur GDAL/OGR central — Conversion entre formats géospatiaux
Formats supportés : GeoJSON, Shapefile, GPKG, KML, DXF, CSV, FileGDB, FlatGeobuf
"""
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import fiona
from osgeo import gdal, ogr

from app.services.projection_detector import ProjectionDetector
from app.services.geometry_cleaner import GeometryCleaner
from app.services.attribute_normalizer import AttributeNormalizer
from app.services.quality_reporter import QualityReporter


# Activer les erreurs GDAL (pas juste des warnings)
gdal.UseExceptions()


class ConversionResult:
    __slots__ = [
        "output_path", "output_format", "feature_count",
        "source_epsg", "target_epsg", "quality_report",
        "geometry_stats", "attribute_stats", "processing_time_s",
    ]

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class GDALProcessor:
    """
    Orchestrateur principal de conversion.
    Pipeline : Lecture → Détection CRS → Nettoyage géom → Normalisation attrs
              → Reprojection → Écriture → Rapport qualité
    """

    # Drivers OGR → extensions de sortie
    FORMAT_CONFIG = {
        "GeoJSON":        {"driver": "GeoJSON",        "ext": ".geojson", "single_file": True},
        "ESRI Shapefile": {"driver": "ESRI Shapefile",  "ext": ".shp",     "single_file": False},
        "GPKG":           {"driver": "GPKG",            "ext": ".gpkg",    "single_file": True},
        "KML":            {"driver": "KML",             "ext": ".kml",     "single_file": True},
        "DXF":            {"driver": "DXF",             "ext": ".dxf",     "single_file": True},
        "CSV":            {"driver": "CSV",             "ext": ".csv",     "single_file": True},
        "OpenFileGDB":    {"driver": "OpenFileGDB",     "ext": ".gdb",     "single_file": False},
        "FlatGeobuf":     {"driver": "FlatGeobuf",      "ext": ".fgb",     "single_file": True},
    }

    def __init__(self):
        self.detector = ProjectionDetector()
        self.cleaner = GeometryCleaner()
        self.normalizer = AttributeNormalizer()
        self.reporter = QualityReporter()

    def process(
        self,
        input_path: str,
        output_format: str,
        target_epsg: Optional[int] = None,
        fix_geometries: bool = True,
        normalize_attributes: bool = True,
        encoding: str = "UTF-8",
        gdal_options: Optional[dict] = None,
    ) -> ConversionResult:
        """
        Exécute le pipeline complet de conversion.
        Retourne un ConversionResult avec le chemin de sortie et le rapport qualité.
        """
        t_start = time.perf_counter()

        # ── Étape 1 : Extraction si ZIP ───────────────────────────────────
        work_path = self._extract_if_zip(input_path)

        # ── Étape 2 : Détection projection source ─────────────────────────
        detection = self.detector.detect(work_path)
        source_epsg = detection["epsg"]

        # ── Étape 3 : Lecture avec Geopandas/Fiona ────────────────────────
        gdf = self._read_file(work_path, encoding)
        gdf_before = gdf.copy()

        # ── Étape 4 : Nettoyage géométrique ───────────────────────────────
        geometry_stats = {}
        if fix_geometries:
            gdf, geometry_stats = self.cleaner.clean(gdf)

        # ── Étape 5 : Normalisation attributs ─────────────────────────────
        attribute_stats = {}
        if normalize_attributes:
            gdf, attribute_stats = self.normalizer.normalize(gdf, output_format)

        # ── Étape 6 : Reprojection ────────────────────────────────────────
        effective_target_epsg = target_epsg
        if target_epsg and source_epsg and target_epsg != source_epsg:
            gdf = self.detector.reproject_geodataframe(gdf, source_epsg, target_epsg)
        elif source_epsg and not target_epsg:
            if gdf.crs is None:
                gdf = gdf.set_crs(epsg=source_epsg, allow_override=True)
            effective_target_epsg = source_epsg

        # ── Étape 7 : Écriture dans le format cible ───────────────────────
        output_path = self._write_file(gdf, output_format, encoding, gdal_options or {})

        # ── Étape 8 : Packaging ZIP si multi-fichiers (Shapefile, GDB) ────
        final_path = self._package_if_needed(output_path, output_format)

        t_end = time.perf_counter()
        processing_time = t_end - t_start

        # ── Étape 9 : Rapport qualité ─────────────────────────────────────
        quality_report = self.reporter.generate(
            gdf_before=gdf_before,
            gdf_after=gdf,
            geometry_stats=geometry_stats,
            attribute_stats=attribute_stats,
            source_epsg=source_epsg,
            target_epsg=effective_target_epsg,
            processing_time_s=processing_time,
        )

        return ConversionResult(
            output_path=final_path,
            output_format=output_format,
            feature_count=len(gdf),
            source_epsg=source_epsg,
            target_epsg=effective_target_epsg,
            quality_report=quality_report,
            geometry_stats=geometry_stats,
            attribute_stats=attribute_stats,
            processing_time_s=round(processing_time, 2),
        )

    # ── Méthodes privées ──────────────────────────────────────────────────

    def _extract_if_zip(self, path: str) -> str:
        """Extrait un ZIP et retourne le chemin du fichier principal."""
        if not path.lower().endswith(".zip"):
            return path
        extract_dir = tempfile.mkdtemp(prefix="geoconvert_")
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(extract_dir)
        # Cherche le fichier principal dans l'archive
        for ext in [".shp", ".gpkg", ".geojson", ".kml", ".gdb", ".dxf", ".csv"]:
            matches = list(Path(extract_dir).rglob(f"*{ext}"))
            if matches:
                return str(matches[0])
        raise ValueError("Aucun fichier géospatial reconnu dans l'archive ZIP.")

    def _read_file(self, path: str, encoding: str = "UTF-8") -> gpd.GeoDataFrame:
        """Lecture robuste avec fallback encodage."""
        try:
            return gpd.read_file(path, encoding=encoding)
        except Exception:
            # Fallback latin-1
            return gpd.read_file(path, encoding="latin-1")

    def _write_file(
        self,
        gdf: gpd.GeoDataFrame,
        output_format: str,
        encoding: str,
        gdal_options: dict,
    ) -> str:
        config = self.FORMAT_CONFIG.get(output_format)
        if not config:
            raise ValueError(f"Format de sortie non supporté : {output_format}")

        output_path = tempfile.mktemp(prefix="geoconvert_out_", suffix=config["ext"])

        write_kwargs = {
            "driver": config["driver"],
            "encoding": encoding,
        }

        # Options spécifiques par format
        if output_format == "KML":
            write_kwargs["engine"] = "fiona"
        elif output_format == "CSV":
            write_kwargs.pop("driver", None)
            gdf["latitude"] = gdf.geometry.centroid.y
            gdf["longitude"] = gdf.geometry.centroid.x

        gdf.to_file(output_path, **write_kwargs)
        return output_path

    def _package_if_needed(self, output_path: str, output_format: str) -> str:
        """
        Shapefile et FileGDB génèrent plusieurs fichiers.
        On les zippe pour un seul téléchargement.
        """
        config = self.FORMAT_CONFIG.get(output_format, {})
        if config.get("single_file", True):
            return output_path

        zip_path = output_path.replace(config["ext"], ".zip")
        base = Path(output_path).stem
        parent = Path(output_path).parent

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if output_format == "ESRI Shapefile":
                for f in parent.glob(f"{Path(output_path).stem}.*"):
                    zf.write(f, f.name)
            elif output_format == "OpenFileGDB":
                for f in Path(output_path).rglob("*"):
                    zf.write(f, f.relative_to(parent))

        return zip_path

    @staticmethod
    def list_supported_formats() -> dict:
        """Liste les formats disponibles avec leurs capacités."""
        return {
            fmt: {
                "driver": cfg["driver"],
                "extension": cfg["ext"],
                "multi_file": not cfg["single_file"],
            }
            for fmt, cfg in GDALProcessor.FORMAT_CONFIG.items()
        }
