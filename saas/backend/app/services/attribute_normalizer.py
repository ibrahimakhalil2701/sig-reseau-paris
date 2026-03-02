"""
Normalisation des attributs — Nettoyage, encodage, standardisation
"""
import re
import unicodedata
from typing import Optional

import pandas as pd
import geopandas as gpd


class AttributeNormalizer:
    """
    Pipeline de normalisation des attributs en 6 étapes :
    1. Nettoyage des noms de colonnes (snake_case, ASCII, longueur)
    2. Détection et suppression des colonnes fantômes
    3. Conversion des types (str→float, str→datetime)
    4. Nettoyage des valeurs texte (strip, encodage)
    5. Standardisation des valeurs nulles
    6. Troncature des noms DBF (10 chars max pour Shapefile)
    """

    # Colonnes généralement inutiles générées par QGIS/ArcGIS
    GHOST_COLUMNS = {"fid", "objectid", "shape_area", "shape_length", "shape_leng"}

    def normalize(
        self,
        gdf: gpd.GeoDataFrame,
        target_format: str = "GeoJSON",
        drop_ghost_cols: bool = True,
    ) -> tuple[gpd.GeoDataFrame, dict]:
        stats = {
            "columns_renamed": {},
            "columns_dropped": [],
            "type_conversions": {},
            "null_values_standardized": 0,
        }

        gdf = gdf.copy()

        # ── 1. Nettoyage des noms de colonnes ────────────────────────────
        rename_map = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            clean = self._clean_column_name(col, target_format)
            if clean != col:
                rename_map[col] = clean

        # Déduplication des noms après nettoyage
        seen = {}
        final_rename = {}
        for old, new in rename_map.items():
            if new in seen:
                seen[new] += 1
                new = f"{new}_{seen[new]}"
            else:
                seen[new] = 0
            final_rename[old] = new

        if final_rename:
            gdf = gdf.rename(columns=final_rename)
            stats["columns_renamed"] = final_rename

        # ── 2. Suppression colonnes fantômes ─────────────────────────────
        if drop_ghost_cols:
            cols_to_drop = [
                c for c in gdf.columns
                if c.lower() in self.GHOST_COLUMNS and c != "geometry"
            ]
            if cols_to_drop:
                gdf = gdf.drop(columns=cols_to_drop)
                stats["columns_dropped"] = cols_to_drop

        # ── 3. Conversion de types ────────────────────────────────────────
        for col in gdf.columns:
            if col == "geometry":
                continue
            converted, new_dtype = self._try_convert_type(gdf[col])
            if new_dtype:
                gdf[col] = converted
                stats["type_conversions"][col] = new_dtype

        # ── 4. Nettoyage des valeurs texte ───────────────────────────────
        for col in gdf.select_dtypes(include=["object"]).columns:
            if col == "geometry":
                continue
            gdf[col] = gdf[col].apply(self._clean_text_value)

        # ── 5. Standardisation des nulls ──────────────────────────────────
        null_indicators = {"", "null", "none", "n/a", "na", "#n/a", "nan", "-", "--"}
        null_count = 0
        for col in gdf.columns:
            if col == "geometry":
                continue
            if gdf[col].dtype == object:
                mask = gdf[col].str.strip().str.lower().isin(null_indicators)
                null_count += mask.sum()
                gdf.loc[mask, col] = None
        stats["null_values_standardized"] = int(null_count)

        return gdf, stats

    def _clean_column_name(self, name: str, target_format: str) -> str:
        # Translittération unicode → ASCII
        name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        # Minuscules, espaces → underscore
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())
        # Supprimer les underscores multiples
        name = re.sub(r"_+", "_", name).strip("_")
        # Préfixe si commence par chiffre
        if name and name[0].isdigit():
            name = f"col_{name}"
        # Troncature pour Shapefile DBF (10 chars max)
        if target_format == "ESRI Shapefile":
            name = name[:10]
        return name or "col"

    def _try_convert_type(self, series: pd.Series) -> tuple[pd.Series, Optional[str]]:
        if series.dtype != object:
            return series, None
        # Tentative conversion numérique
        try:
            numeric = pd.to_numeric(series, errors="raise")
            return numeric, "numeric"
        except (ValueError, TypeError):
            pass
        # Tentative conversion datetime
        non_null = series.dropna()
        if not non_null.empty and non_null.str.match(
            r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}:\d{2})?$"
        ).all():
            try:
                return pd.to_datetime(series, errors="raise"), "datetime"
            except (ValueError, TypeError):
                pass
        return series, None

    def _clean_text_value(self, value) -> Optional[str]:
        if pd.isna(value) or value is None:
            return None
        s = str(value).strip()
        # Supprimer caractères de contrôle
        s = "".join(c for c in s if not unicodedata.category(c).startswith("C"))
        return s if s else None
