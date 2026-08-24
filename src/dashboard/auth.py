"""
Authentification et droits d'accès.

Principe : chaque compte est rattaché à un staff, dont les rôles
déterminent ce que l'utilisateur peut voir et faire. Un compte
administrateur par défaut est créé au premier lancement.

Les mots de passe ne sont jamais stockés en clair : seule une empreinte
PBKDF2-SHA256 avec sel aléatoire est conservée.
"""
import hashlib
import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from config import DATA_RAW, ROLES_STAFF
import crud

FICHIER = "comptes"
COLS = ["login", "empreinte", "staff_id", "nom_complet", "roles", "actif"]

ADMIN_DEFAUT = {"login": "admin", "mot_de_passe": "admin@123",
                "nom_complet": "Administrateur", "roles": "Admin"}

ITERATIONS = 200_000


# ══════════════════════════════════════════════════════════════════════
# Mots de passe
# ══════════════════════════════════════════════════════════════════════
def hacher(mot_de_passe: str, sel: bytes | None = None) -> str:
    sel = sel or os.urandom(16)
    emp = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"), sel,
                              ITERATIONS)
    return f"{sel.hex()}${emp.hex()}"


def verifier_mdp(mot_de_passe: str, empreinte: str) -> bool:
    try:
        sel_hex, attendu = str(empreinte).split("$", 1)
        calcule = hashlib.pbkdf2_hmac("sha256", mot_de_passe.encode("utf-8"),
                                      bytes.fromhex(sel_hex), ITERATIONS)
        return hmac.compare_digest(calcule.hex(), str(attendu))
    except (ValueError, AttributeError):
        return False


# ══════════════════════════════════════════════════════════════════════
# Comptes
# ══════════════════════════════════════════════════════════════════════
def charger_comptes() -> pd.DataFrame:
    df = crud.lire(FICHIER)
    if df is None or df.empty:
        return initialiser_comptes()
    for c in COLS:
        if c not in df.columns:
            df[c] = ""
    return df.fillna("")


def enregistrer_comptes(df: pd.DataFrame):
    crud.ecrire(FICHIER, df[COLS])


def initialiser_comptes() -> pd.DataFrame:
    """Crée le compte administrateur par défaut au premier lancement."""
    df = pd.DataFrame([{
        "login": ADMIN_DEFAUT["login"],
        "empreinte": hacher(ADMIN_DEFAUT["mot_de_passe"]),
        "staff_id": "", "nom_complet": ADMIN_DEFAUT["nom_complet"],
        "roles": ADMIN_DEFAUT["roles"], "actif": "Oui",
    }])
    enregistrer_comptes(df)
    return df


def authentifier(login: str, mot_de_passe: str) -> dict | None:
    """Retourne l'utilisateur si les identifiants sont valides, sinon None.
    Les rôles proviennent de la fiche staff quand le compte y est rattaché,
    de sorte qu'une modification des rôles s'applique immédiatement."""
    comptes = charger_comptes()
    login = str(login).strip().lower()
    ligne = comptes[comptes.login.astype(str).str.strip().str.lower() == login]
    if ligne.empty:
        return None
    c = ligne.iloc[0]
    if str(c.get("actif", "Oui")).strip().lower() == "non":
        return None
    if not verifier_mdp(mot_de_passe, c.empreinte):
        return None

    nom, roles, sid = c.nom_complet, c.roles, str(c.staff_id or "").strip()
    if sid:
        staffs = crud.lire("staffs")
        if staffs is not None and "staff_id" in staffs.columns:
            fiche = staffs[staffs.staff_id.astype(str).str.strip() == sid]
            if not fiche.empty:
                f = fiche.iloc[0]
                nom = f.get("nom_complet", nom)
                roles = f.get("roles", roles) or roles
                if str(f.get("actif", "Oui")).strip().lower() == "non":
                    return None
    return {"login": c.login, "staff_id": sid, "nom_complet": nom,
            "roles": {r.strip().lower() for r in str(roles).split(",")
                      if r.strip()} or {"user"}}


# ══════════════════════════════════════════════════════════════════════
# Droits
# ══════════════════════════════════════════════════════════════════════
# Qui peut faire quoi. « user » n'apparaît nulle part : il consulte
# uniquement, et seulement ce qui est validé.
DROITS = {
    "gerer_vehicules":   {"gestionnaire", "admin"},
    "gerer_missions":    {"gestionnaire", "admin"},
    "approuver_mission": {"approbateur", "admin"},
    "gerer_carburant":   {"gestionnaire", "admin"},
    "gerer_maintenance": {"gestionnaire", "admin"},
    "gerer_staffs":      {"admin"},
    "voir_staffs":       {"gestionnaire", "approbateur", "admin"},
    "voir_predictions":  {"gestionnaire", "approbateur", "admin"},
    "importer":          {"admin"},
    "gerer_comptes":     {"admin"},
}

