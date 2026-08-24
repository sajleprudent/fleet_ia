"""
Page Missions v8.7 — workflow d'approbation + CRUD complet.

Workflow statut :
  Draft (affiché grisé à la saisie) → Pending (à l'enregistrement)
  → Approved (par l'approbateur, avec date d'approbation)
  → Rejected (refus) | Canceled (annulation gestionnaire, reste listée)

Nouveautés v8.7 :
  - Aperçu de l'ordre de mission avant génération du PDF
  - PDF séparés : ordre de mission seul / feuille(s) de route seule(s) / complet
  - Modifier (formulaire pré-rempli) et supprimer (confirmation oui/non)
  - Champs techniques IA (part de piste, taux de charge) déplacés dans un
    volet optionnel avec explications
"""
import sys
from datetime import date, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from config import (IMPUTATIONS_MISSION, CENTRES_SERVICE, DEPARTEMENTS,
                    CODES_DEPT)
from crud import ecrire, lire, prochain_id
from staffs_page import staffs_avec_role
import auth
import ui
import referentiels

WV_ROUGE = "#E2231A"
STATUTS = ["Draft", "Pending", "Approved", "Rejected", "Canceled"]
COULEUR_STATUT = {"Draft": "gray", "Pending": "orange", "Approved": "green",
                  "Rejected": "red", "Canceled": "gray"}


def _norm_statut(s) -> str:
    """Normalise les anciens statuts français vers le workflow v8.7."""
    return {"Soumise": "Pending", "Approuvée": "Approved",
            "Terminée": "Approved", "Annulée": "Canceled"}.get(
        str(s or "").strip(), str(s or "Pending").strip() or "Pending")


def _numero_mission(mis, departement, d):
    """WVS-{code département}-{date}-{séquence 0001..9999}."""
    code = CODES_DEPT.get(departement, "GEN")
    seq = 1
    if mis is not None and "numero_mission" in mis.columns:
        nums = mis.numero_mission.dropna().astype(str) \
                  .str.extract(r"-(\d{4})$")[0].dropna()
        if len(nums):
            seq = (int(nums.astype(int).max()) % 9999) + 1
    return f"WVS-{code}-{pd.Timestamp(d):%Y-%m-%d}-{seq:04d}"


def pers_default_ok(ids, idx_staff):
    """Ne conserve que les identifiants présents dans le référentiel."""
    dispo = {str(i) for i in idx_staff.index}
    return [i for i in ids if str(i) in dispo]


def _date_defaut():
    """Date proposée à la création : celle cliquée dans le calendrier,
    sinon aujourd'hui."""
    d = (st.session_state.get("date_mission_calendrier")
         or st.session_state.get("date_mission_prevue"))
    return d if d else date.today()


def _ix(options, val, defaut=0):
    options = list(options)
    if val in options:
        return options.index(val)
    txt = [str(o) for o in options]           # comparaison en texte
    return txt.index(str(val)) if str(val) in txt else defaut


