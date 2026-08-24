"""
Page Staffs & rôles — référentiel unique du personnel.

Principe : chauffeur, approbateur, gestionnaire et admin sont des RÔLES
attribuables et retirables à n'importe quel staff, pas des tables séparées.
- chauffeur     : peut être affecté à la conduite d'une mission
- approbateur   : peut approuver les ordres de mission
- gestionnaire  : peut créer les missions
- admin         : tous les droits (dont la gestion des rôles)

À la première utilisation, les chauffeurs existants (chauffeurs.csv) sont
migrés automatiquement en staffs avec le rôle « chauffeur », en CONSERVANT
leurs identifiants (CH-xxx) pour ne pas casser l'historique des missions.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from config import (DEPARTEMENTS, ROLES_STAFF, ROLE_DEFAUT,
                    DESCRIPTION_ROLES, CENTRES_SERVICE, LOCALITES, DATA_RAW)
from crud import lire, ecrire, prochain_id
import auth
import ui
import referentiels

# staff_id = numéro d'employé World Vision (Employee number) : il existe
# déjà pour chaque agent, il n'est donc jamais généré.
COLS_STAFF = ["staff_id", "nom_complet", "externe", "email", "departement", "fonction",
              "telephone", "centre_service", "localite", "roles",
              "date_permis", "actif"]


def initialiser_staffs() -> pd.DataFrame | None:
    """Crée staffs.csv depuis chauffeurs.csv si absent. Retourne la table."""
    staffs = lire("staffs.csv")
    if staffs is not None:
        return staffs
    ch = lire("chauffeurs.csv")
    if ch is None or ch.empty:
        return None
    centre_par_loc = {}
    for c, l in CENTRES_SERVICE.items():
        centre_par_loc.setdefault(l, c)
    staffs = pd.DataFrame({
        "staff_id": ch.chauffeur_id,
        "nom_complet": ch.nom_complet,
        "departement": "Operations",
        "fonction": "Chauffeur",
        "telephone": "",
        "centre_service": ch.localite.map(centre_par_loc).fillna("Dakar"),
        "localite": ch.localite,
        "email": "",
        "roles": "User, Chauffeur",
        "date_permis": ch.get("date_permis", ""),
        "actif": "Oui",
    })
    ecrire("staffs.csv", staffs)
    return staffs


def roles_de(row) -> set:
    return {r.strip() for r in str(row.get("roles", "") or "").split(",")
            if r.strip()}


def staffs_avec_role(staffs: pd.DataFrame, role: str) -> pd.DataFrame:
    if staffs is None or staffs.empty:
        return pd.DataFrame(columns=COLS_STAFF)
    m = staffs.roles.astype(str).str.contains(rf"\b{role}\b", na=False,
                                              case=False)
    if "actif" in staffs.columns:
        m &= staffs.actif.astype(str).str.strip().str.lower() != "non"
    return staffs[m]


def _est_admin() -> bool:
    """La gestion du personnel est réservée aux administrateurs :
    un gestionnaire consulte les fiches mais ne les modifie pas."""
    return auth.peut("gerer_staffs")


# ══════════════════════════════════════════════════════════════════════
def page_staffs(d):
    ui.titre_page("Gestion des staffs & rôles", "👥")
    st.caption("Module staffs v10.6 — matricule employé comme identifiant, "
               "rôle « User » par défaut")
    staffs = d.get("staffs")

    if staffs is not None and len(staffs):
        c0, c1, c2, c3, c4 = st.columns(5)
        n_ext = int(staffs.get("externe", pd.Series(dtype=str))
                    .astype(str).str.strip().str.lower().eq("oui").sum())
        c0.metric("👥 Personnes", len(staffs),
                  f"dont {n_ext} externe(s)" if n_ext else None,
                  delta_color="off")
        c1.metric("🧑‍✈️ Chauffeurs", len(staffs_avec_role(staffs, "chauffeur")))
        c2.metric("✍️ Approbateurs", len(staffs_avec_role(staffs, "approbateur")))
        c3.metric("🗂️ Gestionnaires", len(staffs_avec_role(staffs, "gestionnaire")))
        c4.metric("🛡️ Admins", len(staffs_avec_role(staffs, "admin")))
        with st.expander("ℹ️ Que permet chaque rôle ?"):
            for r, desc in DESCRIPTION_ROLES.items():
                st.markdown(f"- **{r}** — {desc}")

    t_new, t_liste, t_masse = st.tabs(
        ["➕ Nouveau staff", "📋 Liste / Rôles / Modifier",
         "☑️ Actions en masse"])

    # ── ➕ NOUVEAU ─────────────────────────────────────────────────────
    with t_new:
        if not _est_admin():
            st.warning("🔒 Seul un administrateur peut créer des staffs.")
        else:
            with st.form("form_staff", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                sid = c1.text_input("N° employé (matricule) *",
                                    placeholder="10027846",
                                    help="Employee number World Vision : il "
                                         "identifie le staff de manière unique.")
                nom = c2.text_input("Nom complet *")
                email = c3.text_input("Email professionnel",
                                      placeholder="prenom_nom@wvi.org")
                c4, c5, c6 = st.columns(3)
                dep = c4.selectbox("Département / Unité *",
                                   referentiels.liste("departement")
                                   or list(DEPARTEMENTS))
                fonc = c5.text_input("Fonction / Poste",
                                     placeholder="ICT Coordinator")
                tel = c6.text_input("Téléphone", placeholder="+221 77 123 45 67")
                c7, c8, c9 = st.columns([2, 2, 1.6])
                centre = c7.selectbox("Centre de service *",
                                      list(CENTRES_SERVICE.keys()))
                permis = c8.text_input("Date permis (si chauffeur, AAAA-MM-JJ)",
                                       "")
                externe = c9.checkbox(
                    "Collaborateur externe",
                    help="Personne ne faisant pas partie du personnel : "
                         "consultant, partenaire, accompagnant. Elle "
                         "apparaîtra suivie de « (Externe) » sur les ordres "
                         "de mission.")
                roles = st.multiselect(
                    "Rôles", ROLES_STAFF, default=[ROLE_DEFAUT],
                    help="« User » est le rôle par défaut : le staff peut "
                         "partir en mission sans droit de gestion.")
                if st.form_submit_button("Enregistrer le staff", type="primary"):
                    sid = sid.strip()
                    deja = set(staffs.staff_id.astype(str)) \
                        if staffs is not None and len(staffs) else set()
                    if externe and not sid:
                        # Un externe n'a pas de matricule : on en génère un
                        sid = prochain_id(staffs, "staff_id", "EXT-", 4)
                    if not sid or not nom.strip():
                        st.error("Le n° d'employé et le nom sont obligatoires. "
                                 "Pour un externe, le matricule peut rester "
                                 "vide : il sera généré.")
                    elif sid in deja:
                        st.error(f"❌ Le matricule **{sid}** existe déjà.")
                    else:
                        ligne = {"staff_id": sid, "nom_complet": nom.strip(),
                                 "email": email.strip(),
                                 "departement": dep, "fonction": fonc.strip(),
                                 "telephone": tel.strip(),
                                 "centre_service": centre,
                                 "localite": CENTRES_SERVICE[centre],
                                 "roles": ", ".join(roles or [ROLE_DEFAUT]),
                                 "date_permis": permis.strip(),
                                 "externe": "Oui" if externe else "Non",
                                 "actif": "Oui"}
                        nouveau = pd.concat(
                            [staffs if staffs is not None else pd.DataFrame(),
                             pd.DataFrame([ligne])], ignore_index=True)
                        ecrire("staffs.csv", nouveau)
                        st.success(f"✅ Staff **{sid}** ({nom}) créé — rôles : "
                                   f"{', '.join(roles or [ROLE_DEFAUT])}.")
                        st.rerun()

    # ── 📋 LISTE / RÔLES ──────────────────────────────────────────────
    with t_liste:
        if staffs is None or staffs.empty:
            st.info("Aucun staff. Les chauffeurs existants seront migrés "
                    "automatiquement au prochain rechargement.")
            return

        c1, c2, c3 = st.columns([2, 2, 2])
        q = c1.text_input("🔍 Recherche (nom, ID, fonction)")
        f_dep = c2.multiselect("Département", DEPARTEMENTS)
        f_role = c3.multiselect("Rôle", ROLES_STAFF)
        v = staffs.copy()
        if q.strip():
            ql = q.strip().lower()
            masque = pd.Series(False, index=v.index)
            for col in ["nom_complet", "staff_id", "fonction"]:
                masque |= v[col].astype(str).str.lower().str.contains(ql, na=False)
            v = v[masque]
        if f_dep:
            v = v[v.departement.isin(f_dep)]
        for r in f_role:
            v = v[v.roles.astype(str).str.contains(rf"\b{r}\b", na=False)]

        st.caption("👆 **Cliquez sur une ligne** pour modifier le staff "
                   "et ses rôles.")
        vv = v.reset_index(drop=True)
        sel = []
        try:
            ev = st.dataframe(vv, use_container_width=True, hide_index=True,
                              on_select="rerun", selection_mode="single-row",
                              key=f"tbl_staff_{len(vv)}_{q}")
            sel = list(ev.selection.rows)
        except TypeError:
            st.dataframe(vv, use_container_width=True, hide_index=True)
        st.caption(f"{len(v)} staff(s)")

        if sel:
            ligne = vv.iloc[sel[0]]
            sid = ligne.staff_id
            st.divider()
            st.subheader(f"✏️ {sid} — {ligne.nom_complet}")
            peut_modifier = _est_admin()
            if not peut_modifier:
                st.info("🔒 Modification et gestion des rôles réservées aux "
                        "**admins** (lecture seule).")

            with st.form(f"form_edit_staff_{sid}"):
                c1, c2, c3 = st.columns(3)
                nom = c1.text_input("Nom complet *", ligne.nom_complet)
                dep = c2.selectbox("Département / Unité", DEPARTEMENTS,
                                   DEPARTEMENTS.index(ligne.departement)
                                   if ligne.departement in DEPARTEMENTS else 8)
                fonc = c3.text_input("Fonction", str(ligne.get("fonction", "") or ""))
                c4, c5, c6 = st.columns(3)
                tel = c4.text_input("Téléphone", str(ligne.get("telephone", "") or ""))
                centres = list(CENTRES_SERVICE.keys())
                centre = c5.selectbox("Centre de service", centres,
                                      centres.index(ligne.centre_service)
                                      if ligne.centre_service in centres else 0)
                permis = c6.text_input("Date permis",
                                       str(ligne.get("date_permis", "") or ""))
                externe_m = st.checkbox(
                    "Collaborateur externe",
                    value=str(ligne.get("externe", "")).strip().lower() == "oui",
                    key="ext_mod")
                roles = st.multiselect("Rôles", ROLES_STAFF,
                                       [r for r in roles_de(ligne)
                                        if r in ROLES_STAFF])
                if st.form_submit_button("💾 Enregistrer", type="primary",
                                         disabled=not peut_modifier):
                    staffs2 = staffs.copy()
                    m = staffs2.staff_id == sid
                    staffs2.loc[m, ["nom_complet", "departement", "fonction",
                                    "telephone", "centre_service", "localite",
                                    "roles", "date_permis"]] = [
                        nom.strip(), dep, fonc.strip(), tel.strip(), centre,
                        CENTRES_SERVICE[centre], ",".join(roles),
                        permis.strip()]
                    ecrire("staffs.csv", staffs2)
                    st.success(f"✅ **{sid}** mis à jour — rôles : "
                               f"{', '.join(roles) or 'aucun'}.")
                    st.rerun()

            if peut_modifier:
                if st.button(f"🗑️ Supprimer le staff {sid}"):
                    st.session_state["confirm_suppr_staff"] = sid
                if st.session_state.get("confirm_suppr_staff") == sid:
                    st.warning(f"⚠️ **Voulez-vous confirmer la suppression de "
                               f"{sid} ({ligne.nom_complet}) ?** Son historique "
                               f"de missions est conservé.")
                    c1, c2, _ = st.columns([1, 1, 3])
                    if c1.button("✅ Oui, supprimer", type="primary",
                                 key="oui_st"):
                        ecrire("staffs.csv", staffs[staffs.staff_id != sid])
                        del st.session_state["confirm_suppr_staff"]
                        st.rerun()
                    if c2.button("❌ Non, annuler", key="non_st"):
                        del st.session_state["confirm_suppr_staff"]
                        st.rerun()

    # ══ ACTIONS EN MASSE ═════════════════════════════════════════════
    with t_masse:
        if staffs is None or staffs.empty:
            st.info("Aucun staff.")
        elif not _est_admin():
            st.warning("🔒 Les actions en masse sont réservées aux "
                       "administrateurs.")
        else:
            c1, c2 = st.columns(2)
            f_dep2 = c1.multiselect(
                "Filtrer par département",
                sorted(staffs.departement.dropna().unique()), key="mdep")
            f_ctr2 = c2.multiselect(
                "Filtrer par centre",
                sorted(staffs.get("centre_service",
                                  pd.Series(dtype=str)).dropna().unique()),
                key="mctr")
            base = staffs.copy()
            if f_dep2:
                base = base[base.departement.isin(f_dep2)]
            if f_ctr2:
                base = base[base.centre_service.isin(f_ctr2)]

            sel = ui.selection_multiple(
                base, ["staff_id", "nom_complet", "departement",
                       "centre_service", "roles", "actif"],
                "sel_staffs",
                "☑️ Cochez les staffs concernés, puis choisissez l'action.")
            n = len(sel)
            st.caption(f"**{n}** staff(s) sélectionné(s) sur {len(base)}.")

            if n:
                st.divider()
                st.markdown("**Attribuer ou retirer des rôles**")
                c1, c2 = st.columns([3, 1.4])
                roles_c = c1.multiselect("Rôles concernés", ROLES_STAFF,
                                         key="mroles")
                mode = c2.radio("Action", ["Ajouter", "Retirer", "Remplacer"],
                                key="mmode")
                if roles_c and st.button(f"Appliquer aux {n} staff(s)",
                                         type="primary", key="mapply"):
                    s2 = staffs.copy()
                    for sid in sel.staff_id:
                        m = s2.staff_id.astype(str) == str(sid)
                        actuels = {r.strip() for r in
                                   str(s2.loc[m, "roles"].iloc[0] or "")
                                   .split(",") if r.strip()}
                        if mode == "Ajouter":
                            nouveaux = actuels | set(roles_c)
                        elif mode == "Retirer":
                            nouveaux = actuels - set(roles_c)
                        else:
                            nouveaux = set(roles_c)
                        s2.loc[m, "roles"] = ", ".join(
                            [r for r in ROLES_STAFF
                             if r in nouveaux]) or "User"
                    ecrire("staffs.csv", s2)
                    st.success(f"✅ Rôles mis à jour pour {n} staff(s) "
                               f"({mode.lower()} : {', '.join(roles_c)}).")
                    st.rerun()

                st.divider()
                st.markdown("**Activer ou désactiver**")
                c1, c2 = st.columns(2)
                if c1.button(f"⏸️ Désactiver les {n} sélectionné(s)",
                             key="mdesac"):
                    s2 = staffs.copy()
                    s2.loc[s2.staff_id.isin(sel.staff_id), "actif"] = "Non"
                    ecrire("staffs.csv", s2)
                    st.success(f"✅ {n} staff(s) désactivé(s).")
                    st.rerun()
                if c2.button(f"▶️ Réactiver les {n} sélectionné(s)",
                             key="mreac"):
                    s2 = staffs.copy()
                    s2.loc[s2.staff_id.isin(sel.staff_id), "actif"] = "Oui"
                    ecrire("staffs.csv", s2)
                    st.success(f"✅ {n} staff(s) réactivé(s).")
                    st.rerun()

                st.divider()
                st.markdown("**Supprimer**")
                st.caption("La désactivation est préférable : elle conserve "
                           "l'historique des missions de ces agents.")
                if ui.confirmer_action(
                        "suppr_staffs",
                        f"🗑️ Supprimer les {n} sélectionné(s)", n,
                        "Leur historique de missions restera en base mais ne "
                        "sera plus rattaché à un agent."):
                    ecrire("staffs.csv",
                           staffs[~staffs.staff_id.isin(sel.staff_id)])
                    st.success(f"🗑️ {n} staff(s) supprimé(s).")
                    st.rerun()
