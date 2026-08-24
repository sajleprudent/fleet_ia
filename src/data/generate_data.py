"""
Génération de données synthétiques réalistes pour la flotte World Vision Sénégal.

Principe : on encode des relations causales réalistes dans les données
(âge + piste + style de conduite -> pannes ; charge + saison -> consommation)
que les modèles ML devront ensuite redécouvrir. Cela permet de valider
la méthodologie en attendant les données réelles.

Tables générées :
  - vehicules.csv      : référentiel du parc (141 véhicules)
  - chauffeurs.csv     : référentiel chauffeurs avec profil de conduite latent
  - missions.csv       : ordres de mission / déplacements
  - carburant.csv      : pleins de carburant par mission
  - maintenance.csv    : interventions (préventives + pannes)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from config import (
    DATA_RAW, N_VEHICULES, LOCALITES, TYPES_VEHICULES, MARQUES,
    PROBA_MARQUES, PART_PISTE, DATE_DEBUT, DATE_FIN, PRIX_CARBURANT,
    N_CHAUFFEURS, SEED, TYPES_PANNES,
)

rng = np.random.default_rng(SEED)


# ══════════════════════════════════════════════════════════════════════
# 1. VÉHICULES
# ══════════════════════════════════════════════════════════════════════
def generer_vehicules() -> pd.DataFrame:
    from config import MODELES, CENTRES_SERVICE, IMPUTATIONS
    aujourdhui = pd.Timestamp(DATE_FIN)

    localites = rng.choice(
        list(LOCALITES.keys()), size=N_VEHICULES, p=list(LOCALITES.values())
    )
    centres_par_loc = {}
    for c, l in CENTRES_SERVICE.items():
        centres_par_loc.setdefault(l, []).append(c)

    modeles = rng.choice(
        list(MODELES.keys()), size=N_VEHICULES,
        p=[v[2] for v in MODELES.values()],
    )
    annees = rng.choice(range(2012, 2026), size=N_VEHICULES,
                        p=_poids_annees(2012, 2025))

    rows = []
    for i in range(N_VEHICULES):
        mod = modeles[i]
        marque, type_v, _, conso_base, valeur, comb = MODELES[mod]
        annee = int(annees[i])
        age_2023 = max(0.3, 2023 - annee)
        km_par_an = 4_000 if type_v == "Moto" else 22_000
        km_initial = max(0, int(rng.normal(km_par_an, km_par_an * 0.27) * age_2023))

        d_circ = pd.Timestamp(f"{annee}-{rng.integers(1,13):02d}-{rng.integers(1,28):02d}")
        d_acq = d_circ + pd.Timedelta(days=int(rng.integers(0, 120)))

        # Conformité : dates dans les 14 derniers mois -> certaines expirées
        d_vt = aujourdhui - pd.Timedelta(days=int(rng.integers(0, 430)))
        d_ass = aujourdhui - pd.Timedelta(days=int(rng.integers(0, 430)))
        d_at = aujourdhui - pd.Timedelta(days=int(rng.integers(0, 430)))
        p_vt, p_ass, p_at = (d_vt + pd.Timedelta(days=365),
                             d_ass + pd.Timedelta(days=365),
                             d_at + pd.Timedelta(days=365))

        rows.append({
            "vehicule_id": f"WV-{i+1:03d}",
            "immatriculation": f"DK-{rng.integers(1000, 9999)}-{rng.choice(list('ABCDEFG'))}{rng.choice(list('ABCDEFG'))}",
            "marque": marque,
            "modele": mod,
            "type_vehicule": type_v,
            "n_chassis": "".join(rng.choice(list("ABCDEFGHJKLMNPRSTUVWXYZ0123456789"), 17)),
            "centre_service": rng.choice(centres_par_loc[localites[i]]),
            "localite": localites[i],
            "puissance_cv": 2 if type_v == "Moto" else int(rng.integers(7, 16)),
            "imputation": rng.choice(IMPUTATIONS),
            "date_premiere_circulation": d_circ.date(),
            "annee_mise_en_service": annee,
            "date_acquisition": d_acq.date(),
            "valeur_acquisition_fcfa": int(valeur * rng.normal(1.0, 0.08)),
            "combustible": comb,
            "conso_nominale_l_100km": round(conso_base * rng.normal(1.0, 0.05), 1),
            "km_initial": km_initial,
            "date_visite_technique": d_vt.date(),
            "etat_visite_technique": "Bon" if p_vt >= aujourdhui else "Pas bon",
            "prochaine_visite_technique": p_vt.date(),
            "date_souscription_assurance": d_ass.date(),
            "etat_assurance": "Bon" if p_ass >= aujourdhui else "Pas bon",
            "renouvellement_assurance": p_ass.date(),
            "date_admission_temporaire": d_at.date(),
            "etat_at": "Bon" if p_at >= aujourdhui else "Pas bon",
            "renouvellement_at": p_at.date(),
            "etat_carte_grise": rng.choice(["Bon", "Pas bon"], p=[0.93, 0.07]),
            "etat_vehicule": rng.choice(["Fonctionnel", "Non fonctionnel"], p=[0.94, 0.06]),
            "remarques": "",
        })
    return pd.DataFrame(rows)


def _poids_annees(a_min, a_max):
    """Parc plutôt vieillissant : plus de véhicules anciens que récents."""
    n = a_max - a_min + 1
    w = np.linspace(1.4, 0.6, n)
    return w / w.sum()


# ══════════════════════════════════════════════════════════════════════
# 2. CHAUFFEURS  (avec profil de conduite latent, non observé)
# ══════════════════════════════════════════════════════════════════════
def generer_chauffeurs() -> pd.DataFrame:
    prenoms = ["Mamadou", "Ousmane", "Ibrahima", "Cheikh", "Abdoulaye",
               "Moussa", "Alioune", "Modou", "Serigne", "Pape", "Assane",
               "Babacar", "Idrissa", "Lamine", "Souleymane", "Omar"]
    noms = ["Diop", "Ndiaye", "Fall", "Sow", "Ba", "Diallo", "Faye",
            "Gueye", "Sarr", "Sy", "Cissé", "Mbaye", "Thiam", "Kane"]

    localites = rng.choice(
        list(LOCALITES.keys()), size=N_CHAUFFEURS, p=list(LOCALITES.values())
    )
    rows = []
    for i in range(N_CHAUFFEURS):
        # Profil latent : 0 = très souple, 1 = très agressif
        # Impacte consommation ET usure -> les modèles devront le capter
        aggressivite = float(np.clip(rng.beta(2.2, 3.5), 0.02, 0.98))
        rows.append({
            "chauffeur_id": f"CH-{i+1:03d}",
            "nom_complet": f"{rng.choice(prenoms)} {rng.choice(noms)}",
            "localite": localites[i],
            "anciennete_annees": int(rng.integers(1, 22)),
            "date_permis": f"{rng.integers(1995, 2020)}-{rng.integers(1,13):02d}-01",
            # latent, exporté pour validation méthodo (à exclure des features!)
            "_aggressivite_latente": round(aggressivite, 3),
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
# 3. MISSIONS + CARBURANT + MAINTENANCE (simulation jour par jour)
# ══════════════════════════════════════════════════════════════════════
DESTINATIONS = {
    "Bureau National": ["Dakar intra-muros", "Thiès", "Mbour", "Rufisque", "Diamniadio"],
    "Zone Centre": ["Kaolack", "Fatick", "Kaffrine", "Diourbel", "Touba"],
    "Zone Sud": ["Ziguinchor", "Kolda", "Sédhiou", "Bignona", "Vélingara"],
}
DIST_MOY = {  # km aller-retour moyen par localité
    "Bureau National": 90,
    "Zone Centre": 210,
    "Zone Sud": 260,
}


def simuler_activite(vehicules: pd.DataFrame, chauffeurs: pd.DataFrame):
    dates = pd.date_range(DATE_DEBUT, DATE_FIN, freq="D")
    missions, carburant, maintenance = [], [], []

    # État courant par véhicule
    etat = {
        v.vehicule_id: {
            "km": v.km_initial,
            "usure": _usure_initiale(v),      # score latent 0-1
            "indispo_jusqua": None,
            "km_depuis_entretien": rng.integers(0, 5000),
        }
        for v in vehicules.itertuples()
    }
    ch_par_loc = {
        loc: chauffeurs[chauffeurs.localite == loc] for loc in LOCALITES
    }
    mission_id = fuel_id = maint_id = 0

    for date in dates:
        saison_pluie = date.month in (7, 8, 9, 10)  # hivernage
        # Demande de missions : plus faible le weekend, pic en période de programme
        base_p = 0.32 if date.weekday() < 5 else 0.07
        if date.month in (3, 4, 10, 11):  # pics d'activité programmes
            base_p *= 1.3

        for v in vehicules.itertuples():
            st = etat[v.vehicule_id]

            # Véhicule immobilisé ?
            if st["indispo_jusqua"] is not None and date <= st["indispo_jusqua"]:
                continue

            # ── Entretien préventif tous les ~5000 km ──
            if st["km_depuis_entretien"] >= 5000:
                maint_id += 1
                cout = int(rng.normal(85_000, 15_000))
                maintenance.append({
                    "maintenance_id": f"MT-{maint_id:05d}",
                    "vehicule_id": v.vehicule_id,
                    "date": date.date(),
                    "type_intervention": "Entretien préventif",
                    "categorie": "Vidange/Révision",
                    "cout_fcfa": max(40_000, cout),
                    "jours_immobilisation": 1,
                    "km_compteur": int(st["km"]),
                })
                st["km_depuis_entretien"] = 0
                st["usure"] = max(0.0, st["usure"] - 0.015)  # l'entretien réduit un peu l'usure
                st["indispo_jusqua"] = date
                continue

            # ── Mission ce jour ? ──
            if rng.random() > base_p:
                continue

            pool = ch_par_loc[v.localite]
            ch = pool.iloc[int(rng.integers(0, len(pool)))]

            dist = max(15, rng.normal(DIST_MOY[v.localite], DIST_MOY[v.localite] * 0.45))
            part_piste = float(np.clip(rng.normal(PART_PISTE[v.localite], 0.12), 0, 1))
            charge = float(np.clip(rng.beta(2, 2.5), 0.05, 1.0))  # taux de charge
            duree_j = 1 if dist < 300 else int(rng.integers(1, 4))

            mission_id += 1
            missions.append({
                "mission_id": f"MS-{mission_id:06d}",
                "vehicule_id": v.vehicule_id,
                "chauffeur_id": ch.chauffeur_id,
                "date_depart": date.date(),
                "duree_jours": duree_j,
                "destination": rng.choice(DESTINATIONS[v.localite]),
                "distance_km": round(dist, 1),
                "part_piste": round(part_piste, 2),
                "taux_charge": round(charge, 2),
                "objet": rng.choice([
                    "Suivi programme", "Distribution", "Supervision terrain",
                    "Réunion partenaires", "Évaluation", "Logistique",
                ]),
            })

            # ── Consommation réelle (relation causale à redécouvrir) ──
            agg = ch._aggressivite_latente
            age = date.year - v.annee_mise_en_service
            conso = v.conso_nominale_l_100km * (
                1
                + 0.22 * part_piste          # la piste consomme plus
                + 0.13 * charge              # la charge aussi
                + 0.25 * agg                 # style de conduite
                + 0.012 * age                # vieillissement moteur
                + (0.05 if saison_pluie else 0.0)
                + 0.20 * st["usure"]         # véhicule usé surconsomme
            )
            litres = dist / 100 * conso * rng.normal(1.0, 0.05)

            # ~2.5% de pleins anormaux (fraude/fuite simulée) pour le module anomalies
            anomalie = rng.random() < 0.025
            if anomalie:
                litres *= rng.uniform(1.35, 1.9)

            fuel_id += 1
            carburant.append({
                "plein_id": f"FL-{fuel_id:06d}",
                "mission_id": f"MS-{mission_id:06d}",
                "vehicule_id": v.vehicule_id,
                "chauffeur_id": ch.chauffeur_id,
                "date": date.date(),
                "litres": round(litres, 1),
                "montant_fcfa": int(litres * PRIX_CARBURANT),
                "_anomalie_reelle": int(anomalie),  # vérité terrain pour évaluation
            })

            # ── Mise à jour usure & probabilité de panne ──
            st["km"] += dist
            st["km_depuis_entretien"] += dist
            st["usure"] += (dist / 1000) * (
                0.003 + 0.020 * part_piste + 0.005 * agg + 0.0015 * age
            )
            st["usure"] = min(st["usure"], 1.0)

            p_panne = 0.0006 + 0.018 * st["usure"] ** 2.2 + 0.002 * (age > 9)
            if rng.random() < p_panne:
                cat = rng.choice(list(TYPES_PANNES.keys()))
                gravite, cout_m, immo = TYPES_PANNES[cat]
                cout = int(max(30_000, rng.normal(cout_m, cout_m * 0.3)))
                immo_j = max(1, int(rng.normal(immo, 1)))
                maint_id += 1
                maintenance.append({
                    "maintenance_id": f"MT-{maint_id:05d}",
                    "vehicule_id": v.vehicule_id,
                    "date": (date + pd.Timedelta(days=duree_j)).date(),
                    "type_intervention": "Panne",
                    "categorie": cat,
                    "cout_fcfa": cout,
                    "jours_immobilisation": immo_j,
                    "km_compteur": int(st["km"]),
                })
                st["indispo_jusqua"] = date + pd.Timedelta(days=duree_j + immo_j)
                st["usure"] = max(0.0, st["usure"] - 0.10)  # réparation restaure partiellement

    return (
        pd.DataFrame(missions),
        pd.DataFrame(carburant),
        pd.DataFrame(maintenance),
    )


def _usure_initiale(v) -> float:
    age = 2023 - v.annee_mise_en_service
    return float(np.clip(0.04 * age + rng.normal(0, 0.05), 0, 0.75))


# ══════════════════════════════════════════════════════════════════════
def main():
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    print("1/3 Génération des référentiels…")
    vehicules = generer_vehicules()
    chauffeurs = generer_chauffeurs()

    print("2/3 Simulation de 3 ans d'activité (missions, carburant, pannes)…")
    missions, carburant, maintenance = simuler_activite(vehicules, chauffeurs)

    print("3/3 Écriture des fichiers…")
    vehicules.to_csv(DATA_RAW / "vehicules.csv", index=False)
    chauffeurs.to_csv(DATA_RAW / "chauffeurs.csv", index=False)
    missions.to_csv(DATA_RAW / "missions.csv", index=False)
    carburant.to_csv(DATA_RAW / "carburant.csv", index=False)
    maintenance.to_csv(DATA_RAW / "maintenance.csv", index=False)

    print("\n── Résumé ──────────────────────────────")
    print(f"Véhicules   : {len(vehicules):>7,}")
    print(f"Chauffeurs  : {len(chauffeurs):>7,}")
    print(f"Missions    : {len(missions):>7,}")
    print(f"Pleins      : {len(carburant):>7,}")
    print(f"Interventions maintenance : {len(maintenance):,}")
    print(f"  dont pannes             : {(maintenance.type_intervention=='Panne').sum():,}")
    print(f"Anomalies carburant simulées : {carburant._anomalie_reelle.sum():,}")


if __name__ == "__main__":
    main()