# ══════════════════════════════════════════════════════════════════════
# Formulaire mission réutilisable (création ET modification)
# ══════════════════════════════════════════════════════════════════════
def _form_mission(cle, refs, v=None):
    (staffs, veh, chauffeurs_staff, approbateurs,
     idx_staff, idx_veh, lib_staff, lib_veh) = refs
    v = v or {}
    edition = bool(v)

    d0 = pd.to_datetime(v.get("date_depart"), errors="coerce")
    f0 = pd.to_datetime(v.get("date_fin"), errors="coerce")

    # Le formulaire ne se vide QUE si l'enregistrement a réussi. Streamlit
    # vide un formulaire dès sa soumission, avant toute validation : pour
    # conserver la saisie en cas d'erreur, les widgets portent une clé
    # versionnée, incrémentée uniquement après un enregistrement réussi.
    nonce = st.session_state.get(f"nonce_{cle}", 0)
    k = f"{cle}_{nonce}"

    # Le trajet est saisi HORS du formulaire : Streamlit ne réévalue pas
    # le contenu d'un formulaire tant qu'il n'est pas soumis, or la
    # distance doit se recalculer dès que l'on change origine ou
    # destination.
    # Le formulaire ne doit PAS se vider quand la validation échoue : la
    # saisie en cours reste affichée jusqu'à correction. On renonce donc à
    # clear_on_submit, et on force le renouvellement des widgets — via un
    # compteur intégré à leurs clés — seulement après un enregistrement
    # réussi.
    nonce = st.session_state.get(f"nonce_{cle}", 0)
    k = f"{cle}_{nonce}"

    centres = list(CENTRES_SERVICE.keys())
    st.markdown("**Trajet**")
    ct1, ct2, ct3 = st.columns([2, 2, 2])
    origine = ct1.selectbox("Origine *", centres,
                            _ix(centres, v.get("origine")),
                            key=f"{k}_ori")
    dest = ct2.selectbox("Destination *", centres,
                         _ix(centres, v.get("destination"), 1),
                         key=f"{k}_dest")
    aller = ui.distance_aller(origine, dest)
    trajet = ct3.radio("Type de trajet", ["Aller-retour", "Aller simple"],
                       horizontal=True, key=f"{k}_ar",
                       help="Détermine la distance proposée : l'aller "
                            "simple pour un déplacement sans retour "
                            "immédiat, l'aller-retour sinon.")
    dist_ref = aller * (2 if trajet == "Aller-retour" else 1)
    dist_proposee = float(v.get("distance_km") or 0) if edition else 0.0
    if not dist_proposee:
        dist_proposee = float(dist_ref)
    if aller:
        libelle = "A/R" if trajet == "Aller-retour" else "aller simple"
        ct3.metric(f"Distance proposée ({libelle})", f"{dist_ref} km",
                   f"{aller} km par trajet", delta_color="off")
    elif origine != dest:
        ct3.warning("Distance inconnue pour ce trajet : saisissez-la.")

    with st.form(k, clear_on_submit=False):
        st.markdown("**Mission**")
        c1, c2, c3, c4 = st.columns(4)
        objet = c1.text_input("Objet *", v.get("objet", "") or "",
                              placeholder="Visite IT", key=f"{k}_objet")
        deps = referentiels.liste("departement") or list(DEPARTEMENTS)
        imputs = (referentiels.liste("imputation")
                  or list(IMPUTATIONS_MISSION))
        dep = c2.selectbox("Département / Unité *", deps,
                           _ix(deps, v.get("departement")), key=f"{k}_dep")
        imput = c3.selectbox("Imputation *", imputs,
                             _ix(imputs, v.get("imputation")), key=f"{k}_imput")
        c4.text_input("Statut", _norm_statut(v.get("statut", "Draft"))
                      if edition else "Draft", disabled=True,
                      help="Draft à la saisie → Pending à l'enregistrement → "
                           "Approved/Rejected par l'approbateur. Le statut se "
                           "gère depuis la fiche mission (Historique).")

        st.markdown("**Agent, personnes à bord & approbation**")
        c1, c2, c3 = st.columns(3)
        agent_id = c1.selectbox("Agent principal *", staffs.staff_id,
                                _ix(staffs.staff_id, v.get("agent_id")),
                                format_func=lib_staff, key=f"{k}_agent")
        ids_ok = set(staffs.staff_id)
        pers_def = [i.strip() for i in str(v.get("personnes_ids", "") or "")
                    .split(",") if i.strip() in ids_ok]
        pers_ids = c2.multiselect("Personnes à bord", list(staffs.staff_id),
                                  default=pers_def, format_func=lib_staff,
                                  help="L'agent principal est ajouté "
                                       "automatiquement.", key=f"{k}_pers")
        approb_id = None
        if len(approbateurs):
            approb_id = c3.selectbox("Approbateur désigné *",
                                     approbateurs.staff_id,
                                     _ix(approbateurs.staff_id,
                                         v.get("approbateur_id")),
                                     format_func=lib_staff, key=f"{k}_approb")
        else:
            c3.warning("Aucun staff n'a le rôle « approbateur » "
                       "(page 👥 Staffs).")

        st.markdown("**Trajet & période**")
        c1, c2, c3, c4 = st.columns(4)
        # Une mission se planifie : pas de création dans le passé.
        # La modification reste libre, pour corriger un historique.
        dd = c1.date_input("Date départ *",
                           d0.date() if pd.notna(d0) else _date_defaut(),
                           min_value=None if edition else date.today(),
                           key=f"{k}_dd")
        hd = c2.time_input("Heure départ",
                           d0.time() if pd.notna(d0) else time(7, 0), key=f"{k}_hd")
        df_ = c3.date_input("Date retour *",
                            f0.date() if pd.notna(f0)
                            else _date_defaut() + timedelta(days=1),
                            min_value=None if edition else dd,
                            key=f"{k}_df")
        hf = c4.time_input("Heure retour",
                           f0.time() if pd.notna(f0) else time(18, 0), key=f"{k}_hf")
        c5, c6 = st.columns(2)
        dist = c5.number_input(
            "Distance A/R (km) *", 0.0, 4000.0, float(dist_proposee), 10.0,
            help="Proposée d'après le trajet sélectionné ci-dessus. "
                 "Corrigez-la si l'itinéraire réel diffère.", key=f"{k}_dist")
        obs = c6.text_input("Observations", v.get("observations", "") or "", key=f"{k}_obs")

        st.markdown("**Affectation**")
        c1, c2 = st.columns(2)
        vid = c1.selectbox("Véhicule *", veh.vehicule_id,
                           _ix(veh.vehicule_id, v.get("vehicule_id")),
                           format_func=lib_veh, key=f"{k}_vid")
        # Une motocyclette ne convient qu'aux courts trajets et à une
        # seule personne : le gestionnaire doit confirmer ce choix.
        est_moto = str(idx_veh.loc[vid].get("type_vehicule")
                       if vid in idx_veh.index else "").strip().lower() \
            .startswith("moto")
        confirme_moto = True
        if est_moto:
            st.warning(
                "🏍️ **Ce véhicule est une motocyclette.** Elle ne convient "
                "qu'aux trajets courts et ne transporte qu'une seule "
                "personne, sans matériel volumineux. Vérifiez la distance "
                "et le nombre de personnes à bord.")
            confirme_moto = st.checkbox(
                "Je confirme l'affectation d'une moto pour cette mission",
                key=f"{k}_moto")

        cid = None
        if len(chauffeurs_staff):
            cid = c2.selectbox("Chauffeur *", chauffeurs_staff.staff_id,
                               _ix(chauffeurs_staff.staff_id,
                                   v.get("chauffeur_id")),
                               format_func=lib_staff, key=f"{k}_chauf")
        else:
            c2.warning("Aucun staff n'a le rôle « chauffeur ».")

        with st.expander("⚙️ Paramètres techniques pour les modèles IA "
                         "(optionnels — valeurs par défaut raisonnables)"):
            st.caption(
                "Ces deux champs ne figurent pas sur l'ordre de mission : ils "
                "alimentent les modèles de prédiction (consommation, usure, "
                "risque de panne) et le score d'exposition des chauffeurs.")
            c1, c2 = st.columns(2)
            piste_pct = c1.slider(
                "Part de piste (%)", 0, 100,
                int(float(v.get("part_piste", 0.3) or 0.3) * 100), 5,
                help="Proportion du trajet effectuée sur route NON bitumée "
                     "(piste, latérite). Ex. : Dakar→Kaffrine ≈ 10-20 % ; "
                     "tournée en Casamance rurale ≈ 60-80 %. La piste augmente "
                     "la consommation (~+20 %) et l'usure du véhicule.", key=f"{k}_piste")
            charge_pct = c2.slider(
                "Taux de charge (%)", 0, 100,
                int(float(v.get("taux_charge", 0.5) or 0.5) * 100), 5,
                help="Niveau de chargement du véhicule : passagers + matériel, "
                     "par rapport à sa capacité. Ex. : 2 personnes sans "
                     "matériel ≈ 30 % ; véhicule plein pour une distribution "
                     "≈ 90-100 %. La charge augmente la consommation.", key=f"{k}_charge")

        lib = "💾 Enregistrer les modifications" if edition \
            else "Enregistrer la mission"
        if st.form_submit_button(lib, type="primary"):
            if not objet.strip():
                st.error("L'objet est obligatoire.")
            elif origine == dest:
                st.error("L'origine et la destination doivent différer.")
            elif not edition and dd < date.today():
                st.error(f"❌ Le départ est fixé au {dd:%d/%m/%Y}, une date "
                         f"déjà passée. Une mission ne peut pas être créée "
                         f"rétroactivement ; corrigez la date de départ.")
            elif not edition and dd < date.today():
                st.error(f"❌ Le départ est fixé au {dd:%d/%m/%Y}, une date "
                         f"déjà passée. Une mission se planifie : choisissez "
                         f"aujourd'hui ou une date à venir.")
            elif not ui.controler_periode(dd, hd, df_, hf)[0]:
                st.error("❌ " + ui.controler_periode(dd, hd, df_, hf)[1])
            elif dist <= 0:
                st.error("La distance doit être renseignée (en kilomètres).")
            elif est_moto and not confirme_moto:
                st.error("🏍️ Confirmez l'affectation d'une motocyclette, ou "
                         "choisissez un autre véhicule.")
            elif est_moto and len([i for i in pers_ids
                                   if str(i) != str(agent_id)]) > 0:
                st.error("🏍️ Une motocyclette ne transporte qu'une seule "
                         "personne : retirez les passagers, ou choisissez "
                         "un autre véhicule.")
            elif est_moto and dist > 200:
                st.error(f"🏍️ {dist:.0f} km en motocyclette : distance trop "
                         f"importante. Choisissez un autre véhicule.")
            elif cid is None or approb_id is None:
                st.error("Il faut au moins un chauffeur et un approbateur "
                         "(attribuez les rôles dans 👥 Staffs).")
            else:
                agent = idx_staff.loc[agent_id]
                # Les matricules peuvent être numériques : on force le texte
                ids = [str(agent_id)] + [str(i) for i in pers_ids
                                         if str(i) != str(agent_id)]
                noms = [ui.nom_personne(idx_staff.loc[i])
                        for i in pers_default_ok(ids, idx_staff)]
                return {
                    "objet": objet.strip(), "departement": dep,
                    "imputation": imput,
                    "agent_principal": ui.nom_personne(agent),
                    "agent_id": agent_id,
                    "fonction_agent": agent.get("fonction", ""),
                    "telephone_agent": agent.get("telephone", ""),
                    "personnes_a_bord": ", ".join(noms),
                    "personnes_ids": ",".join(ids),
                    "approbateur": idx_staff.loc[approb_id, "nom_complet"],
                    "approbateur_id": approb_id,
                    "vehicule_id": vid, "chauffeur_id": cid,
                    "origine": origine, "destination": dest,
                    "date_depart": f"{dd} {hd}", "date_fin": f"{df_} {hf}",
                    "duree_jours": ui.duree_jours(dd, hd, df_, hf),
                    "distance_km": float(dist),
                    "part_piste": piste_pct / 100,
                    "taux_charge": charge_pct / 100,
                    "observations": obs.strip(),
                }
    return None


