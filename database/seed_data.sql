-- =============================================
-- DONNEES DE TEST — RESEAU EAU PARIS
-- Coordonnees en Lambert-93 (EPSG:2154)
-- =============================================

INSERT INTO aep_canalisation (id_cana, materiau, diametre_mm, annee_pose, etat, arrondissement, secteur, geom) VALUES
('AEP-P01-001', 'FON', 200, 1962, 'DEG', 1,  'Paris 1er',  ST_SetSRID(ST_MakeLine(ST_MakePoint(651800,6862100), ST_MakePoint(651950,6862150)), 2154)),
('AEP-P01-002', 'PVC', 110, 1995, 'BON', 1,  'Paris 1er',  ST_SetSRID(ST_MakeLine(ST_MakePoint(651950,6862150), ST_MakePoint(652100,6862200)), 2154)),
('AEP-P02-001', 'FON', 300, 1955, 'HS',  2,  'Paris 2e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(652100,6862200), ST_MakePoint(652300,6862250)), 2154)),
('AEP-P03-001', 'PEHD',150, 2008, 'BON', 3,  'Paris 3e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(652300,6862250), ST_MakePoint(652500,6862300)), 2154)),
('AEP-P04-001', 'ACI', 400, 1948, 'HS',  4,  'Paris 4e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(652200,6862000), ST_MakePoint(652400,6862050)), 2154)),
('AEP-P05-001', 'FON', 250, 1971, 'DEG', 5,  'Paris 5e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(652100,6861800), ST_MakePoint(652300,6861850)), 2154)),
('AEP-P06-001', 'PVC', 100, 2001, 'BON', 6,  'Paris 6e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(651900,6861700), ST_MakePoint(652100,6861750)), 2154)),
('AEP-P07-001', 'PEHD',200, 2015, 'BON', 7,  'Paris 7e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(651700,6861900), ST_MakePoint(651900,6861950)), 2154)),
('AEP-P08-001', 'FON', 350, 1963, 'DEG', 8,  'Paris 8e',   ST_SetSRID(ST_MakeLine(ST_MakePoint(651500,6862200), ST_MakePoint(651700,6862250)), 2154)),
('AEP-P15-001', 'PVC', 125, 1999, 'BON', 15, 'Paris 15e',  ST_SetSRID(ST_MakeLine(ST_MakePoint(650800,6861500), ST_MakePoint(651000,6861550)), 2154));

INSERT INTO exploitation_incident (ref_incident, type_inc, gravite, statut, description, arrondissement, geom) VALUES
('INC-2024-001', 'Fuite visible',           'CRI', 'OUVERT',   'Fuite importante rue de Rivoli', 1,  ST_SetSRID(ST_MakePoint(651900,6862120), 2154)),
('INC-2024-002', 'Affaissement chaussee',   'MAJ', 'EN_COURS', 'Affaissement lié vieille canalisation fonte', 4, ST_SetSRID(ST_MakePoint(652300,6862020), 2154)),
('INC-2024-003', 'Odeur suspecte',          'MIN', 'OUVERT',   'Odeur egout remontée cave', 5,  ST_SetSRID(ST_MakePoint(652200,6861820), 2154)),
('INC-2024-004', 'Pression anormale',       'MAJ', 'RESOLU',   'Chute pression secteur Opéra', 2,  ST_SetSRID(ST_MakePoint(652150,6862220), 2154)),
('INC-2024-005', 'Bouche incendie HS',      'MAJ', 'OUVERT',   'DECI hors service contrôle annuel', 8,  ST_SetSRID(ST_MakePoint(651600,6862220), 2154));