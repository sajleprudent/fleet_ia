"""
Migration des fichiers CSV vers la base SQLite.

À exécuter une seule fois, depuis la racine du projet :
    python src/data/migrer_sqlite.py

Ce que fait le script :
  1. Sauvegarde le dossier data/raw dans un dossier horodaté
  2. Crée data/fleet_ia.db
  3. Importe chaque table CSV présente, en préservant les types
     (identifiants en texte, dates au format ISO)
  4. Crée les index sur les clés de jointure
  5. Vérifie que chaque table contient bien le même nombre de lignes
     qu'à l'origine

Les fichiers CSV d'origine ne sont pas supprimés : ils restent disponibles
en secours dans le dossier de sauvegarde.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "dashboard"))

import pandas as pd

from config import DATA_RAW
import crud

ORDRE = ["vehicules", "staffs", "chauffeurs", "missions", "carburant",
         "maintenance", "comptes"]

# Colonnes lues en texte pour préserver matricules et immatriculations
def _types(chemin):
    entetes = pd.read_csv(chemin, nrows=0).columns
    return {c: str for c in entetes if crud._est_identifiant(c)}


def main():
    print("── Migration CSV → SQLite ──────────────────────")
    presents = [t for t in ORDRE if (DATA_RAW / f"{t}.csv").exists()]
    if not presents:
        print(f"❌ Aucun fichier CSV trouvé dans {DATA_RAW}")
        return 1

    if crud.BASE.exists():
        print(f"⚠️  La base existe déjà : {crud.BASE}")
        rep = input("   Écraser son contenu ? (oui/non) ").strip().lower()
        if rep not in ("oui", "o", "yes", "y"):
            print("   Migration annulée, rien n'a été modifié.")
            return 0

    sauv = DATA_RAW.parent / f"raw_sauvegarde_{datetime.now():%Y%m%d_%H%M%S}"
    shutil.copytree(DATA_RAW, sauv)
    print(f"💾 Sauvegarde des CSV : {sauv}")

    print(f"\n📦 Base : {crud.BASE}")
    total, erreurs = 0, []
    for t in presents:
        p = DATA_RAW / f"{t}.csv"
        try:
            df = pd.read_csv(p, dtype=_types(p), low_memory=False)
        except Exception as err:
            erreurs.append(f"{t} : lecture impossible ({err})")
            continue

        # Dates normalisées avant stockage
        for col in crud.DATES.get(t, []):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce",
                                         format="mixed")
        crud.ecrire(t, df)

        relu = crud.compter(t)
        etat = "✅" if relu == len(df) else "⚠️"
        if relu != len(df):
            erreurs.append(f"{t} : {len(df)} lignes lues, {relu} écrites")
        print(f"   {etat} {t:<14} {relu:>7,} lignes · "
              f"{len(df.columns):>2} colonnes")
        total += relu

    print(f"\n   Total : {total:,} lignes dans {len(presents)} table(s)")
    taille = crud.BASE.stat().st_size / 1e6
    print(f"   Taille de la base : {taille:.1f} Mo")

    # Contrôle d'intégrité référentielle
    print("\n── Contrôle des références ─────────────────────")
    veh = crud.lire("vehicules")
    staffs = crud.lire("staffs")
    for table, colonne, ref, nom_ref in [
            ("missions", "vehicule_id", veh, "véhicules"),
            ("missions", "chauffeur_id", staffs, "staffs"),
            ("carburant", "vehicule_id", veh, "véhicules"),
            ("maintenance", "vehicule_id", veh, "véhicules")]:
        df = crud.lire(table)
        if df is None or ref is None or colonne not in df.columns:
            continue
        cle = "vehicule_id" if ref is veh else "staff_id"
        if cle not in ref.columns:
            continue
        orphelins = ~df[colonne].isin(set(ref[cle].dropna()))
        n = int(orphelins.sum())
        print(f"   {'✅' if n == 0 else '⚠️ '} {table}.{colonne} → {nom_ref} : "
              f"{n} référence(s) orpheline(s)")

    if erreurs:
        print("\n⚠️  Points à vérifier :")
        for e in erreurs:
            print(f"   · {e}")

    print("\n🎯 Migration terminée. L'application utilise désormais la base.")
    print("   Les CSV d'origine restent disponibles dans la sauvegarde.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