# Pages visibles selon les rôles détenus
PAGES_PAR_DROIT = {
    "👥 Staffs & rôles": "voir_staffs",
    "✍️ Missions à approuver": "approuver_mission",
    "🔮 Prédictions": "voir_predictions",
    "📥 Import données réelles": "importer",
    "🔐 Comptes utilisateurs": "gerer_comptes",
    "📚 Référentiels": "gerer_comptes",
}


def utilisateur() -> dict | None:
    return st.session_state.get("utilisateur")


def roles() -> set:
    u = utilisateur()
    return u["roles"] if u else set()


def peut(action: str) -> bool:
    """Vrai si l'utilisateur connecté détient un rôle autorisant l'action."""
    return bool(roles() & DROITS.get(action, set()))


def est_admin() -> bool:
    return "admin" in roles()


def bloquer(action: str, message: str | None = None) -> bool:
    """Affiche un avertissement et retourne True si l'action est interdite."""
    if peut(action):
        return False
    st.warning(message or "🔒 Vous n'avez pas les droits pour cette action. "
                          "Contactez un administrateur.")
    return True


# ══════════════════════════════════════════════════════════════════════
# Interface
# ══════════════════════════════════════════════════════════════════════
def ecran_connexion(couleur="#E2231A") -> bool:
    """Affiche le formulaire de connexion. Retourne True si connecté."""
    if utilisateur():
        return True

    _, centre, _ = st.columns([1, 1.5, 1])
    with centre:
        st.markdown(
            f"<div style='text-align:center;padding:28px 0 6px'>"
            f"<div style='font-size:44px'>🚙</div>"
            f"<h2 style='margin:6px 0 2px;color:{couleur}'>Fleet-IA</h2>"
            f"<p style='color:#6B7785;margin:0'>Gestion prédictive de flotte"
            f"<br>World Vision Sénégal</p></div>",
            unsafe_allow_html=True)

        with st.form("connexion"):
            login = st.text_input("Identifiant")
            mdp = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", type="primary",
                                     use_container_width=True):
                u = authentifier(login, mdp)
                if u:
                    st.session_state["utilisateur"] = u
                    st.rerun()
                else:
                    st.error("Identifiant ou mot de passe incorrect.")

        comptes = charger_comptes()
        seul_admin = (len(comptes) == 1
                      and comptes.iloc[0].login == ADMIN_DEFAUT["login"])
        if seul_admin:
            st.info(f"Premier lancement — connectez-vous avec "
                    f"**{ADMIN_DEFAUT['login']}** / "
                    f"**{ADMIN_DEFAUT['mot_de_passe']}**, puis changez ce "
                    f"mot de passe dans 🔐 Comptes utilisateurs.")
    return False


def carte_utilisateur():
    """Encart de la barre latérale : qui est connecté, avec quels rôles."""
    u = utilisateur()
    if not u:
        return
    libelles = {r.lower(): r for r in ROLES_STAFF}
    roles_aff = ", ".join(libelles.get(r, r.capitalize())
                          for r in sorted(u["roles"])) or "User"
    st.sidebar.markdown(
        f"<div style='border-top:1px solid #E3E7EC;margin-top:14px;"
        f"padding-top:12px;font-size:13px;line-height:1.5'>"
        f"<div style='color:#6B7785;font-size:11px;letter-spacing:.06em;"
        f"text-transform:uppercase'>Connecté</div>"
        f"<b>{u['nom_complet']}</b><br>"
        f"<span style='color:#6B7785'>{roles_aff}</span></div>",
        unsafe_allow_html=True)
    if st.sidebar.button("Se déconnecter", use_container_width=True):
        st.session_state.pop("utilisateur", None)
        st.rerun()


def pages_autorisees(pages: dict) -> dict:
    """Filtre le menu selon les droits de l'utilisateur connecté."""
    return {nom: fn for nom, fn in pages.items()
            if nom not in PAGES_PAR_DROIT or peut(PAGES_PAR_DROIT[nom])}


