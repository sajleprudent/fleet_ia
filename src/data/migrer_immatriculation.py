"""
Migration : l'IMMATRICULATION devient l'identifiant unique des véhicules.

À exécuter UNE SEULE FOIS, depuis la racine du projet :
    python src/data/migrer_immatriculation.py

Ce que fait le script :
  1. Sauvegarde toutes les tables dans data/raw_sauvegarde_<date>/
  2. Normalise les immatriculations (majuscules, espaces supprimés)
  3. Vérifie l'unicité ; en cas de doublon ou de valeur vide, s'arrête
     sans rien modifier et affiche les lignes en cause
  4. Remplace, dans vehicules.csv, la valeur de `vehicule_id` par
     l'immatriculation
  5. Remappe la colonne `vehicule_id` des tables missions, carburant et
     maintenance selon l'ancienne correspondance WV-xxx -> immatriculation
  6. Signale les références orphelines (lignes pointant vers un véhicule
     absent du référentiel), qui sont conservées telles quelles

Note technique : la colonne conserve le nom `vehicule_id` dans les tables
de transaction — c'est le nom de la clé étrangère — mais elle contient
désormais l'immatriculation. Aucun code de jointure n'est donc à modifier.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from config import DATA_RAW

TABLES_LIEES = ["missions.csv", "carburant.csv", "maintenance.csv"]


def normaliser_immat(serie: pd.Series) -> pd.Series:
    """« dk 1234 ab » -> « DK-1234-AB » (majuscules, espaces normalisés)."""
    s = serie.astype(str).str.strip().str.upper()
    s = s.str.replace(r"[\s\u00a0]+", "-", regex=True)
    s = s.str.replace(r"-{2,}", "-", regex=True).str.strip("-")
    return s


def main():
    veh_p = DATA_RAW / "vehicules.csv"
    if not veh_p.exists():
        print("❌ vehicules.csv introuvable dans", DATA_RAW)
        return 1

    veh = pd.read_csv(veh_p)
    if "immatriculation" not in veh.columns:
        print("❌ La colonne 'immatriculation' est absente de vehicules.csv.")
        return 1

    # ── Contrôles préalables ──────────────────────────────────────────
    veh["immatriculation"] = normaliser_immat(veh.immatriculation)
    vides = veh.immatriculation.isin(["", "NAN", "NONE"]) | veh.immatriculation.isna()
    if vides.any():
        print(f"❌ {int(vides.sum())} véhicule(s) sans immatriculation. "
              f"Complétez-les avant migration :")
        print(veh.loc[vides, [c for c in ["vehicule_id", "marque", "modele"]
                              if c in veh.columns]].to_string(index=False))
        return 1

    dbl = veh.immatriculation.duplicated(keep=False)
    if dbl.any():
        print(f"❌ Immatriculations en double — elles doivent être uniques :")
        print(veh.loc[dbl, [c for c in ["vehicule_id", "immatriculation",
                                        "marque", "modele"]
                            if c in veh.columns]]
              .sort_values("immatriculation").to_string(index=False))
        return 1

    # ── Sauvegarde ────────────────────────────────────────────────────
    sauv = DATA_RAW.parent / f"raw_sauvegarde_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(DATA_RAW, sauv)
    print(f"💾 Sauvegarde créée : {sauv}")

    # ── Correspondance ancien -> nouveau ──────────────────────────────
    if "vehicule_id" in veh.columns:
        corresp = dict(zip(veh.vehicule_id.astype(str), veh.immatriculation))
    else:
        corresp = {}
    veh["vehicule_id"] = veh.immatriculation

    # immatriculation en tête de colonnes
    cols = ["vehicule_id", "immatriculation"] + \
           [c for c in veh.columns if c not in ("vehicule_id", "immatriculation")]
    veh[cols].to_csv(veh_p, index=False, encoding="utf-8")
    print(f"✅ vehicules.csv : {len(veh)} véhicules, identifiant = immatriculation")

    # ── Remappage des tables liées ────────────────────────────────────
    for nom in TABLES_LIEES:
        p = DATA_RAW / nom
        if not p.exists():
            continue
        df = pd.read_csv(p)
        if "vehicule_id" not in df.columns or df.empty:
            continue
        avant = df.vehicule_id.astype(str)
        df["vehicule_id"] = avant.map(corresp).fillna(
            normaliser_immat(avant))
        orphelins = ~df.vehicule_id.isin(set(veh.immatriculation))
        df.to_csv(p, index=False, encoding="utf-8")
        msg = f"✅ {nom} : {len(df)} lignes remappées"
        if orphelins.any():
            ids = sorted(set(df.loc[orphelins, "vehicule_id"]))[:5]
            msg += (f" — ⚠️ {int(orphelins.sum())} référence(s) orpheline(s) "
                    f"(ex. {', '.join(map(str, ids))})")
        print(msg)

    print("\n🎯 Migration terminée. Relancez ensuite :")
    print("   python src/models/features_maintenance.py")
    print("   python src/models/train_panne.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