# ══════════════════════════════════════════════════════════════════════
# Aperçu HTML de l'ordre de mission
# ══════════════════════════════════════════════════════════════════════
def _apercu_ordre(r: dict):
    g = lambda k: ("—" if r.get(k) in (None, "") or
                   (isinstance(r.get(k), float) and pd.isna(r.get(k)))
                   else str(r.get(k)))
    with st.container(border=True):
        st.markdown(
            "<div style='text-align:right;font-weight:700;font-size:1.1em'>"
            "World Vision <span style='color:#F58220'>✦</span></div>"
            "<h3 style='text-align:center;margin-top:0'>ORDRE DE MISSION</h3>",
            unsafe_allow_html=True)
        cg, cd = st.columns(2)
        with cg:
            st.markdown(
                f"| | |\n|---|---|\n"
                f"| **N° de mission** | {g('numero_mission')} |\n"
                f"| **Statut** | {_norm_statut(r.get('statut'))} |\n"
                f"| **Objet** | {g('objet')} |\n"
                f"| **Imputation** | {g('imputation')} |\n"
                f"| **Département** | {g('departement')} |")
        with cd:
            st.markdown(
                f"| | |\n|---|---|\n"
                f"| **Agent principal** | {g('agent_principal')} |\n"
                f"| **Fonction / Tél.** | {g('fonction_agent')} / "
                f"{g('telephone_agent')} |\n"
                f"| **Trajet** | {g('origine')} → {g('destination')} |\n"
                f"| **Période** | {g('date_depart')} → {g('date_fin')} |\n"
                f"| **Véhicule / Chauffeur** | {g('vehicule_id')} / "
                f"{g('chauffeur_id')} |")
        st.markdown(
            f"**Personnes à bord :** {g('personnes_a_bord')}  \n"
            f"**Observations :** {g('observations')}")
        st.markdown(
            f"<div style='border:1px solid #999;border-radius:6px;"
            f"padding:8px 12px'><b>Approbateur</b> : {g('approbateur')}"
            f"<br>Date d'approbation : {g('date_approbation')}"
            f"<br>Signature : ______________________</div>",
            unsafe_allow_html=True)


JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
            "dimanche"]
