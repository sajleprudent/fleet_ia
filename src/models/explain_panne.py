"""
Étape 2.3 — Explicabilité et rapport d'alertes maintenance.

1. Importance GLOBALE : coefficients standardisés du modèle
   (quels facteurs pilotent le risque de panne dans la flotte ?)
2. Explication LOCALE : pour chaque véhicule à risque, contribution
   exacte de chaque variable (coef × valeur standardisée).
   NB: pour un modèle linéaire, ces contributions sont équivalentes
   aux valeurs SHAP — exactes et sans approximation.
3. Rapport d'alertes : top véhicules à inspecter, avec les 3 facteurs
   de risque dominants de chacun, exporté en CSV pour le gestionnaire.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import joblib

from config import MODELS_DIR, DATA_PROCESSED
from train_panne import FEATURES_NUM, FEATURES_CAT

LIBELLES = {
    "age_annees": "Âge du véhicule",
    "km_total": "Kilométrage total",
    "km_90j": "Km parcourus (90j)",
    "km_30j": "Km parcourus (30j)",
    "n_missions_90j": "Nb missions (90j)",
    "piste_moy_90j": "Part de piste (90j)",
    "charge_moy_90j": "Taux de charge (90j)",
    "surconso_90j": "Surconsommation (90j)",
    "surconso_30j": "Surconsommation (30j)",
    "tendance_surconso": "Tendance surconso",
    "km_piste_90j": "Km de piste (90j)",
    "km_piste_cumules": "Km de piste cumulés",
    "jours_depuis_maint": "Jours depuis entretien",
    "km_depuis_maint": "Km depuis entretien",
    "n_pannes_12m": "Pannes (12 mois)",
}


def main():
    pipe = joblib.load(MODELS_DIR / "modele_panne_30j.joblib")
    df = pd.read_parquet(DATA_PROCESSED / "features_maintenance.parquet")

    prep = pipe.named_steps["prep"]
    clf = pipe.named_steps["clf"]
    noms_features = prep.get_feature_names_out()
    coefs = clf.coef_[0]

    # ── 1. Importance globale ─────────────────────────────────────────
    imp = pd.Series(coefs, index=noms_features).sort_values(key=abs, ascending=False)
    print("═" * 62)
    print("1. FACTEURS DE RISQUE GLOBAUX (coefficients standardisés)")
    print("   coef > 0 : augmente le risque | coef < 0 : le réduit")
    print("═" * 62)
    for nom, c in imp.head(12).items():
        nom_court = nom.split("__")[-1]
        lib = LIBELLES.get(nom_court, nom_court)
        barre = "█" * int(abs(c) * 25)
        signe = "+" if c > 0 else "-"
        print(f"  {lib:<28} {signe}{abs(c):.3f} {barre}")

    # ── 2. Alertes sur le dernier snapshot ────────────────────────────
    derniere = df.date_snapshot.max()
    snap = df[df.date_snapshot == derniere].copy()
    X = snap[FEATURES_NUM + FEATURES_CAT]
    scores = pipe.predict_proba(X)[:, 1]
    calib = joblib.load(MODELS_DIR / "calibrateur_panne.joblib")
    snap["proba_panne_30j"] = calib.predict_proba(scores.reshape(-1, 1))[:, 1]

    # Contributions locales exactes : coef * valeur transformée
    X_std = prep.transform(X)
    if hasattr(X_std, "toarray"):
        X_std = X_std.toarray()
    contribs = X_std * coefs  # (n_vehicules, n_features)

    top = snap.nlargest(15, "proba_panne_30j").copy()
    print("\n" + "═" * 62)
    print(f"2. ALERTES — 15 VÉHICULES À INSPECTER (semaine du {derniere.date()})")
    print("═" * 62)

    lignes_csv = []
    for _, row in top.iterrows():
        i = snap.index.get_loc(row.name)
        c = pd.Series(contribs[i], index=noms_features)
        c = c[[n for n in c.index if n.startswith("num__")]]  # facteurs actionnables
        top3 = c.sort_values(ascending=False).head(3)
        facteurs = ", ".join(
            LIBELLES.get(n.split("__")[-1], n) for n in top3.index if top3[n] > 0
        )
        print(f"  {row.vehicule_id}  [{row.localite:<15}] "
              f"risque={row.proba_panne_30j*100:5.1f}%  ← {facteurs}")
        lignes_csv.append({
            "vehicule_id": row.vehicule_id,
            "localite": row.localite,
            "type_vehicule": row.type_vehicule,
            "age_annees": row.age_annees,
            "km_total": int(row.km_total),
            "proba_panne_30j": round(row.proba_panne_30j, 3),
            "facteurs_de_risque": facteurs,
        })

    out = MODELS_DIR / "alertes_maintenance.csv"
    pd.DataFrame(lignes_csv).to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\nRapport exporté → {out}")
    print("(encodage utf-8-sig : s'ouvre proprement dans Excel)")


if __name__ == "__main__":
    main()
