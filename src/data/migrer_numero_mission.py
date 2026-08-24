"""
Migration : le NUMÉRO DE MISSION devient l'identifiant unique.

À exécuter une seule fois, depuis la racine du projet :
    python src/data/migrer_numero_mission.py

Ce que fait le script :
  1. Sauvegarde la base
  2. Complète les numéros manquants au format WVS-{DEPT}-{date}-{0001}
  3. Vérifie l'unicité ; en cas de doublon, s'arrête sans rien modifier
  4. Remplace, dans carburant, la colonne `mission_id` par
     `numero_mission` en reportant la correspondance
  5. Supprime la colonne `mission_id` de la table missions

Le numéro de mission est celui qui figure sur l'ordre de mission : il est
déjà connu en interne, ce qui évite de manipuler un identifiant technique
supplémentaire.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "dashboard"))

import pandas as pd

from config import CODES_DEPT
import crud


def generer_numeros(mis: pd.DataFrame) -> pd.DataFrame:
    """Attribue un numéro aux missions qui n'en ont pas encore."""
    mis = mis.copy()
    if "numero_mission" not in mis.columns:
        mis["numero_mission"] = None
    num = mis.numero_mission.astype("string").str.strip()
    vide = num.isna() | num.isin(["", "nan", "None"])

    # La séquence reprend après le plus grand numéro déjà attribué
    deja = num[~vide].str.extract(r"-(\d{4})$")[0].dropna()
    seq = int(deja.astype(int).max()) if len(deja) else 0

    dates = pd.to_datetime(mis.get("date_depart"), errors="coerce",
                           format="mixed")
    depts = mis.get("departement", pd.Series("", index=mis.index)).astype(str)
    nouveaux = []
    for i in mis.index[vide]:
        seq = (seq % 9999) + 1
        d = dates.get(i)
        d = d if pd.notna(d) else pd.Timestamp.today()
        code = CODES_DEPT.get(depts.get(i, ""), "GEN")
        nouveaux.append(f"WVS-{code}-{d:%Y-%m-%d}-{seq:04d}")
    mis.loc[vide, "numero_mission"] = nouveaux
    return mis, int(vide.sum())


def main():
    print("── Migration : numéro de mission comme identifiant ──")
    mis = crud.lire("missions")
    if mis is None or mis.empty:
        print("❌ Aucune mission en base.")
        return 1

    mis, n_generes = generer_numeros(mis)
    if n_generes:
        print(f"   {n_generes} numéro(s) généré(s) pour des missions "
              f"qui n'en avaient pas")

    dbl = mis.numero_mission.duplicated(keep=False)
    if dbl.any():
        print(f"❌ {int(dbl.sum())} numéro(s) de mission en double — ils "
              f"doivent être uniques. Rien n'a été modifié :")
        cols = [c for c in ["numero_mission", "mission_id", "date_depart",
                            "objet", "agent_principal"] if c in mis.columns]
        print(mis.loc[dbl, cols].sort_values("numero_mission")
              .head(20).to_string(index=False))
        return 1

    sauv = crud.BASE.with_name(
        f"fleet_ia_sauvegarde_{datetime.now():%Y%m%d_%H%M%S}.db")
    shutil.copy(crud.BASE, sauv)
    print(f"💾 Base sauvegardée : {sauv.name}")

    # ── Correspondance ancien identifiant → numéro ────────────────────
    corresp = {}
    if "mission_id" in mis.columns:
        corresp = dict(zip(mis.mission_id.astype(str), mis.numero_mission))

    # ── Carburant : mission_id → numero_mission ───────────────────────
    fuel = crud.lire("carburant")
    if fuel is not None and len(fuel):
        if "mission_id" in fuel.columns:
            ancien = fuel.mission_id.astype(str)
            nouveau = ancien.map(corresp)
            # Repli sur un numéro déjà présent, si la colonne existe
            if "numero_mission" in fuel.columns:
                nouveau = nouveau.fillna(fuel["numero_mission"])
            fuel["numero_mission"] = nouveau
            fuel = fuel.drop(columns=["mission_id"])
            rattaches = int(fuel.numero_mission.notna().sum())
            print(f"✅ carburant : {rattaches:,}/{len(fuel):,} plein(s) "
                  f"rattaché(s) à un numéro de mission")
            orphelins = int((~fuel.numero_mission
                             .isin(set(mis.numero_mission))).sum())
            if orphelins:
                print(f"   ⚠️  {orphelins} plein(s) sans mission "
                      f"correspondante (conservés)")
        cols_f = ["plein_id", "numero_mission"] + [
            c for c in fuel.columns if c not in ("plein_id", "numero_mission")]
        crud.ecrire("carburant", fuel[[c for c in cols_f if c in fuel.columns]])

    # ── Missions : suppression de la colonne technique ────────────────
    if "mission_id" in mis.columns:
        mis = mis.drop(columns=["mission_id"])
    # numero_mission en première colonne
    cols = ["numero_mission"] + [c for c in mis.columns
                                 if c != "numero_mission"]
    crud.ecrire("missions", mis[cols])
    print(f"✅ missions : {len(mis):,} mission(s), identifiant = "
          f"numero_mission")

    print("\n🎯 Migration terminée. Remplacez ensuite les fichiers de code, "
          "puis relancez :")
    print("   python src/models/features_maintenance.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