MOIS_FR = ["", "janvier", "février", "mars", "avril", "mai", "juin",
           "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


def _date_fr(d) -> str:
    """« jeudi 27 août 2026 » — le formatage système reste en anglais."""
    return (f"{JOURS_FR[d.weekday()].capitalize()} {d.day} "
            f"{MOIS_FR[d.month]} {d.year}")


def _calendrier_missions(mis, veh, idx_veh, refs=None):
    """Vue mensuelle : chaque jour affiche le nombre de missions et
    permet d'ouvrir la saisie d'une mission à cette date."""
    import calendar as cal

    aujourdhui = date.today()
    ref = st.session_state.get("cal_mois", date(aujourdhui.year,
                                                aujourdhui.month, 1))
    c1, c2, c3, c4 = st.columns([1, 1, 3, 2])
    if c1.button("◀ Mois précédent", key="cal_prec"):
        st.session_state["cal_mois"] = (ref - timedelta(days=1)).replace(day=1)
        st.rerun()
    if c2.button("Mois suivant ▶", key="cal_suiv"):
        jours_mois = cal.monthrange(ref.year, ref.month)[1]
        st.session_state["cal_mois"] = (ref + timedelta(days=jours_mois)) \
            .replace(day=1)
        st.rerun()
    c3.markdown(f"### {MOIS_FR[ref.month].capitalize()} {ref.year}")
    if c4.button("📍 Revenir au mois courant", key="cal_auj"):
        st.session_state["cal_mois"] = date(aujourdhui.year,
                                            aujourdhui.month, 1)
        st.rerun()

    # Occupation : une mission occupe tous les jours de sa période
    occupation, details = {}, {}
    if mis is not None and len(mis):
        m = mis.copy()
        m["statut"] = m.get("statut", "Pending").map(_norm_statut)
        m = m[~m.statut.isin(["Canceled", "Rejected"])]
        for r in m.itertuples():
            d1 = pd.to_datetime(getattr(r, "date_depart", None),
                                errors="coerce")
            if pd.isna(d1):
                continue
            d2 = pd.to_datetime(getattr(r, "date_fin", None), errors="coerce")
            if pd.isna(d2) or d2 < d1:
                d2 = d1
            for j in pd.date_range(d1.normalize(), d2.normalize(), freq="D"):
                cle = j.date()
                occupation[cle] = occupation.get(cle, 0) + 1
                details.setdefault(cle, []).append(
                    f"{getattr(r, 'numero_mission', '')} · "
                    f"{getattr(r, 'origine', '')} → "
                    f"{getattr(r, 'destination', '')} · "
                    f"{getattr(r, 'vehicule_id', '')}")

    choisi = st.session_state.get("cal_jour_detail")
    if choisi:
        st.divider()
        st.markdown(f"#### 📌 {_date_fr(choisi)}")
        occ = details.get(choisi, [])
        if occ:
            st.markdown("**Missions déjà programmées ce jour :**")
            for x in occ:
                st.markdown(f"- {x}")
        else:
            st.success("Aucune mission ce jour : les véhicules sont "
                       "disponibles.")
        st.info(f"📝 La date du **{choisi:%d/%m/%Y}** est pré-remplie "
                f"ci-dessous et dans l'onglet **➕ Nouvelle mission**.")
        if st.button("Effacer la sélection", key="cal_clear"):
            st.session_state.pop("date_mission_calendrier", None)
            st.session_state.pop("date_mission_prevue", None)
            st.session_state.pop("cal_jour_detail", None)
            st.rerun()

        # Saisie directe depuis le calendrier : évite d'avoir à changer
        # d'onglet après avoir cliqué sur une date.
        if choisi < aujourdhui:
            st.warning("⚠️ Cette date est passée : la création de mission "
                       "n'est possible qu'à partir d'aujourd'hui.")
        elif refs is not None and auth.peut("gerer_missions"):
            with st.expander(f"➕ Créer une mission le {_date_fr(choisi)}",
                             expanded=True):
                valeurs = _form_mission("form_cal_mission", refs)
                if valeurs:
                    mis_a = lire("missions.csv")
                    numero = _numero_mission(mis_a, valeurs["departement"],
                                             valeurs["date_depart"][:10])
                    ligne = {"numero_mission": numero, "statut": "Pending",
                             "date_approbation": "", **valeurs}
                    ecrire("missions.csv", pd.concat(
                        [mis_a if mis_a is not None else pd.DataFrame(),
                         pd.DataFrame([ligne])], ignore_index=True))
                    st.session_state["nonce_form_cal_mission"] = \
                        st.session_state.get("nonce_form_cal_mission", 0) + 1
                    st.session_state.pop("date_mission_calendrier", None)
                    st.session_state.pop("date_mission_prevue", None)
                    st.session_state.pop("cal_jour_detail", None)
                    st.success(f"✅ Mission **{numero}** créée le "
                               f"{choisi:%d/%m/%Y} — en attente "
                               f"d'approbation.")
                    st.rerun()

    st.divider()

    st.caption("Chaque case indique le nombre de missions ce jour-là. "
               "**Cliquez sur le ＋ d'un jour** pour y créer une mission. "
               "Les jours passés sont désactivés : une mission ne se crée "
               "pas rétroactivement.")
    entetes = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
    for col, nom in zip(st.columns(7), entetes):
        col.markdown(f"<div style='text-align:center;font-weight:600;"
                     f"color:#6B7785;font-size:12px'>{nom}</div>",
                     unsafe_allow_html=True)

    for semaine in cal.Calendar(firstweekday=0).monthdatescalendar(
            ref.year, ref.month):
        for col, jour in zip(st.columns(7), semaine):
            with col:
                if jour.month != ref.month:
                    st.markdown("<div style='height:66px'></div>",
                                unsafe_allow_html=True)
                    continue
                n = occupation.get(jour, 0)
                if n == 0:
                    fond, txt = "#F4F6F8", "#8A99A9"
                elif n <= 2:
                    fond, txt = "#EAF4EF", "#1F7A5C"
                elif n <= 5:
                    fond, txt = "#FBF1E8", "#B5652F"
                else:
                    fond, txt = "#FCEAE9", "#E2231A"
                bord = ("2px solid #C2570A" if jour == aujourdhui
                        else "1px solid #E3E7EC")
                st.markdown(
                    f"<div style='background:{fond};border:{bord};"
                    f"border-radius:8px;padding:6px 4px;text-align:center'>"
                    f"<div style='font-weight:700;font-size:15px;"
                    f"color:#33404F'>{jour.day}</div>"
                    f"<div style='font-size:11px;color:{txt}'>"
                    f"{str(n) + ' mission' + ('s' if n > 1 else '') if n else '—'}"
                    f"</div></div>", unsafe_allow_html=True)
                passe = jour < aujourdhui
                # Pas de st.rerun() ici : il ramènerait l'affichage au
                # premier onglet et le panneau de saisie resterait
                # invisible. Le clic provoque déjà un réaffichage, et la
                # section de détail plus bas lit l'état mis à jour.
                if st.button("＋", key=f"cal_{jour}", disabled=passe,
                             use_container_width=True,
                             help=("Date passée : une mission ne peut pas "
                                   "être créée rétroactivement." if passe
                                   else f"Créer une mission le "
                                        f"{jour:%d/%m/%Y}")):
                    st.session_state["date_mission_calendrier"] = jour
                    st.session_state["date_mission_prevue"] = jour
                    st.session_state["cal_jour_detail"] = jour
                    # Streamlit conserve la valeur d'un champ tant que sa
                    # clé est inchangée : on renouvelle les clés pour que
                    # la date cliquée soit réellement reprise.
                    for f in ("form_cal_mission", "form_new_mission"):
                        st.session_state[f"nonce_{f}"] = \
                            st.session_state.get(f"nonce_{f}", 0) + 1
                    # Les champs conservent leur valeur d'une exécution à
                    # l'autre : il faut renouveler leurs clés pour que la
                    # date choisie devienne effectivement la valeur par
                    # défaut du formulaire.
                    for f in ("form_cal_mission", "form_new_mission"):
                        st.session_state[f"nonce_{f}"] = \
                            st.session_state.get(f"nonce_{f}", 0) + 1

# ══════════════════════════════════════════════════════════════════════
def page_missions(d):
    ui.titre_page("Gestion des missions", "🗺️")
    st.caption("Module missions v11.0 — workflow Draft→Pending→Approved, "
               "aperçu, PDF séparés, modification/suppression")
    veh, mis = d["vehicules"], d["missions"]
    staffs = d.get("staffs")
    if veh is None or staffs is None or staffs.empty:
        st.warning("Enregistrez d'abord des véhicules et des staffs "
                   "(page 👥 Staffs).")
        return
    chauffeurs_staff = staffs_avec_role(staffs, "chauffeur")
    approbateurs = staffs_avec_role(staffs, "approbateur")
    staffs = staffs.copy()
    staffs["staff_id"] = staffs.staff_id.astype(str).str.strip()
    idx_staff = staffs.set_index("staff_id")
    idx_veh = veh.set_index("vehicule_id")

    def lib_veh(x):
        r = idx_veh.loc[x]
        return f"{x} — {r.get('modele', r.get('type_vehicule', ''))} " \
               f"({r.get('immatriculation', '')}, " \
               f"{r.get('centre_service', r.get('localite', ''))})"

    def lib_staff(x):
        r = idx_staff.loc[x]
        mention = " · EXTERNE" if ui.est_externe(r) else ""
        return f"{x} — {r.nom_complet} ({r.get('departement', '')}){mention}"

    refs = (staffs, veh, chauffeurs_staff, approbateurs,
            idx_staff, idx_veh, lib_staff, lib_veh)

    t_new, t_cal, t_hist, t_ana, t_masse = st.tabs(
        ["➕ Nouvelle mission", "📅 Calendrier",
         "📋 Missions / Approbation / PDF", "🔮 Analyse & risques",
         "☑️ Actions en masse"])

    # ══ ➕ NOUVELLE MISSION ═══════════════════════════════════════════
    with t_new:
        if not auth.peut("gerer_missions"):
            st.warning("🔒 La création de missions est réservée aux "
                       "gestionnaires et administrateurs.")
        else:
            valeurs = _form_mission("form_new_mission", refs)
            if valeurs:
                numero = _numero_mission(mis, valeurs["departement"],
                                         valeurs["date_depart"][:10])
                ligne = {"numero_mission": numero, "statut": "Pending",
                         "date_approbation": "", **valeurs}
                nouveau = pd.concat(
                    [mis if mis is not None else pd.DataFrame(),
                     pd.DataFrame([ligne])], ignore_index=True)
                ecrire("missions.csv", nouveau)
                # Le formulaire n'est vidé qu'après un enregistrement
                # réussi : en cas d'erreur de saisie, tout est conservé.
                st.session_state["nonce_form_new_mission"] = \
                    st.session_state.get("nonce_form_new_mission", 0) + 1
                st.session_state.pop("date_mission_calendrier", None)
                st.session_state.pop("date_mission_prevue", None)
                st.success(f"✅ Mission **{numero}** enregistrée — statut "
                           f"**Pending** : en attente d'approbation "
                           f"(onglet Missions).")
                st.rerun()

    # ══ 📅 CALENDRIER ═════════════════════════════════════════════════
    with t_cal:
        _calendrier_missions(mis, veh, idx_veh, refs)

    # ══ 📋 MISSIONS / APPROBATION / PDF ═══════════════════════════════
    with t_hist:
        if mis is None or mis.empty:
            st.info("Aucune mission.")
        else:
            u = auth.utilisateur() or {}
            mon_id = str(u.get("staff_id") or "")
            mes_demandes = False
            if "approbateur" in u.get("roles", set()) and mon_id:
                _ap = mis.get("approbateur_id", pd.Series(dtype=str)).astype(str)
                _st = mis.get("statut", pd.Series(dtype=str)).map(_norm_statut)
                n_attente = int(((_ap == mon_id) & (_st == "Pending")).sum())
                mes_demandes = st.checkbox(
                    f"✍️ N'afficher que les missions qui me sont soumises "
                    f"({n_attente} en attente)", value=n_attente > 0)
            c1, c2, c3, c4 = st.columns([2, 2, 2, 2])
            q = c1.text_input("🔍 Recherche (n°, agent, destination, véhicule)")
            sfil = c2.multiselect("Statut", STATUTS)
            vfil = c3.selectbox("Véhicule",
                                ["(tous)"] + sorted(mis.vehicule_id.unique()))
            nj = c4.slider("Période (derniers jours)", 7, 1200, 180)

            m = mis.copy()
            m["statut"] = m.get("statut", "Pending").map(_norm_statut)
            # Un simple utilisateur ne consulte que ce qui est validé
            if not (auth.peut("gerer_missions")
                    or auth.peut("approuver_mission")):
                m = m[m.statut == "Approved"]
                st.caption("🔒 Consultation : seules les missions approuvées "
                           "vous sont accessibles.")
            m["date_depart"] = pd.to_datetime(m.date_depart, errors="coerce")
            m = m[m.date_depart >= m.date_depart.max() - pd.Timedelta(days=nj)]
            if mes_demandes and mon_id:
                m = m[(m.get("approbateur_id", "").astype(str) == mon_id)
                      & (m.statut == "Pending")]
            if vfil != "(tous)":
                m = m[m.vehicule_id == vfil]
            if sfil:
                m = m[m.statut.isin(sfil)]
            if q.strip():
                ql = q.strip().lower()
                masque = pd.Series(False, index=m.index)
                for col in ["numero_mission", "agent_principal",
                            "destination", "vehicule_id"]:
                    if col in m.columns:
                        masque |= m[col].astype(str).str.lower() \
                            .str.contains(ql, na=False)
                m = m[masque]
            m = m.sort_values("date_depart", ascending=False) \
                 .reset_index(drop=True)

            cols_aff = [c for c in ["numero_mission", "statut",
                                    "objet", "departement", "agent_principal",
                                    "origine", "destination", "date_depart",
                                    "duree_jours", "vehicule_id",
                                    "chauffeur_id", "distance_km"]
                        if c in m.columns]
            st.caption("👆 **Cliquez sur une ligne** : aperçu, approbation, "
                       "PDF, modification, suppression.")
            sel = []
            try:
                ev = st.dataframe(m[cols_aff], use_container_width=True,
                                  hide_index=True, on_select="rerun",
                                  selection_mode="single-row",
                                  key=f"tbl_mis_{len(m)}_{q}_{vfil}")
                sel = list(ev.selection.rows)
            except TypeError:
                st.dataframe(m[cols_aff], use_container_width=True,
                             hide_index=True)
            st.caption(f"{len(m)} mission(s)")

            if sel:
                r = m.iloc[sel[0]].to_dict()
                numero = r["numero_mission"]
                statut = _norm_statut(r.get("statut"))
                st.divider()
                st.subheader(f"Mission {numero}")
                st.markdown(f"Statut : :{COULEUR_STATUT.get(statut, 'gray')}"
                            f"[**{statut}**]")

                def maj_mission(champs: dict, message: str,
                                tracer_decideur=False):
                    m2 = mis.copy()
                    cible = m2.numero_mission == numero
                    # Celui qui décide devient l'approbateur enregistré :
                    # l'ordre de mission doit porter le nom de la personne
                    # qui a réellement statué.
                    if tracer_decideur:
                        u = auth.utilisateur() or {}
                        sid, nom = str(u.get("staff_id") or ""), \
                            u.get("nom_complet") or ""
                        if nom:
                            if sid != str(r.get("approbateur_id") or ""):
                                obs0 = str(r.get("observations") or "").strip()
                                m2.loc[cible, "observations"] = (
                                    f"{obs0} | Décidée par {nom} (désigné : "
                                    f"{r.get('approbateur', '—')})"
                                ).strip(" |")
                            m2.loc[cible, "approbateur"] = nom
                            m2.loc[cible, "approbateur_id"] = sid
                    for kk, val in champs.items():
                        m2.loc[cible, kk] = val
                    ecrire("missions.csv", m2)
                    st.success(message)
                    st.rerun()

                # ---- Workflow d'approbation ----
                mien = (str(r.get("approbateur_id") or "")
                        == str((auth.utilisateur() or {}).get("staff_id")))
                peut_decider = auth.est_admin() or (
                    auth.peut("approuver_mission") and mien)
                if statut == "Pending" and auth.peut("approuver_mission") \
                        and not peut_decider:
                    st.info(f"Cette mission est soumise à "
                            f"**{r.get('approbateur', '—')}** : vous ne pouvez "
                            f"pas la décider à sa place.")
                if statut == "Pending" and peut_decider:
                    c1, c2, c3, _ = st.columns([1, 1, 1, 2])
                    if c1.button("✅ Approuver", type="primary"):
                        maj_mission(
                            {"statut": "Approved",
                             "date_approbation":
                                 f"{pd.Timestamp.now():%Y-%m-%d %H:%M}"},
                            f"✅ Mission {numero} **approuvée**.",
                            tracer_decideur=True)
                    if c2.button("❌ Rejeter"):
                        maj_mission({"statut": "Rejected"},
                                    f"❌ Mission {numero} **rejetée**.",
                                    tracer_decideur=True)
                    if c3.button("🚫 Annuler (gestionnaire)"):
                        maj_mission({"statut": "Canceled"},
                                    f"🚫 Mission {numero} **annulée** "
                                    f"(conservée dans la liste).")
                elif statut == "Approved" and auth.peut("gerer_missions"):
                    c1, _ = st.columns([1, 4])
                    if c1.button("🚫 Annuler (gestionnaire)"):
                        maj_mission({"statut": "Canceled"},
                                    f"🚫 Mission {numero} **annulée**.")

                # ---- Aperçu de l'ordre de mission ----
                st.markdown("#### 👁️ Aperçu de l'ordre de mission")
                _apercu_ordre(r)

                # ---- PDF séparés ----
                try:
                    if r.get("vehicule_id") in idx_veh.index:
                        rv = idx_veh.loc[r["vehicule_id"]]
                        r["vehicule_label"] = (
                            f"{r['vehicule_id']} ({rv.get('modele', '')} — "
                            f"{rv.get('immatriculation', '')})")
                    if r.get("chauffeur_id") in idx_staff.index:
                        r["chauffeur_label"] = (
                            f"{idx_staff.loc[r['chauffeur_id'], 'nom_complet']}"
                            f" ({r['chauffeur_id']})")
                    from mission_pdf import generer_pdf_mission
                    c1, c2, c3 = st.columns(3)
                    c1.download_button(
                        "🖨️ PDF Ordre de mission",
                        generer_pdf_mission(r, contenu="ordre"),
                        f"{numero}_ordre.pdf", "application/pdf",
                        use_container_width=True)
                    c2.download_button(
                        "🖨️ PDF Feuille(s) de route",
                        generer_pdf_mission(r, contenu="feuille"),
                        f"{numero}_feuille_de_route.pdf", "application/pdf",
                        use_container_width=True)
                    c3.download_button(
                        "📄 PDF complet",
                        generer_pdf_mission(r, contenu="tout"),
                        f"{numero}.pdf", "application/pdf", type="primary",
                        use_container_width=True)
                except ImportError:
                    st.error("Bibliothèque PDF manquante : "
                             "`pip install reportlab`")

                # ---- Modifier ----
                if auth.peut("gerer_missions"):
                  with st.expander(f"✏️ Modifier la mission {numero}"):
                    st.warning("⚠️ Toute modification renvoie la mission au "
                               "statut **Pending** : elle devra être "
                               "réapprouvée."
                               + (f" Statut actuel : {statut}."
                                  if statut != "Pending" else ""))
                    valeurs = _form_mission(f"form_edit_{numero}", refs, r)
                    if valeurs:
                        # Une mission modifiée repasse systématiquement
                        # devant l'approbateur, quel que soit son statut.
                        valeurs["statut"] = "Pending"
                        valeurs["date_approbation"] = ""
                        maj_mission(
                            valeurs,
                            f"✅ Mission {numero} mise à jour — repassée en "
                            f"**Pending**, soumise à "
                            f"{valeurs.get('approbateur') or 'l’approbateur'}.")

                # ---- Supprimer (confirmation oui/non) ----
                if auth.peut("gerer_missions") and \
                        st.button(f"🗑️ Supprimer la mission {numero}"):
                    st.session_state["confirm_suppr_mis"] = numero
                if st.session_state.get("confirm_suppr_mis") == numero:
                    st.warning(f"⚠️ **Voulez-vous confirmer la suppression "
                               f"de la mission {numero} ?** Pour garder la "
                               f"trace, préférez l'annulation (statut "
                               f"Canceled).")
                    c1, c2, _ = st.columns([1, 1, 3])
                    if c1.button("✅ Oui, supprimer", type="primary",
                                 key="oui_suppr_mis"):
                        ecrire("missions.csv",
                               mis[mis.numero_mission != numero])
                        del st.session_state["confirm_suppr_mis"]
                        st.rerun()
                    if c2.button("❌ Non, annuler", key="non_suppr_mis"):
                        del st.session_state["confirm_suppr_mis"]
                        st.rerun()

    # ══ 🔮 ANALYSE & RISQUES ══════════════════════════════════════════
    with t_ana:
        if mis is None or mis.empty:
            st.info("Pas encore de missions à analyser.")
            return
        m = mis.copy()
        m["date_depart"] = pd.to_datetime(m.date_depart, errors="coerce")
        ref = m.date_depart.max()
        m90 = m[m.date_depart >= ref - pd.Timedelta(days=90)]
        m30 = m[m.date_depart >= ref - pd.Timedelta(days=30)]

        st.subheader("🚙 Utilisation des véhicules (90 derniers jours)")
        u = m90.groupby("vehicule_id").agg(
            jours_mission=("duree_jours", "sum"),
            missions=("numero_mission", "count"),
            km=("distance_km", "sum")).reindex(veh.vehicule_id).fillna(0)
        u["taux_utilisation_%"] = (u.jours_mission / 90 * 100).round(1)
        u = u.merge(veh.set_index("vehicule_id")[
            [c for c in ["centre_service", "localite", "modele",
                         "etat_vehicule"] if c in veh.columns]],
            left_index=True, right_index=True)
        c1, c2, c3 = st.columns(3)
        c1.metric("Taux d'utilisation moyen",
                  f"{u['taux_utilisation_%'].mean():.0f} %")
        c2.metric("Véhicules surutilisés (>60 %)",
                  int((u["taux_utilisation_%"] > 60).sum()))
        c3.metric("Véhicules sous-utilisés (<15 %)",
                  int((u["taux_utilisation_%"] < 15).sum()))
        cg, cd = st.columns(2)
        with cg:
            st.markdown("**🔥 Les plus sollicités** — usure accélérée, "
                        "à surveiller en maintenance")
            st.dataframe(u.nlargest(8, "taux_utilisation_%").reset_index(),
                         use_container_width=True, hide_index=True)
        with cd:
            st.markdown("**💤 Les moins utilisés** — candidats à la "
                        "réaffectation entre centres")
            st.dataframe(u.nsmallest(8, "taux_utilisation_%").reset_index(),
                         use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("🧑‍✈️ Exposition des chauffeurs et staffs "
                     "(fatigue / risque route)")
        e = m90.groupby("chauffeur_id").agg(
            jours_route_90j=("duree_jours", "sum"),
            km_90j=("distance_km", "sum"),
            km_piste_90j=("part_piste", lambda s: float(
                (m90.loc[s.index, "distance_km"] * s).sum())),
            missions_90j=("numero_mission", "count")).fillna(0)
        e30 = m30.groupby("chauffeur_id").duree_jours.sum() \
                 .rename("jours_route_30j")
        e = e.join(e30).fillna(0)
        e["score_exposition"] = (
            (e.jours_route_30j / 15).clip(0, 1) * 45
            + (e.km_90j / 9000).clip(0, 1) * 35
            + (e.km_piste_90j / 5000).clip(0, 1) * 20).round(0)
        e["alerte"] = np.select(
            [e.score_exposition >= 75, e.score_exposition >= 50],
            ["🔴 Surexposé — repos conseillé", "🟠 À surveiller"], "🟢 OK")
        ref_noms = staffs.set_index("staff_id")[["nom_complet", "localite"]]
        e = e.merge(ref_noms, left_index=True, right_index=True,
                    how="left").reset_index()
        e["nom_complet"] = e.nom_complet.fillna(e.chauffeur_id)
        e["localite"] = e.localite.fillna("—")
        c1, c2 = st.columns(2)
        c1.metric("🔴 Chauffeurs surexposés",
                  int((e.alerte.str.startswith("🔴")).sum()))
        c2.metric("🟠 À surveiller",
                  int((e.alerte.str.startswith("🟠")).sum()))
        st.caption("Score = jours sur la route (30 j, 45 %) + km (90 j, 35 %)"
                   " + km de piste (90 j, 20 %). Seuils : 🔴 ≥ 75, 🟠 ≥ 50 — "
                   "à calibrer avec les règles RH World Vision.")
        aff = e.sort_values("score_exposition", ascending=False)[
            ["chauffeur_id", "nom_complet", "localite", "jours_route_30j",
             "jours_route_90j", "km_90j", "km_piste_90j",
             "score_exposition", "alerte"]].round(0)
        st.dataframe(aff.style.background_gradient(
            subset=["score_exposition"], cmap="Reds"),
            use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("💡 Suggestion d'affectation pour une prochaine mission")
        centre = st.selectbox("Centre de départ",
                              list(CENTRES_SERVICE.keys()), key="sugg_centre")
        loc = CENTRES_SERVICE[centre]
        vloc = u[(u.get("centre_service", u.get("localite")) == centre)
                 | (u.get("localite", "") == loc)].copy()
        if "etat_vehicule" in vloc.columns:
            vloc = vloc[vloc.etat_vehicule != "Non fonctionnel"]
        vsug = vloc.nsmallest(3, "taux_utilisation_%")
        csug = e[e.localite == loc].nsmallest(3, "score_exposition")
        cg, cd = st.columns(2)
        with cg:
            st.markdown("**Véhicules recommandés** (fonctionnels, "
                        "les moins sollicités)")
            st.dataframe(vsug.reset_index()[
                ["vehicule_id", "modele", "taux_utilisation_%", "km"]]
                if "modele" in vsug.columns else vsug.reset_index(),
                use_container_width=True, hide_index=True)
        with cd:
            st.markdown("**Chauffeurs recommandés** (les moins exposés)")
            st.dataframe(csug[["chauffeur_id", "nom_complet",
                               "jours_route_30j", "score_exposition"]],
                         use_container_width=True, hide_index=True)
        st.info("🚧 Prochaine itération : croisement avec le risque de panne "
                "prédit et optimisation multi-missions (OR-Tools).")

    # ══ ACTIONS EN MASSE ═════════════════════════════════════════════
    with t_masse:
        if mis is None or mis.empty:
            st.info("Aucune mission.")
        elif not auth.peut("gerer_missions"):
            st.warning("🔒 Les actions en masse sont réservées aux "
                       "gestionnaires et administrateurs.")
        else:
            base = mis.copy()
            base["statut"] = base.get("statut", "Pending").map(_norm_statut)
            base["date_depart"] = pd.to_datetime(base.date_depart,
                                                 errors="coerce")
            c1, c2, c3 = st.columns(3)
            sf = c1.multiselect("Statut", STATUTS, key="mst")
            vf = c2.multiselect("Véhicule",
                                sorted(base.vehicule_id.dropna().unique()),
                                key="mve")
            nj = c3.slider("Période (derniers jours)", 7, 1200, 365,
                           key="mnj")
            ref = base.date_depart.max()
            if pd.notna(ref):
                base = base[base.date_depart >= ref - pd.Timedelta(days=nj)]
            if sf:
                base = base[base.statut.isin(sf)]
            if vf:
                base = base[base.vehicule_id.isin(vf)]
            base = base.sort_values("date_depart", ascending=False)

            sel = ui.selection_multiple(
                base, ["numero_mission", "statut", "objet", "departement",
                       "agent_principal", "origine", "destination",
                       "date_depart", "vehicule_id", "chauffeur_id"],
                "sel_missions",
                "☑️ Cochez les missions concernées, puis choisissez "
                "l'action.")
            n = len(sel)
            st.caption(f"**{n}** mission(s) sélectionnée(s) sur {len(base)}.")

            if n:
                st.divider()
                st.markdown("**Changer le statut**")
                c1, c2, c3 = st.columns(3)
                if c1.button(f"🚫 Annuler les {n} sélectionnée(s)",
                             key="mannul"):
                    m2 = mis.copy()
                    m2.loc[m2.numero_mission.isin(sel.numero_mission),
                           "statut"] = "Canceled"
                    ecrire("missions.csv", m2)
                    st.success(f"🚫 {n} mission(s) annulée(s) — elles restent "
                               f"listées pour la traçabilité.")
                    st.rerun()
                if auth.peut("approuver_mission"):
                    if c2.button(f"✅ Approuver les {n} sélectionnée(s)",
                                 key="mappr"):
                        m2 = mis.copy()
                        cible = m2.numero_mission.isin(sel.numero_mission)
                        m2.loc[cible, "statut"] = "Approved"
                        m2.loc[cible, "date_approbation"] = \
                            f"{pd.Timestamp.now():%Y-%m-%d %H:%M}"
                        ecrire("missions.csv", m2)
                        st.success(f"✅ {n} mission(s) approuvée(s).")
                        st.rerun()
                    if c3.button(f"❌ Rejeter les {n} sélectionnée(s)",
                                 key="mrejet"):
                        m2 = mis.copy()
                        m2.loc[m2.numero_mission.isin(sel.numero_mission),
                               "statut"] = "Rejected"
                        ecrire("missions.csv", m2)
                        st.success(f"❌ {n} mission(s) rejetée(s).")
                        st.rerun()

                st.divider()
                st.markdown("**Réaffecter**")
                c1, c2 = st.columns(2)
                nv = c1.selectbox("Nouveau véhicule", ["(inchangé)"]
                                  + list(veh.vehicule_id), key="mnv")
                nc = c2.selectbox("Nouveau chauffeur", ["(inchangé)"]
                                  + list(chauffeurs_staff.staff_id),
                                  format_func=lambda x: x if x == "(inchangé)"
                                  else lib_staff(x), key="mnc")
                if (nv != "(inchangé)" or nc != "(inchangé)") and st.button(
                        f"Réaffecter les {n} mission(s)", key="mreaff",
                        type="primary"):
                    m2 = mis.copy()
                    cible = m2.numero_mission.isin(sel.numero_mission)
                    if nv != "(inchangé)":
                        m2.loc[cible, "vehicule_id"] = nv
                    if nc != "(inchangé)":
                        m2.loc[cible, "chauffeur_id"] = nc
                    # Une mission réaffectée doit être réapprouvée
                    m2.loc[cible, "statut"] = "Pending"
                    m2.loc[cible, "date_approbation"] = ""
                    ecrire("missions.csv", m2)
                    st.success(f"✅ {n} mission(s) réaffectée(s) — repassées "
                               f"en **Pending** pour approbation.")
                    st.rerun()

                st.divider()
                st.markdown("**Supprimer**")
                st.caption("L'annulation est préférable : elle conserve la "
                           "trace de la demande.")
                if ui.confirmer_action(
                        "suppr_missions",
                        f"🗑️ Supprimer les {n} sélectionnée(s)", n,
                        "Les pleins rattachés à ces missions resteront en "
                        "base sans mission correspondante."):
                    ecrire("missions.csv",
                           mis[~mis.numero_mission.isin(sel.numero_mission)])
                    st.success(f"🗑️ {n} mission(s) supprimée(s).")
                    st.rerun()


# ══════════════════════════════════════════════════════════════════════
# ✍️ MISSIONS À APPROUVER — écran dédié aux approbateurs
# ══════════════════════════════════════════════════════════════════════
def page_approbations(d):
    ui.titre_page("Missions à approuver", "✍️")
    st.caption("Demandes en attente de votre décision")
    if auth.bloquer("approuver_mission",
                    "🔒 Cet écran est réservé aux approbateurs et aux "
                    "administrateurs."):
        return

    mis, veh, staffs = d["missions"], d["vehicules"], d.get("staffs")
    if mis is None or mis.empty:
        st.info("Aucune mission enregistrée.")
        return

    u = auth.utilisateur() or {}
    mon_id = str(u.get("staff_id") or "")
    m = mis.copy()
    m["statut"] = m.get("statut", "Pending").map(_norm_statut)
    m["date_depart"] = pd.to_datetime(m.date_depart, errors="coerce")
    attente = m[m.statut == "Pending"].copy()

    # Un admin voit tout ; un approbateur ne voit que ce qui lui est soumis
    if auth.est_admin():
        miennes = attente[attente.get("approbateur_id", "").astype(str)
                          == mon_id] if mon_id else attente.iloc[0:0]
        autres = attente[~attente.index.isin(miennes.index)]
    else:
        miennes = attente[attente.get("approbateur_id", "").astype(str)
                          == mon_id]
        autres = attente.iloc[0:0]

    c1, c2, c3 = st.columns(3)
    c1.metric("✍️ Soumises à moi", len(miennes))
    if auth.est_admin():
        c2.metric("Soumises à d'autres", len(autres))
    c3.metric("Total en attente", len(attente))

    if attente.empty:
        st.success("✅ Aucune mission en attente : tout est traité.")
        return

    liste = pd.concat([miennes, autres]) if auth.est_admin() else miennes
    if liste.empty:
        st.info("Aucune mission ne vous est soumise actuellement. "
                f"{len(attente)} attende(nt) la décision d'un autre "
                f"approbateur.")
        return

    liste = liste.sort_values("date_depart")
    cols = [c for c in ["numero_mission", "objet", "departement",
                        "agent_principal", "origine", "destination",
                        "date_depart", "duree_jours", "distance_km",
                        "vehicule_id", "approbateur"] if c in liste.columns]
    st.caption("👆 Cliquez sur une ligne pour examiner la demande.")
    sel = []
    try:
        ev = st.dataframe(liste[cols].reset_index(drop=True),
                          use_container_width=True, hide_index=True,
                          on_select="rerun", selection_mode="single-row",
                          key=f"tbl_appr_{len(liste)}")
        sel = list(ev.selection.rows)
    except TypeError:
        st.dataframe(liste[cols], use_container_width=True, hide_index=True)

    if not sel:
        return

    r = liste.reset_index(drop=True).iloc[sel[0]].to_dict()
    numero = r["numero_mission"]
    mien = str(r.get("approbateur_id") or "") == mon_id
    st.divider()
    st.subheader(f"Mission {numero}")

    if not (mien or auth.est_admin()):
        st.info(f"Cette mission est soumise à **{r.get('approbateur', '—')}** : "
                f"vous ne pouvez pas la décider à sa place.")
    else:
        c1, c2, c3 = st.columns([1, 1, 3])
        motif = c3.text_input("Motif (obligatoire en cas de rejet)",
                              key=f"motif_{numero}")

        def decider(statut, message, avec_date=False):
            m2 = mis.copy()
            cible = m2.numero_mission == numero
            m2.loc[cible, "statut"] = statut
            # L'ordre de mission porte le nom de qui a réellement décidé
            nom_decideur = u.get("nom_complet") or ""
            if nom_decideur:
                if not mien:
                    obs0 = str(r.get("observations") or "").strip()
                    m2.loc[cible, "observations"] = (
                        f"{obs0} | Décidée par {nom_decideur} (désigné : "
                        f"{r.get('approbateur', '—')})").strip(" |")
                m2.loc[cible, "approbateur"] = nom_decideur
                m2.loc[cible, "approbateur_id"] = mon_id
            if avec_date:
                m2.loc[cible, "date_approbation"] = \
                    f"{pd.Timestamp.now():%Y-%m-%d %H:%M}"
            if motif.strip():
                obs = str(r.get("observations") or "").strip()
                m2.loc[cible, "observations"] = (
                    f"{obs} | {statut} : {motif.strip()}".strip(" |"))
            ecrire("missions.csv", m2)
            st.success(message)
            st.rerun()

        if c1.button("✅ Approuver", type="primary", key=f"ap_{numero}"):
            decider("Approved", f"✅ Mission {numero} approuvée.", True)
        if c2.button("❌ Rejeter", key=f"rj_{numero}"):
            if not motif.strip():
                st.error("Indiquez le motif du rejet : il sera consigné "
                         "dans les observations de la mission.")
            else:
                decider("Rejected", f"❌ Mission {numero} rejetée.")

    st.markdown("#### 👁️ Aperçu de l'ordre de mission")
    _apercu_ordre(r)
