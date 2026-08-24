"""
Référentiels modifiables depuis l'application.

Les listes de valeurs — catégories de maintenance, départements,
imputations, objets de mission — étaient jusqu'ici figées dans le code.
Elles sont désormais stockées en base et administrables, de sorte qu'un
nouveau type de panne ou un nouveau département n'exige plus de toucher
au code.

Au premier lancement, la table est initialisée à partir des valeurs
définies dans config.py : aucune donnée existante n'est perdue.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

import auth
import crud
import ui

TABLE = "referentiels"
COLS = ["type", "valeur", "code", "actif", "ordre"]

# type technique -> (libellé affiché, description, code utilisé ?)
TYPES = {
    "categorie_maintenance": (
        "Catégories de maintenance",
        "Organes ou natures d'intervention proposés à la saisie d'une "
        "intervention.", False),
    "departement": (
        "Départements / Unités",
        "Unités organisationnelles. Le code sert à composer le numéro de "
        "mission : WVS-{code}-{date}-{séquence}.", True),
    "imputation": (
        "Imputations budgétaires",
        "Départements et projets sur lesquels imputer une mission.", False),
    }


# ══════════════════════════════════════════════════════════════════════
def _defauts() -> pd.DataFrame:
    """Valeurs initiales, reprises de la configuration."""
    from config import (TYPES_PANNES, DEPARTEMENTS, CODES_DEPT,
                        IMPUTATIONS_MISSION)
    lignes = []
    cats = ["Vidange/Révision"] + list(TYPES_PANNES.keys())
    for i, v in enumerate(cats):
        lignes.append({"type": "categorie_maintenance", "valeur": v,
                       "code": "", "actif": "Oui", "ordre": i})
    for i, v in enumerate(DEPARTEMENTS):
        lignes.append({"type": "departement", "valeur": v,
                       "code": CODES_DEPT.get(v, v[:4].upper()),
                       "actif": "Oui", "ordre": i})
    for i, v in enumerate(IMPUTATIONS_MISSION):
        lignes.append({"type": "imputation", "valeur": v, "code": "",
                       "actif": "Oui", "ordre": i})
    # Les objets de mission ne sont pas un référentiel : chaque mission
    # a son propre objet, saisi librement à la création.
    return pd.DataFrame(lignes, columns=COLS)


def charger() -> pd.DataFrame:
    df = crud.lire(TABLE)
    if df is None or df.empty:
        df = _defauts()
        crud.ecrire(TABLE, df)
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    return df


def liste(type_ref: str, actifs_seulement=True) -> list:
    """Valeurs d'un référentiel, dans l'ordre défini."""
    df = charger()
    d = df[df.type == type_ref].copy()
    if actifs_seulement:
        d = d[d.actif.astype(str).str.strip().str.lower() != "non"]
    d["ordre"] = pd.to_numeric(d.ordre, errors="coerce").fillna(999)
    return d.sort_values("ordre").valeur.astype(str).tolist()


def codes_departements() -> dict:
    """Correspondance département -> code, pour le numéro de mission."""
    df = charger()
    d = df[df.type == "departement"]
    return {str(r.valeur): (str(r.code) or str(r.valeur)[:4].upper())
            for r in d.itertuples()}


def ajouter(type_ref, valeur, code=""):
    df = charger()
    valeur = str(valeur).strip()
    if not valeur:
        return False, "La valeur ne peut pas être vide."
    existe = df[(df.type == type_ref)
                & (df.valeur.astype(str).str.strip().str.lower()
                   == valeur.lower())]
    if len(existe):
        return False, f"« {valeur} » existe déjà dans ce référentiel."
    ordre = pd.to_numeric(df[df.type == type_ref].ordre,
                          errors="coerce").max()
    ordre = 0 if pd.isna(ordre) else int(ordre) + 1
    crud.ecrire(TABLE, pd.concat([df, pd.DataFrame([{
        "type": type_ref, "valeur": valeur, "code": str(code).strip(),
        "actif": "Oui", "ordre": ordre}])], ignore_index=True))
    return True, f"« {valeur} » ajouté."


# ══════════════════════════════════════════════════════════════════════
def page_referentiels(d):
    ui.titre_page("Référentiels", "📚")
    st.caption("Module référentiels v10.4 — listes de valeurs "
               "administrables sans intervention sur le code")
    if auth.bloquer("gerer_comptes",
                    "🔒 Seul un administrateur modifie les référentiels : "
                    "ces listes conditionnent la saisie de tous les "
                    "utilisateurs."):
        return

    df = charger()
    onglets = st.tabs([TYPES[t][0] for t in TYPES])
    for onglet, type_ref in zip(onglets, TYPES):
        libelle, description, avec_code = TYPES[type_ref]
        with onglet:
            st.caption(description)
            d_type = df[df.type == type_ref].copy()
            d_type["ordre"] = pd.to_numeric(d_type.ordre,
                                            errors="coerce").fillna(999)
            d_type = d_type.sort_values("ordre")

            # ── Ajout ────────────────────────────────────────────────
            with st.form(f"ajout_{type_ref}", clear_on_submit=True):
                c1, c2, c3 = st.columns([3, 1.4, 1])
                val = c1.text_input(f"Nouvelle valeur — {libelle.lower()}")
                code = c2.text_input(
                    "Code", help="Utilisé dans le numéro de mission "
                                 "(ex. ICT, FIN, OPS)") if avec_code else ""
                c3.markdown("<div style='height:28px'></div>",
                            unsafe_allow_html=True)
                if c3.form_submit_button("➕ Ajouter", type="primary"):
                    ok, msg = ajouter(type_ref, val, code)
                    (st.success if ok else st.error)(msg)
                    if ok:
                        st.rerun()

            # ── Modification en place ────────────────────────────────
            aff = d_type[["valeur", "code", "actif", "ordre"]] \
                if avec_code else d_type[["valeur", "actif", "ordre"]]
            edite = st.data_editor(
                aff.reset_index(drop=True), use_container_width=True,
                hide_index=True, num_rows="fixed",
                column_config={
                    "valeur": st.column_config.TextColumn("Valeur",
                                                          required=True),
                    "code": st.column_config.TextColumn("Code"),
                    "actif": st.column_config.SelectboxColumn(
                        "Actif", options=["Oui", "Non"]),
                    "ordre": st.column_config.NumberColumn("Ordre",
                                                           step=1)},
                key=f"edit_{type_ref}")
            st.caption("Passez une valeur à « Non » pour la retirer des "
                       "listes de saisie sans perdre les enregistrements "
                       "existants qui l'utilisent.")

            c1, c2 = st.columns([1, 3])
            if c1.button("💾 Enregistrer", key=f"save_{type_ref}",
                         type="primary"):
                if edite.valeur.astype(str).str.strip().eq("").any():
                    st.error("Aucune valeur ne peut être vide.")
                elif edite.valeur.astype(str).str.strip().str.lower() \
                        .duplicated().any():
                    st.error("Des valeurs sont en double.")
                else:
                    autres = df[df.type != type_ref]
                    maj = edite.copy()
                    maj["type"] = type_ref
                    if "code" not in maj.columns:
                        maj["code"] = ""
                    crud.ecrire(TABLE, pd.concat(
                        [autres, maj[COLS]], ignore_index=True))
                    st.success(f"✅ {libelle} enregistré(e)s.")
                    st.rerun()

            # ── Suppression ──────────────────────────────────────────
            with st.expander("🗑️ Supprimer des valeurs"):
                st.caption("La suppression est définitive. Préférez "
                           "« Actif : Non » si des enregistrements "
                           "existants utilisent la valeur.")
                a_sup = st.multiselect("Valeurs à supprimer",
                                       d_type.valeur.tolist(),
                                       key=f"sup_{type_ref}")
                if a_sup and st.button(f"Supprimer {len(a_sup)} valeur(s)",
                                       key=f"btn_sup_{type_ref}"):
                    reste = df[~((df.type == type_ref)
                                 & (df.valeur.isin(a_sup)))]
                    crud.ecrire(TABLE, reste)
                    st.success(f"🗑️ {len(a_sup)} valeur(s) supprimée(s).")
                    st.rerun()
