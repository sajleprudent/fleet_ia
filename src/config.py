"""
Configuration centrale du projet Fleet-IA
Système intelligent de gestion prédictive de flotte - World Vision Sénégal
"""
from pathlib import Path

# ── Chemins ──────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
MODELS_DIR = BASE_DIR / "data" / "models_artifacts"

# ── Paramètres de la flotte (calibrés sur le parc réel) ─────────────
N_VEHICULES = 141
LOCALITES = {
    "Bureau National": 0.40,   # ~40% du parc à Dakar
    "Zone Centre": 0.32,
    "Zone Sud": 0.28,
}

# Modèle : (marque, type Voiture/Moto, proportion, conso L/100km, valeur acquisition FCFA, combustible)
MODELES = {
    "Hilux":        ("Toyota",     "Voiture", 0.28, 11.5, 28_000_000, "Gasoil"),
    "Land Cruiser": ("Toyota",     "Voiture", 0.15, 12.5, 45_000_000, "Gasoil"),
    "Prado":        ("Toyota",     "Voiture", 0.10, 10.5, 38_000_000, "Gasoil"),
    "Hiace":        ("Toyota",     "Voiture", 0.07, 13.5, 25_000_000, "Gasoil"),
    "Patrol":       ("Nissan",     "Voiture", 0.08, 12.0, 35_000_000, "Gasoil"),
    "Navara":       ("Nissan",     "Voiture", 0.06, 11.0, 26_000_000, "Gasoil"),
    "L200":         ("Mitsubishi", "Voiture", 0.07, 11.0, 25_000_000, "Gasoil"),
    "Ranger":       ("Ford",       "Voiture", 0.05, 11.5, 27_000_000, "Gasoil"),
    "Corolla":      ("Toyota",     "Voiture", 0.05,  7.5, 15_000_000, "Super"),
    "DT 125":       ("Yamaha",     "Moto",    0.05,  3.0,  2_500_000, "Super"),
    "XTZ 125":      ("Yamaha",     "Moto",    0.04,  3.2,  2_800_000, "Super"),
}
TYPES_VEHICULE = ["Voiture", "Moto"]
COMBUSTIBLES = ["Gasoil", "Super"]

# Centres de service -> localité analytique (⚠️ mapping à valider avec WV)
CENTRES_SERVICE = {
    "Dakar": "Bureau National",
    "Kaffrine": "Zone Centre",
    "Fatick": "Zone Centre",
    "Tamba": "Zone Centre",
    "Kolda": "Zone Sud",
    "Kedougou": "Zone Sud",
    "Tanaf": "Zone Sud",
    "Oussouye": "Zone Sud",
}

IMPUTATIONS = ["ADMIN", "PRG-EDUCATION", "PRG-SANTE-NUT",
               "PRG-WASH", "PRG-PROTECTION", "GRANTS"]

# ── Départements / Unités (libellés de l'export RH World Vision) ─────
DEPARTEMENTS = ["ICT", "Finance", "Administration", "Operations",
                "Communication", "People & Culture", "Supply chain",
                "Sponsorship F&D", "DN", "HEA", "Programs", "Audit"]

# Code utilisé dans le n° de mission : WVS-{CODE}-{date}-{0001..9999}
CODES_DEPT = {"ICT": "ICT", "Finance": "FIN", "Administration": "ADM",
              "Operations": "OPS", "Communication": "COMS",
              "People & Culture": "PC", "Supply chain": "SC",
              "Sponsorship F&D": "SPON", "DN": "DN", "HEA": "HEA",
              "Programs": "PRG", "Audit": "AUD",
              # Variantes rencontrées dans les exports
              "IT": "ICT", "Admin": "ADM", "COMS": "COMS", "P&C": "PC",
              "Supply Chain": "SC", "Sponsorship": "SPON"}

# Imputation d'une mission : département OU projet
IMPUTATIONS_MISSION = [f"DEPARTMENT / {d}" for d in DEPARTEMENTS] + \
                      [f"PROJET / {p}" for p in IMPUTATIONS]

# ── Rôles applicatifs ────────────────────────────────────────────────
# « User » est le rôle par défaut : le staff peut partir en mission mais
# n'a aucun droit de gestion dans l'application. Les autres rôles sont
# cumulables et révocables.
ROLE_DEFAUT = "User"
ROLES_STAFF = ["User", "Chauffeur", "Approbateur", "Gestionnaire", "Admin"]
DESCRIPTION_ROLES = {
    "User": "Peut être désigné agent ou passager d'une mission",
    "Chauffeur": "Peut être affecté à la conduite d'un véhicule",
    "Approbateur": "Peut approuver ou rejeter les ordres de mission",
    "Gestionnaire": "Crée et gère les missions, véhicules et interventions",
    "Admin": "Tous les droits, dont l'attribution des rôles",
}

ETATS_DOC = ["Bon", "Pas bon"]
ETATS_VEHICULE = ["Fonctionnel", "Non fonctionnel"]

# Compatibilité simulation (anciens types conservés pour référence conso/charge)
TYPES_VEHICULES = {
    "Pickup 4x4": (0.45, 11.5, 28_000_000),
    "SUV 4x4": (0.25, 10.0, 32_000_000),
    "Berline": (0.12, 7.5, 15_000_000),
    "Minibus": (0.10, 13.5, 25_000_000),
    "Camion léger": (0.08, 16.0, 35_000_000),
}

MARQUES = ["Toyota", "Nissan", "Mitsubishi", "Ford", "Hyundai", "Yamaha"]
PROBA_MARQUES = [0.55, 0.18, 0.12, 0.08, 0.05, 0.02]

# Types de routes par localité (proportion de piste — facteur d'usure clé)
PART_PISTE = {
    "Bureau National": 0.15,   # Dakar: surtout bitume
    "Zone Centre": 0.55,
    "Zone Sud": 0.70,          # Casamance: beaucoup de piste
}

# ── Paramètres de simulation ─────────────────────────────────────────
DATE_DEBUT = "2023-07-01"
DATE_FIN = "2026-06-30"        # 3 ans d'historique
PRIX_CARBURANT = 990            # FCFA/litre (gasoil, moyenne)
N_CHAUFFEURS = 96

SEED = 42

# ── Champs de conformité (repris de l'app Power Apps existante) ─────
CHAMPS_CONFORMITE = [
    "Etat Visite Technique",
    "Etat Assurance",
    "Etat Carte grise",
    "Etat AT",
]

TYPES_PANNES = {
    # type: (gravité 1-3, coût moyen FCFA, immobilisation jours moy.)
    "Freinage": (2, 180_000, 2),
    "Suspension": (2, 250_000, 3),
    "Moteur": (3, 900_000, 8),
    "Embrayage/Transmission": (3, 550_000, 5),
    "Électrique/Batterie": (1, 90_000, 1),
    "Pneumatique": (1, 120_000, 1),
    "Refroidissement": (2, 200_000, 2),
    "Climatisation": (1, 150_000, 1),
}
