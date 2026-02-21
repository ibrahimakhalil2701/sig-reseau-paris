"""
quality_check.py
Controle qualite automatique de la base PostGIS
Auteur : Ibrahima Khalil Mbacke
"""

import geopandas as gpd
from sqlalchemy import create_engine, text
import pandas as pd
from datetime import datetime

DB_URL = "postgresql://sig_user:SigParis2024!@localhost:5432/reseau_eau_paris"

TABLES = {
    "aep_canalisation": {
        "geom_col": "geom",
        "geom_type": "LineString",
        "champs_obligatoires": ["id_cana", "materiau", "etat"],
        "valeurs_valides": {
            "materiau": ["PVC","PEHD","FON","ACI","AC","INC"],
            "etat":     ["BON","DEG","HS","INC"]
        }
    },
    "exploitation_incident": {
        "geom_col": "geom",
        "geom_type": "Point",
        "champs_obligatoires": ["ref_incident","gravite","statut"],
        "valeurs_valides": {
            "gravite": ["CRI","MAJ","MIN","INF"],
            "statut":  ["OUVERT","EN_COURS","RESOLU","FERME"]
        }
    }
}


def check_table(table: str, config: dict, engine) -> list:
    errors = []
    gdf = gpd.read_postgis(
        f"SELECT * FROM {table}",
        engine, geom_col=config["geom_col"]
    )
    print(f"\n[{table}] {len(gdf)} entites chargees")

    # 1. Geometries nulles
    null_geom = gdf[gdf.geometry.isna()]
    if len(null_geom) > 0:
        errors.append(f"{len(null_geom)} geometries nulles")

    # 2. Geometries invalides
    invalid = gdf[~gdf.geometry.is_valid]
    if len(invalid) > 0:
        errors.append(f"{len(invalid)} geometries invalides")

    # 3. Valeurs hors domaine
    for champ, valides in config["valeurs_valides"].items():
        if champ in gdf.columns:
            hors_domaine = gdf[~gdf[champ].isin(valides + [None])]
            if len(hors_domaine) > 0:
                errors.append(f"{len(hors_domaine)} valeurs invalides dans '{champ}'")

    # 4. Champs obligatoires vides
    for champ in config["champs_obligatoires"]:
        if champ in gdf.columns:
            vides = gdf[gdf[champ].isna()]
            if len(vides) > 0:
                errors.append(f"{len(vides)} valeurs nulles dans '{champ}'")

    return errors


def main():
    print(f"\n{'='*50}")
    print(f"CONTROLE QUALITE PostGIS — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    engine = create_engine(DB_URL)
    total_errors = []

    for table, config in TABLES.items():
        errs = check_table(table, config, engine)
        if errs:
            print(f"  ERREURS dans {table}:")
            for e in errs:
                print(f"    ❌ {e}")
            total_errors.extend(errs)
        else:
            print(f"  ✅ {table} — OK")

    print(f"\n{'='*50}")
    if total_errors:
        print(f"RESULTAT : {len(total_errors)} probleme(s) detecte(s)")
    else:
        print("RESULTAT : Base de donnees OK — Aucune erreur")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()