# ══════════════════════════════════════════════════════════════════════
# Page de gestion des comptes (admin)
# ══════════════════════════════════════════════════════════════════════
def page_comptes(d):
    st.title("🔐 Comptes utilisateurs")
    st.caption("Module comptes v9.5 — un compte est rattaché à un staff ; "
               "ses droits découlent des rôles de sa fiche")
    if bloquer("gerer_comptes", "🔒 Seul un administrateur gère les comptes."):
        return

    comptes = charger_comptes()
    staffs = d.get("staffs")

    t_liste, t_new, t_mdp = st.tabs(["📋 Comptes", "➕ Nouveau compte",
                                     "🔑 Mot de passe"])

    with t_liste:
        aff = comptes.drop(columns=["empreinte"]).copy()
        aff["roles"] = aff.apply(
            lambda r: _roles_effectifs(r, staffs), axis=1)
        st.dataframe(aff, use_container_width=True, hide_index=True)
        st.caption(f"{len(comptes)} compte(s). Les rôles affichés sont ceux "
                   f"de la fiche staff quand le compte y est rattaché.")

        if len(comptes) > 1:
            st.divider()
            sup = st.selectbox("Désactiver ou supprimer un compte",
                               comptes.login)
            c1, c2 = st.columns(2)
            if c1.button("⏸️ Désactiver"):
                comptes.loc[comptes.login == sup, "actif"] = "Non"
                enregistrer_comptes(comptes)
                st.success(f"Compte **{sup}** désactivé.")
                st.rerun()
            if c2.button("🗑️ Supprimer"):
                st.session_state["confirm_suppr_compte"] = sup
            if st.session_state.get("confirm_suppr_compte") == sup:
                st.warning(f"⚠️ **Confirmer la suppression du compte "
                           f"{sup} ?**")
                a, b, _ = st.columns([1, 1, 3])
                if a.button("✅ Oui, supprimer", type="primary"):
                    enregistrer_comptes(comptes[comptes.login != sup])
                    del st.session_state["confirm_suppr_compte"]
                    st.rerun()
                if b.button("❌ Non"):
                    del st.session_state["confirm_suppr_compte"]
                    st.rerun()

    with t_new:
        if staffs is None or staffs.empty:
            st.info("Importez d'abord les staffs : un compte se rattache à "
                    "une fiche du personnel.")
        else:
            idx = staffs.set_index(staffs.staff_id.astype(str))
            with st.form("form_compte", clear_on_submit=True):
                c1, c2 = st.columns(2)
                sid = c1.selectbox(
                    "Staff", staffs.staff_id.astype(str),
                    format_func=lambda x: f"{x} — {idx.loc[x, 'nom_complet']} "
                                          f"({idx.loc[x, 'roles']})")
                login = c2.text_input("Identifiant de connexion",
                                      placeholder="prenom.nom")
                c3, c4 = st.columns(2)
                m1 = c3.text_input("Mot de passe", type="password")
                m2 = c4.text_input("Confirmer", type="password")
                if st.form_submit_button("Créer le compte", type="primary"):
                    login = login.strip().lower()
                    if not login or not m1:
                        st.error("Identifiant et mot de passe obligatoires.")
                    elif login in set(comptes.login.str.lower()):
                        st.error(f"L'identifiant **{login}** existe déjà.")
                    elif m1 != m2:
                        st.error("Les deux mots de passe diffèrent.")
                    elif len(m1) < 8:
                        st.error("8 caractères minimum.")
                    else:
                        f = idx.loc[sid]
                        nouveau = pd.concat([comptes, pd.DataFrame([{
                            "login": login, "empreinte": hacher(m1),
                            "staff_id": sid, "nom_complet": f.nom_complet,
                            "roles": f.get("roles", "User"), "actif": "Oui",
                        }])], ignore_index=True)
                        enregistrer_comptes(nouveau)
                        st.success(f"✅ Compte **{login}** créé pour "
                                   f"{f.nom_complet}.")
                        st.rerun()

    with t_mdp:
        with st.form("form_mdp"):
            cible = st.selectbox("Compte", comptes.login)
            c1, c2 = st.columns(2)
            n1 = c1.text_input("Nouveau mot de passe", type="password")
            n2 = c2.text_input("Confirmer", type="password")
            if st.form_submit_button("Changer le mot de passe",
                                     type="primary"):
                if n1 != n2:
                    st.error("Les deux saisies diffèrent.")
                elif len(n1) < 8:
                    st.error("8 caractères minimum.")
                else:
                    comptes.loc[comptes.login == cible,
                                "empreinte"] = hacher(n1)
                    enregistrer_comptes(comptes)
                    st.success(f"✅ Mot de passe de **{cible}** modifié.")


def _roles_effectifs(ligne, staffs):
    sid = str(ligne.get("staff_id") or "").strip()
    if sid and staffs is not None and len(staffs):
        f = staffs[staffs.staff_id.astype(str) == sid]
        if not f.empty and f.iloc[0].get("roles"):
            return f.iloc[0]["roles"]
    return ligne.get("roles", "User")
