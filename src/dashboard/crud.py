"""
Accès aux données — base SQLite.

L'interface est identique à la version fichiers : `lire("missions.csv")` et
`ecrire("missions.csv", df)`. Les pages n'ont donc pas à connaître le mode
de stockage. Le suffixe « .csv » est accepté par compatibilité ; le nom de
la table est celui du fichier sans extension.

Ce que SQLite apporte par rapport aux CSV :
  · écritures transactionnelles — une écriture interrompue ne laisse pas
    la table à moitié écrite ;
  · lecture concurrente — plusieurs utilisateurs peuvent consulter
    simultanément (mode WAL) ;
  · types préservés — les identifiants restent du texte, les matricules
    commençant par zéro ne sont plus tronqués ;
  · index sur les clés — filtres et jointures restent rapides quand
    l'historique grossit.
"""
import datetime
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from config import DATA_RAW

BASE = DATA_RAW.parent / "fleet_ia.db"

TABLES = ["vehicules", "staffs", "missions", "carburant", "maintenance",
          "comptes", "chauffeurs"]

DATES = {
    "missions": ["date_depart", "date_fin"],
    "carburant": ["date"],
    "maintenance": ["date"],
}

# Les identifiants sont toujours du texte : sans cela, un matricule
# (10027846) deviendrait un nombre et les jointures casseraient.
SUFFIXES_ID = ("_id", "_ids")
COLONNES_ID = {"immatriculation", "n_chassis", "telephone", "numero_mission",
               "login", "empreinte"}

INDEX = {
    "vehicules": ["vehicule_id", "immatriculation", "centre_service"],
    "staffs": ["staff_id", "centre_service"],
    "missions": ["mission_id", "vehicule_id", "chauffeur_id",
                 "approbateur_id", "date_depart", "statut"],
    "carburant": ["vehicule_id", "mission_id", "date"],
    "maintenance": ["vehicule_id", "date", "type_intervention"],
    "comptes": ["login"],
}


# ══════════════════════════════════════════════════════════════════════
def nom_table(nom: str) -> str:
    """« missions.csv » ou « missions » -> « missions »."""
    return str(nom).rsplit("/", 1)[-1].removesuffix(".csv").strip()


@contextmanager
def connexion():
    BASE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(BASE, timeout=15)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def tables_existantes() -> set:
    if not BASE.exists():
        return set()
    with connexion() as con:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


def _est_identifiant(col: str) -> bool:
    return col.endswith(SUFFIXES_ID) or col in COLONNES_ID


# ══════════════════════════════════════════════════════════════════════
# Lecture / écriture
# ══════════════════════════════════════════════════════════════════════
def lire(nom: str) -> pd.DataFrame | None:
    """Retourne la table sous forme de DataFrame, ou None si absente."""
    t = nom_table(nom)
    if t not in tables_existantes():
        return None
    with connexion() as con:
        df = pd.read_sql_query('SELECT * FROM "%s"' % t, con)
    for c in df.columns:
        if _est_identifiant(c):
            df[c] = (df[c].astype("string").str.strip()
                     .replace({"nan": None, "None": None, "": None,
                               "<NA>": None}))
    for col in DATES.get(t, []):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
    return df


def _valeur_sql(v):
    """Convertit une valeur Python en type accepté par SQLite.

    Nécessaire car une colonne peut mélanger les types : les lignes lues
    en base contiennent des Timestamp, tandis qu'une ligne ajoutée par un
    formulaire contient une date ou du texte. La colonne devient alors de
    type « object » et SQLite refuse les objets temporels.
    """
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, datetime.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, datetime.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, datetime.time):
        return v.strftime("%H:%M:%S")
    if isinstance(v, (list, tuple, set, dict)):
        return str(v)
    return v


def ecrire(nom: str, df: pd.DataFrame):
    """Remplace intégralement la table, en une seule transaction."""
    t = nom_table(nom)
    a_ecrire = df.copy()
    for c in a_ecrire.columns:
        if pd.api.types.is_datetime64_any_dtype(a_ecrire[c]):
            a_ecrire[c] = a_ecrire[c].dt.strftime("%Y-%m-%d %H:%M:%S")
        elif _est_identifiant(c):
            a_ecrire[c] = a_ecrire[c].astype("string")
        elif a_ecrire[c].dtype == object:
            # Colonne hétérogène : dates, heures ou objets divers
            a_ecrire[c] = a_ecrire[c].map(_valeur_sql)
    with connexion() as con:
        a_ecrire.to_sql(t, con, if_exists="replace", index=False)
        _creer_index(con, t, a_ecrire.columns)
    try:
        st.cache_data.clear()
    except Exception:
        pass


def _creer_index(con, table, colonnes):
    for col in INDEX.get(table, []):
        if col in colonnes:
            con.execute('CREATE INDEX IF NOT EXISTS "idx_%s_%s" ON "%s"("%s")'
                        % (table, col, table, col))


def compter(nom: str) -> int:
    t = nom_table(nom)
    if t not in tables_existantes():
        return 0
    with connexion() as con:
        return con.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]


def requete(sql: str, params=()) -> pd.DataFrame:
    """Requête SQL libre — utile pour les analyses et le débogage."""
    with connexion() as con:
        return pd.read_sql_query(sql, con, params=params)


# ══════════════════════════════════════════════════════════════════════
# Utilitaires conservés à l'identique
# ══════════════════════════════════════════════════════════════════════
def prochain_id(df, colonne: str, prefixe: str, largeur: int) -> str:
    """Ex : prochain_id(veh, 'vehicule_id', 'WV-', 3) -> 'WV-142'."""
    if df is None or df.empty or colonne not in df.columns:
        n = 1
    else:
        nums = (df[colonne].astype(str).str.extract(r"(\d+)$")[0]
                .dropna().astype(int))
        n = (nums.max() + 1) if len(nums) else 1
    return "%s%0*d" % (prefixe, largeur, n)


def editeur_table(nom_fichier: str, df, cle: str, colonnes_fixes=None) -> None:
    """Tableau éditable avec bouton d'enregistrement."""
    st.caption("✏️ Double-cliquez sur une cellule pour modifier. "
               "Cochez une ligne puis touche Suppr pour la supprimer. "
               "Cliquez ensuite sur **Enregistrer**.")
    edite = st.data_editor(
        df, num_rows="dynamic", use_container_width=True,
        disabled=colonnes_fixes or [], key="edit_%s" % nom_fichier)
    c1, c2 = st.columns([1, 4])
    if c1.button("💾 Enregistrer", key="save_%s" % nom_fichier, type="primary"):
        if edite[cle].isna().any() or (edite[cle].astype(str).str.strip()
                                       == "").any():
            st.error("Chaque ligne doit avoir un identifiant `%s`." % cle)
        elif edite[cle].duplicated().any():
            st.error("Identifiants `%s` en double : %s"
                     % (cle, edite[edite[cle].duplicated()][cle].tolist()))
        else:
            ecrire(nom_fichier, edite)
            st.success("✅ %s enregistré (%d lignes)."
                       % (nom_table(nom_fichier), len(edite)))
            st.rerun()
