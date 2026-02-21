"""
generate_synthetic_data.py
Génération de données synthétiques réseau AEP Paris
Auteur : Ibrahima Khalil Mbacke
"""
import geopandas as gpd
from shapely.geometry import LineString
from sqlalchemy import create_engine
import random

random.seed(42)

DB_URL = "postgresql://sig_user:SigParis2024!@localhost:5432/reseau_eau_paris"

rues_paris = [
    ("Rue de Rivoli",        1, [(651800,6862100),(652000,6862120),(652200,6862140),(652400,6862160)]),
    ("Boulevard Haussmann",  8, [(651400,6862300),(651600,6862280),(651800,6862260),(652000,6862240)]),
    ("Rue Saint-Antoine",    4, [(652100,6861950),(652300,6861970),(652500,6861990)]),
    ("Boulevard Saint-Germain", 6, [(651700,6861750),(651900,6861730),(652100,6861710)]),
    ("Avenue des Champs-Elysées", 8, [(651200,6862200),(651400,6862220),(651600,6862240)]),
    ("Rue de Vaugirard",    15, [(650800,6861500),(651000,6861520),(651200,6861540)]),
    ("Boulevard Voltaire",  11, [(652600,6862000),(652800,6862020),(653000,6862040)]),
    ("Rue du Faubourg Saint-Antoine", 12, [(652800,6861900),(653000,6861920),(653200,6861940)]),
    ("Avenue de la République", 11, [(652500,6862100),(652700,6862120),(652900,6862140)]),
    ("Rue de la Paix",       2, [(651900,6862400),(652000,6862380),(652100,6862360)]),
    ("Boulevard de Sébastopol", 1, [(652000,6862200),(652020,6862000),(652040,6861800)]),
    ("Rue Mouffetard",       5, [(652100,6861700),(652120,6861600),(652140,6861500)]),
    ("Avenue Montaigne",     8, [(651300,6862100),(651350,6861950),(651400,6861800)]),
    ("Rue de Passy",        16, [(650500,6862000),(650700,6862020),(650900,6862040)]),
    ("Boulevard Raspail",    6, [(651600,6861700),(651620,6861600),(651640,6861500)]),
]

materiaux = ['FON','FON','FON','PVC','PVC','PEHD','PEHD','ACI','AC']
etats     = ['BON','BON','BON','DEG','DEG','HS','INC']

rows = []
for i, (rue, arrdt, coords) in enumerate(rues_paris):
    rows.append({
        'id_cana': f'AEP-{arrdt:02d}-{i+1:03d}',
        'materiau': random.choice(materiaux),
        'diametre_mm': random.choice([100,110,125,150,200,250,300,350,400]),
        'annee_pose': random.randint(1950, 2015),
        'etat': random.choice(etats),
        'arrondissement': arrdt,
        'secteur': rue,
        'source': 'SYNTHESE_DEMO',
        'geometry': LineString(coords)
    })

gdf = gpd.GeoDataFrame(rows, crs='EPSG:2154')
engine = create_engine(DB_URL)
gdf.to_postgis('aep_canalisation_synthetique', engine, if_exists='replace', index=False)
print(f"OK — {len(gdf)} canalisations inserees dans PostGIS")

if __name__ == "__main__":
    pass
