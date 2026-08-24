"""
Page Véhicules — gestion complète alignée sur le modèle World Vision.

Volets :
  🚨 Conformité   alertes rouges + mise à jour directe des documents
  ➕ Nouveau      formulaire complet avec champs calculés
  📋 Liste        recherche (immatriculation…), modification par formulaire
                  pré-rempli, suppression avec confirmation oui/non
  📄 Template     modèle CSV/Excel pour import sans erreur
"""
import io
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from config import (MODELES, TYPES_VEHICULE, COMBUSTIBLES, CENTRES_SERVICE,
                    IMPUTATIONS, ETATS_DOC, ETATS_VEHICULE)
from crud import ecrire, lire, prochain_id
import auth
import ui
import auth

CAPACITES_MODELE = {
    "hilux": 80, "land cruiser": 90, "prado": 87, "hiace": 70,
    "patrol": 85, "navara": 80, "l200": 75, "ranger": 80,
    "corolla": 50, "dt 125": 10, "xtz": 12, "motorcycle": 12,
}
CAPACITES_TYPE = {"Voiture": 70, "Moto": 12}


def capacite_defaut(modele="", type_vehicule="Voiture") -> int:
    m = str(modele or "").strip().lower()
    for cle, cap in CAPACITES_MODELE.items():
        if cle in m:
            return cap
    return CAPACITES_TYPE.get(str(type_vehicule).strip(), 70)


def conso_estimee(missions, conso_nominale_l_100km) -> float:
    """Carburant consommé par un ensemble de missions (litres).
    La piste majore la consommation d'environ 20 %."""
    if missions is None or not len(missions):
        return 0.0
    dist = pd.to_numeric(missions.get("distance_km"), errors="coerce").fillna(0)
    piste = pd.to_numeric(missions.get("part_piste"), errors="coerce").fillna(0.3)
    conso = float(conso_nominale_l_100km or 10)
    return float((dist * conso / 100 * (1 + 0.22 * piste)).sum())


def niveau_reservoir(v, missions=None) -> dict:
    """État du réservoir. Le niveau enregistré est diminué de la
    consommation estimée des missions effectuées depuis le dernier relevé."""
    # NaN est « vrai » en Python : on teste avec pd.notna().
    cap = pd.to_numeric(v.get("capacite_reservoir_l"), errors="coerce")
    cap = float(cap) if pd.notna(cap) and float(cap) > 0 else float(
        capacite_defaut(v.get("modele"), v.get("type_vehicule")))
    niveau = pd.to_numeric(v.get("niveau_carburant_l"), errors="coerce")
    niveau = float(niveau) if pd.notna(niveau) else 0.0
    ref = pd.to_datetime(v.get("date_niveau"), errors="coerce")

    consomme = 0.0
    if missions is not None and len(missions) and pd.notna(ref):
        m = missions[missions.vehicule_id.astype(str)
                     == str(v.get("vehicule_id"))]
        if "date_depart" in m.columns:
            m = m[pd.to_datetime(m.date_depart, errors="coerce") > ref]
        if "statut" in m.columns:
            m = m[~m.statut.astype(str).str.lower()
                  .isin(["canceled", "rejected", "draft", "annulée"])]
        consomme = conso_estimee(m, v.get("conso_nominale_l_100km"))

    actuel = max(0.0, min(cap, niveau - consomme))
    return {"capacite": cap, "niveau": round(actuel, 1),
            "consomme": round(consomme, 1),
            "disponible": round(max(0.0, cap - actuel), 1),
            "pourcentage": round(actuel / cap * 100, 0) if cap else 0}


DOCS = {
    "Visite technique": ("date_visite_technique", "prochaine_visite_technique",
                         "etat_visite_technique"),
    "Assurance": ("date_souscription_assurance", "renouvellement_assurance",
                  "etat_assurance"),
    "Admission Temporaire": ("date_admission_temporaire", "renouvellement_at",
                             "etat_at"),
}

COLONNES = [
    "immatriculation", "vehicule_id", "marque", "modele", "type_vehicule",
    "n_chassis", "centre_service", "localite", "puissance_cv", "imputation",
    "date_premiere_circulation", "annee_mise_en_service", "date_acquisition",
    "valeur_acquisition_fcfa", "combustible", "conso_nominale_l_100km",
    "capacite_reservoir_l", "niveau_carburant_l", "date_niveau",
    "km_initial", "date_visite_technique", "etat_visite_technique",
    "prochaine_visite_technique", "date_souscription_assurance",
    "etat_assurance", "renouvellement_assurance", "date_admission_temporaire",
    "etat_at", "renouvellement_at", "etat_carte_grise", "etat_vehicule",
    "remarques",
]


# ══════════════════════════════════════════════════════════════════════
# Utilitaires
# ══════════════════════════════════════════════════════════════════════
def _sans_accent(t):
    """« Kédougou » -> « kedougou » (comparaison insensible aux accents)."""
    return "".join(c for c in unicodedata.normalize("NFD", str(t).strip())
                   if unicodedata.category(c) != "Mn").lower()


_CENTRES_NORM = {_sans_accent(k): (k, v) for k, v in CENTRES_SERVICE.items()}


def _normaliser_centre(val):
    """« kédougou », « KEDOUGOU », «  Kedougou  » -> ('Kedougou', 'Zone Sud').
    Un centre inconnu est conservé tel quel, sans localité déduite."""
    return _CENTRES_NORM.get(_sans_accent(val), (str(val).strip(), None))


def _entier(serie, defaut=0):
    """Entier tolérant : vides, « N/A », « 12 000 » (espace insécable inclus)."""
    nettoye = (serie.astype(str)
               .str.replace("\u00a0", "", regex=False)
               .str.replace(" ", "", regex=False))
    return pd.to_numeric(nettoye, errors="coerce").fillna(defaut).astype(int)


def normaliser_immat(serie):
    """« wv it 01 » -> « WV-IT-01 ». L'immatriculation est l'identifiant
    unique du véhicule : elle est normalisée pour éviter les doublons dus
    à la casse ou aux espaces."""
    s = serie.astype(str).str.strip().str.upper()
    s = s.str.replace("\u00a0", " ", regex=False).str.replace(r"\s+", "-", regex=True)
    return s.str.replace(r"-{2,}", "-", regex=True).str.strip("-")


def calculer_champs(df: pd.DataFrame) -> pd.DataFrame:
    """Champs dérivés : renouvellements (+1 an), localité, année de service.

    Tolérant aux données réelles importées : dates vides ou illisibles,
    formats français (31/12/2015), accents et casse variables sur les
    centres de service, nombres avec espaces ou virgule décimale.
    """
    df = df.copy()

    # L'IMMATRICULATION est l'identifiant du véhicule. La colonne
    # technique `vehicule_id` (clé étrangère des tables missions,
    # carburant et maintenance) en reçoit la valeur.
    if "immatriculation" in df.columns:
        df["immatriculation"] = normaliser_immat(df.immatriculation)
        df["vehicule_id"] = df.immatriculation

    # Échéances de renouvellement : date du document + 1 an
    for _, (d_src, d_calc, _) in DOCS.items():
        if d_src in df.columns:
            src = pd.to_datetime(df[d_src], errors="coerce", format="mixed")
            df[d_src] = src.dt.date
            df[d_calc] = (src + pd.DateOffset(years=1)).dt.date

    # Centre de service -> localité analytique
    # Les libellés sont ramenés à leur forme canonique : « ZONE SUD »,
    # « zone sud » et « Zone Sud » ne doivent pas compter séparément.
    _LOCS = {_sans_accent(v): v for v in set(CENTRES_SERVICE.values())}
    if "centre_service" in df.columns:
        paires = df.centre_service.map(_normaliser_centre)
        df["centre_service"] = paires.map(lambda x: x[0])
        loc = paires.map(lambda x: x[1])
        if "localite" in df.columns:
            loc = loc.fillna(df.localite)
        df["localite"] = loc.fillna("Bureau National").map(
            lambda x: _LOCS.get(_sans_accent(x), str(x).strip()))
    elif "localite" in df.columns:
        df["localite"] = df.localite.map(
            lambda x: _LOCS.get(_sans_accent(x), str(x).strip()))

    # Autres libellés à valeur fixe
    for col, valeurs in [("type_vehicule", ["Voiture", "Moto"]),
                         ("combustible", ["Gasoil", "Super"]),
                         ("etat_vehicule", ["Fonctionnel", "Non fonctionnel"]),
                         ("etat_visite_technique", ["Bon", "Pas bon"]),
                         ("etat_assurance", ["Bon", "Pas bon"]),
                         ("etat_at", ["Bon", "Pas bon"]),
                         ("etat_carte_grise", ["Bon", "Pas bon"])]:
        if col in df.columns:
            table = {_sans_accent(v): v for v in valeurs}
            df[col] = df[col].map(
                lambda x, t=table: t.get(_sans_accent(x), str(x).strip())
                if pd.notna(x) else x)
    for col in ["marque", "modele"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title() \
                              .replace({"Nan": "", "None": ""})

    # Année de mise en service : 1re circulation, sinon colonne existante,
    # sinon année courante
    if "date_premiere_circulation" in df.columns:
        circ = pd.to_datetime(df.date_premiere_circulation,
                              errors="coerce", format="mixed")
        df["date_premiere_circulation"] = circ.dt.date
        annee = circ.dt.year
        if "annee_mise_en_service" in df.columns:
            annee = annee.fillna(pd.to_numeric(df.annee_mise_en_service,
                                               errors="coerce"))
        df["annee_mise_en_service"] = annee.fillna(date.today().year).astype(int)
    elif "annee_mise_en_service" in df.columns:
        df["annee_mise_en_service"] = _entier(df.annee_mise_en_service,
                                              date.today().year)

    if "date_acquisition" in df.columns:
        df["date_acquisition"] = pd.to_datetime(
            df.date_acquisition, errors="coerce", format="mixed").dt.date

    # Réservoir : capacité déduite du modèle si absente, niveau borné
    if "capacite_reservoir_l" not in df.columns:
        df["capacite_reservoir_l"] = pd.NA
    cap = pd.to_numeric(df.capacite_reservoir_l, errors="coerce")
    defauts = df.apply(lambda r: capacite_defaut(r.get("modele"),
                                                 r.get("type_vehicule")),
                       axis=1) if len(df) else pd.Series(dtype=float)
    df["capacite_reservoir_l"] = cap.fillna(defauts).astype(int)
    if "niveau_carburant_l" not in df.columns:
        df["niveau_carburant_l"] = 0
    df["niveau_carburant_l"] = pd.to_numeric(
        df.niveau_carburant_l, errors="coerce").fillna(0) \
        .clip(lower=0, upper=df.capacite_reservoir_l).round(1)
    if "date_niveau" not in df.columns:
        df["date_niveau"] = ""

    # Champs numériques
    for col in ["km_initial", "puissance_cv", "valeur_acquisition_fcfa"]:
        if col in df.columns:
            df[col] = _entier(df[col], 0)
    if "conso_nominale_l_100km" in df.columns:
        df["conso_nominale_l_100km"] = pd.to_numeric(
            df.conso_nominale_l_100km.astype(str).str.replace(",", "."),
            errors="coerce").fillna(10.0)

    return df


def table_conformite(veh: pd.DataFrame) -> pd.DataFrame:
    auj = pd.Timestamp.today().normalize()
    lignes = []
    for doc, (_, col_renouv, col_etat) in DOCS.items():
        if col_renouv not in veh.columns:
            continue
        r = pd.to_datetime(veh[col_renouv], errors="coerce")
        lignes.append(pd.DataFrame({
            "Véhicule": veh.vehicule_id,
            "Immatriculation": veh.get("immatriculation", ""),
            "Centre": veh.get("centre_service", veh.get("localite", "")),
            "Document": doc,
            "Renouvellement": r.dt.date,
            "Jours restants": (r - auj).dt.days,
            "État déclaré": veh.get(col_etat, ""),
        }))
    if not lignes:
        return pd.DataFrame()
    tout = pd.concat(lignes, ignore_index=True)
    tout["Statut"] = pd.cut(tout["Jours restants"], [-100000, -1, 30, 100000],
                            labels=["🔴 EXPIRÉ", "🟠 Expire sous 30 j", "🟢 OK"])
    return tout


def style_statut(row):
    if row["Statut"] == "🔴 EXPIRÉ":
        return ["background-color:#E2231A;color:white"] * len(row)
    if row["Statut"] == "🟠 Expire sous 30 j":
        return ["background-color:#FFE0B2"] * len(row)
    return [""] * len(row)


def _date(val, defaut=None):
    d = pd.to_datetime(val, errors="coerce")
    return d.date() if pd.notna(d) else (defaut or date.today())


def _idx(options, val, defaut=0):
    options = list(options)
    return options.index(val) if val in options else defaut


def construire_template() -> pd.DataFrame:
    exemple = {
        "immatriculation": "WV-IT-01",
        "vehicule_id": "(calculé : reprend l'immatriculation)", "marque": "Toyota", "modele": "Hilux",
        "type_vehicule": "Voiture", "n_chassis": "AHTFR22G506123456",
        "centre_service": "Dakar", "localite": "(calculé)", "puissance_cv": 11,
        "imputation": "PRG-WASH", "date_premiere_circulation": "2019-05-14",
        "annee_mise_en_service": "(calculé)", "date_acquisition": "2019-08-01",
        "valeur_acquisition_fcfa": 28000000, "combustible": "Gasoil",
        "conso_nominale_l_100km": 11.5, "capacite_reservoir_l": 80,
        "niveau_carburant_l": 45, "date_niveau": "(calculé)",
        "km_initial": 85000,
        "date_visite_technique": "2026-03-10", "etat_visite_technique": "Bon",
        "prochaine_visite_technique": "(calculé : +1 an)",
        "date_souscription_assurance": "2025-11-02", "etat_assurance": "Bon",
        "renouvellement_assurance": "(calculé : +1 an)",
        "date_admission_temporaire": "2025-09-15", "etat_at": "Bon",
        "renouvellement_at": "(calculé : +1 an)",
        "etat_carte_grise": "Bon", "etat_vehicule": "Fonctionnel",
        "remarques": "",
    }
    return pd.DataFrame([exemple], columns=COLONNES)


# ══════════════════════════════════════════════════════════════════════
# Formulaire véhicule réutilisable (création ET modification)
# ══════════════════════════════════════════════════════════════════════
def _formulaire_vehicule(v: dict | None, cle: str) -> dict | None:
    """Affiche le formulaire (pré-rempli si v fourni). Retourne les valeurs
    saisies si le bouton est cliqué, sinon None."""
    v = v or {}
    with st.form(cle, clear_on_submit=v == {}):
        st.markdown("**Identification**")
        c1, c2, c3, c4 = st.columns(4)
        immat = c1.text_input("Immatriculation *", v.get("immatriculation", ""),
                              placeholder="WV-IT-01")
        marques = sorted({m[0] for m in MODELES.values()})
        marque = c2.selectbox("Marque *", marques, _idx(marques, v.get("marque")))
        modele = c3.text_input("Modèle *", v.get("modele", ""), placeholder="Hilux")
        type_v = c4.selectbox("Type véhicule *", TYPES_VEHICULE,
                              _idx(TYPES_VEHICULE, v.get("type_vehicule")))
        c5, c6, c7, c8 = st.columns(4)
        chassis = c5.text_input("N° châssis", v.get("n_chassis", ""))
        centres = list(CENTRES_SERVICE.keys())
        centre = c6.selectbox("Centre de service *", centres,
                              _idx(centres, v.get("centre_service")))
        puissance = c7.number_input("Puissance (CV)", 1, 40,
                                    int(v.get("puissance_cv", 11) or 11))
        imput = c8.selectbox("Imputation", IMPUTATIONS,
                             _idx(IMPUTATIONS, v.get("imputation")))

        st.markdown("**Acquisition & caractéristiques**")
        c1, c2, c3, c4 = st.columns(4)
        d_circ = c1.date_input("1ère mise en circulation *",
                               _date(v.get("date_premiere_circulation"),
                                     date(2020, 1, 1)),
                               min_value=date(1995, 1, 1))
        d_acq = c2.date_input("Date d'acquisition",
                              _date(v.get("date_acquisition"), date(2020, 1, 1)),
                              min_value=date(1995, 1, 1))
        valeur = c3.number_input("Valeur acquisition (FCFA)", 0, 200_000_000,
                                 int(v.get("valeur_acquisition_fcfa",
                                           28_000_000) or 0), step=500_000)
        comb = c4.selectbox("Combustible *", COMBUSTIBLES,
                            _idx(COMBUSTIBLES, v.get("combustible")))
        c5, c6 = st.columns(4)[:2]
        conso = c5.number_input("Conso nominale (L/100km) *", 1.0, 30.0,
                                float(v.get("conso_nominale_l_100km", 11.5)
                                      or 11.5), 0.5)
        km0 = c6.number_input(
            f"Kilométrage initial {ui.puce_champ(v.get('km_initial'))}",
            0, 1_500_000, int(v.get("km_initial", 0) or 0), step=1000,
            help="Compteur au moment de l'enregistrement. Il s'incrémente "
                 "ensuite automatiquement des kilomètres des missions.")
        c7, c8 = st.columns(4)[:2]
        _c = pd.to_numeric(v.get("capacite_reservoir_l"), errors="coerce")
        cap_def = int(_c) if pd.notna(_c) and float(_c) > 0 \
            else capacite_defaut(v.get("modele"), type_v)
        capacite = c7.number_input(
            "Capacité du réservoir (L) *", 1, 400, cap_def,
            help="Volume total du réservoir : sert à contrôler les pleins.")
        _n = pd.to_numeric(v.get("niveau_carburant_l"), errors="coerce")
        niveau = c8.number_input(
            "Niveau de carburant actuel (L)", 0.0, float(capacite),
            min(float(_n) if pd.notna(_n) else 0.0, float(capacite)),
            step=1.0,
            help="Tenu à jour ensuite par les pleins et les missions.")

        # Les libellés portent l'état du document : vert conforme,
        # orange à moins de trente jours, rouge expiré ou absent.
        vt = ui.puce_document(v.get("prochaine_visite_technique"))
        ass = ui.puce_document(v.get("renouvellement_assurance"))
        at = ui.puce_document(v.get("renouvellement_at"))
        st.markdown("**Conformité** *(renouvellements calculés : +1 an)*")
        c1, c2, c3 = st.columns(3)
        d_vt = c1.date_input(f"Date visite technique — {vt}",
                             _date(v.get("date_visite_technique")))
        e_vt = c1.selectbox("État visite technique", ETATS_DOC,
                            _idx(ETATS_DOC, v.get("etat_visite_technique")))
        d_ass = c2.date_input(f"Date souscription assurance — {ass}",
                              _date(v.get("date_souscription_assurance")))
        e_ass = c2.selectbox("État assurance", ETATS_DOC,
                             _idx(ETATS_DOC, v.get("etat_assurance")))
        d_at = c3.date_input(f"Date Admission Temporaire (AT) — {at}",
                             _date(v.get("date_admission_temporaire")))
        e_at = c3.selectbox("État AT", ETATS_DOC,
                            _idx(ETATS_DOC, v.get("etat_at")))
        c4, c5, c6 = st.columns(3)
        e_cg = c4.selectbox("État carte grise", ETATS_DOC,
                            _idx(ETATS_DOC, v.get("etat_carte_grise")))
        e_veh = c5.selectbox("État véhicule", ETATS_VEHICULE,
                             _idx(ETATS_VEHICULE, v.get("etat_vehicule")))
        rem = c6.text_input("Remarques", v.get("remarques", "") or "")

        libelle = "💾 Enregistrer les modifications" if v else "Enregistrer le véhicule"
        if st.form_submit_button(libelle, type="primary"):
            if not immat.strip() or not modele.strip():
                st.error("Immatriculation et modèle sont obligatoires.")
                return None
            return {
                "immatriculation": immat.strip(), "marque": marque,
                "modele": modele.strip(), "type_vehicule": type_v,
                "n_chassis": chassis.strip(), "centre_service": centre,
                "puissance_cv": int(puissance), "imputation": imput,
                "date_premiere_circulation": str(d_circ),
                "date_acquisition": str(d_acq),
                "valeur_acquisition_fcfa": int(valeur), "combustible": comb,
                "conso_nominale_l_100km": float(conso), "km_initial": int(km0),
                "capacite_reservoir_l": int(capacite),
                "niveau_carburant_l": float(niveau),
                "date_niveau": str(pd.Timestamp.now()),
                "date_visite_technique": str(d_vt), "etat_visite_technique": e_vt,
                "date_souscription_assurance": str(d_ass), "etat_assurance": e_ass,
                "date_admission_temporaire": str(d_at), "etat_at": e_at,
                "etat_carte_grise": e_cg, "etat_vehicule": e_veh,
                "remarques": rem.strip(),
            }
    return None


# ══════════════════════════════════════════════════════════════════════
# PAGE
# ══════════════════════════════════════════════════════════════════════
def page_vehicules(d):
    ui.titre_page("Gestion des véhicules", "🚙")
    st.caption("Module véhicules v10.5 — libellés normalisés, immatriculation = identifiant, "
               "conformité cliquable, "
               "suppression avec confirmation, renouvellement de documents")
    veh = d["vehicules"]

    n_alertes = 0
    if veh is not None and not veh.empty:
        tc = table_conformite(veh)
        if len(tc):
            n_alertes = int((tc["Statut"] != "🟢 OK").sum())

    t_conf, t_new, t_liste, t_tpl = st.tabs([
        f"🚨 Conformité ({n_alertes})", "➕ Nouveau véhicule",
        "📋 Liste / Modifier / Supprimer", "📄 Template d'import"])

    # ── 🚨 CONFORMITÉ ─────────────────────────────────────────────────
    with t_conf:
        if veh is None or veh.empty:
            st.info("Aucun véhicule.")
        else:
            tc = table_conformite(veh)
            if tc.empty:
                st.warning("Colonnes de conformité absentes — utilisez le template.")
            else:
                exp = tc[tc["Statut"] == "🔴 EXPIRÉ"]
                bientot = tc[tc["Statut"] == "🟠 Expire sous 30 j"]
                c1, c2, c3 = st.columns(3)
                c1.metric("🔴 Documents expirés", len(exp))
                c2.metric("🟠 Expirent sous 30 jours", len(bientot))
                c3.metric("🟢 En règle", int((tc["Statut"] == "🟢 OK").sum()))

                pb = veh[(veh.get("etat_carte_grise", "") == "Pas bon") |
                         (veh.get("etat_vehicule", "") == "Non fonctionnel")]
                if len(pb):
                    st.error(f"⚠️ {len(pb)} véhicule(s) avec carte grise 'Pas bon' "
                             f"ou non fonctionnel(s) : "
                             f"{', '.join(pb.vehicule_id.head(12))}"
                             + ("…" if len(pb) > 12 else ""))

                a_traiter = tc[tc["Statut"] != "🟢 OK"].sort_values("Jours restants") \
                    .reset_index(drop=True)
                st.subheader("Documents à traiter en priorité")
                if a_traiter.empty:
                    st.success("✅ Toute la flotte est en règle !")
                else:
                    st.caption("👆 **Cliquez sur une ligne** pour enregistrer le "
                               "renouvellement de ce document.")
                    lignes_sel = []
                    try:
                        event = st.dataframe(
                            a_traiter.style.apply(style_statut, axis=1),
                            use_container_width=True, hide_index=True,
                            on_select="rerun", selection_mode="single-row",
                            key=f"tbl_conf_{len(a_traiter)}")
                        lignes_sel = list(event.selection.rows)
                    except TypeError:
                        # Version de Streamlit trop ancienne pour la sélection
                        st.dataframe(a_traiter.style.apply(style_statut, axis=1),
                                     use_container_width=True, hide_index=True)
                        st.info("💡 Mettez à jour Streamlit pour activer la "
                                "sélection par clic : `pip install -U streamlit`")

                    if lignes_sel:
                        r = a_traiter.iloc[lignes_sel[0]]
                        vid, doc = r["Véhicule"], r["Document"]
                        st.markdown(
                            f"#### 🔄 Renouvellement — **{vid}** "
                            f"({r['Immatriculation']}) · {doc}")
                        st.caption(f"Échéance actuelle : {r['Renouvellement']} "
                                   f"({r['Jours restants']} j) — saisissez la "
                                   f"nouvelle date du document.")
                        c1, c2, c3 = st.columns([2, 1, 2])
                        nouvelle = c1.date_input("Nouvelle date du document",
                                                 date.today(), key=f"rd_{vid}_{doc}")
                        netat = c2.selectbox("État", ETATS_DOC, 0,
                                             key=f"re_{vid}_{doc}")
                        echeance = (pd.Timestamp(nouvelle)
                                    + pd.DateOffset(years=1)).date()
                        c3.metric("Nouvelle échéance (calculée)", str(echeance))
                        if st.button("✅ Valider le renouvellement", type="primary",
                                     key=f"rb_{vid}_{doc}"):
                            col_date, _, col_etat = DOCS[doc]
                            veh2 = veh.copy()
                            m = veh2.vehicule_id == vid
                            veh2.loc[m, col_date] = str(nouvelle)
                            veh2.loc[m, col_etat] = netat
                            veh2 = calculer_champs(veh2)
                            ecrire("vehicules.csv", veh2)
                            st.success(f"✅ {doc} de **{vid}** renouvelé(e) le "
                                       f"{nouvelle} — prochaine échéance : "
                                       f"{echeance}. Le véhicule sort des alertes.")
                            st.rerun()

                    st.download_button(
                        "📥 Exporter les alertes (CSV)",
                        a_traiter.to_csv(index=False).encode("utf-8-sig"),
                        "alertes_conformite.csv", "text/csv")

                # ---- 🔄 Saisie manuelle (autre véhicule / hors alerte) ----
                with st.expander("🔄 Enregistrer un renouvellement pour un autre "
                                 "véhicule (hors alertes)"):
                    en_alerte = a_traiter["Véhicule"].unique().tolist() \
                        if not a_traiter.empty else []
                    ordre = en_alerte + [x for x in veh.vehicule_id
                                         if x not in en_alerte]
                    idx_veh = veh.set_index("vehicule_id")
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                    vsel = c1.selectbox(
                        "Véhicule", ordre,
                        format_func=lambda x: f"{x} — "
                        f"{idx_veh.loc[x].get('immatriculation', '')}"
                        + (" 🚨" if x in en_alerte else ""))
                    docsel = c2.selectbox("Document renouvelé", list(DOCS.keys()))
                    nouvelle_m = c3.date_input("Nouvelle date", date.today(),
                                               key="renouv_manuel_date")
                    netat_m = c4.selectbox("État ", ETATS_DOC, 0,
                                           key="renouv_manuel_etat")
                    if st.button("✅ Valider", type="primary",
                                 key="renouv_manuel_btn"):
                        col_date, _, col_etat = DOCS[docsel]
                        veh2 = veh.copy()
                        m = veh2.vehicule_id == vsel
                        veh2.loc[m, col_date] = str(nouvelle_m)
                        veh2.loc[m, col_etat] = netat_m
                        veh2 = calculer_champs(veh2)
                        ecrire("vehicules.csv", veh2)
                        ech = (pd.Timestamp(nouvelle_m)
                               + pd.DateOffset(years=1)).date()
                        st.success(f"✅ {docsel} de **{vsel}** renouvelé(e) — "
                                   f"prochaine échéance : {ech}.")
                        st.rerun()

    # ── ➕ NOUVEAU ─────────────────────────────────────────────────────
    with t_new:
      if auth.bloquer("gerer_vehicules",
                      "🔒 Consultation seule : l'ajout de véhicules est "
                      "réservé aux gestionnaires."):
        pass
      else:
          valeurs = _formulaire_vehicule(None, "form_new_veh")
          if valeurs:
              immat = normaliser_immat(pd.Series([valeurs["immatriculation"]]))[0]
              existantes = set(normaliser_immat(veh.immatriculation)) \
                  if veh is not None and "immatriculation" in veh.columns else set()
              if immat in existantes:
                  st.error(f"❌ L'immatriculation **{immat}** existe déjà. "
                           f"Elle identifie le véhicule de manière unique.")
                  st.stop()
              valeurs["immatriculation"] = immat
              ligne = calculer_champs(pd.DataFrame([valeurs]))
              nouveau = pd.concat([veh if veh is not None else pd.DataFrame(), ligne],
                                  ignore_index=True)
              ecrire("vehicules.csv", nouveau)
              st.success(f"✅ Véhicule **{immat}** enregistré — "
                         f"centre {valeurs['centre_service']}.")
              st.rerun()

    # ── 📋 LISTE / MODIFIER / SUPPRIMER ───────────────────────────────
    with t_liste:
        if veh is None or veh.empty:
            st.info("Aucun véhicule enregistré.")
        else:
            c0, c1, c2, c3 = st.columns([2, 2, 1, 2])
            recherche = c0.text_input(
                "🔍 Recherche (immatriculation, modèle, châssis)",
                placeholder="WV-IT ou 569 ou Hilux…")
            f_ctr = c1.multiselect("Centre de service",
                                   sorted(veh.get("centre_service",
                                                  pd.Series(dtype=str)).dropna().unique()))
            f_typ = c2.multiselect("Type", sorted(veh.type_vehicule.unique()))
            f_eta = c3.multiselect("État véhicule",
                                   sorted(veh.get("etat_vehicule",
                                                  pd.Series(dtype=str)).dropna().unique()))
            v = veh.copy()
            if recherche.strip():
                q = recherche.strip().lower()
                masque = pd.Series(False, index=v.index)
                for col in ["immatriculation", "vehicule_id", "modele", "n_chassis"]:
                    if col in v.columns:
                        masque |= v[col].astype(str).str.lower().str.contains(q, na=False)
                v = v[masque]
            if f_ctr:
                v = v[v.centre_service.isin(f_ctr)]
            if f_typ:
                v = v[v.type_vehicule.isin(f_typ)]
            if f_eta:
                v = v[v.etat_vehicule.isin(f_eta)]

            if len(v):
                etats = v.apply(lambda r: ui.couleur_ligne_vehicule(
                    r.to_dict()), axis=1)
                v = v.assign(**{"état": etats})
                cols = ["état"] + [c for c in v.columns if c != "état"]
                v = v[cols]
            st.dataframe(v, use_container_width=True, hide_index=True)
            st.caption(f"{len(v)} véhicule(s) trouvé(s) · "
                       f"🟢 conforme · 🟠 à renouveler sous 30 j · "
                       f"🔴 expiré ou fiche incomplète")

            if len(v):
                st.divider()
                st.subheader("✏️ Modifier ou supprimer un véhicule")
                if not auth.peut("gerer_vehicules"):
                    st.info("🔒 Consultation seule : la modification et la "
                            "suppression sont réservées aux gestionnaires.")
                    return
                idx = v.set_index("vehicule_id")
                vsel = st.selectbox(
                    "Véhicule (immatriculation)", v.vehicule_id,
                    format_func=lambda x: f"{x} — "
                    f"{idx.loc[x].get('marque', '')} "
                    f"{idx.loc[x].get('modele', '')} "
                    f"({idx.loc[x].get('centre_service', '')})")
                ligne = veh[veh.vehicule_id == vsel].iloc[0].to_dict()

                # Synthèse colorée de l'état du véhicule
                ui.panneau_conformite(ligne)

                # --- Modification par formulaire pré-rempli ---
                valeurs = _formulaire_vehicule(ligne, f"form_edit_{vsel}")
                if valeurs:
                    nouvelle_immat = normaliser_immat(
                        pd.Series([valeurs["immatriculation"]]))[0]
                    autres = set(normaliser_immat(
                        veh[veh.vehicule_id != vsel].immatriculation))
                    if nouvelle_immat in autres:
                        st.error(f"❌ L'immatriculation **{nouvelle_immat}** "
                                 f"est déjà attribuée à un autre véhicule.")
                        st.stop()
                    valeurs["immatriculation"] = nouvelle_immat
                    veh2 = veh.copy()
                    for k, val in valeurs.items():
                        veh2.loc[veh2.vehicule_id == vsel, k] = val
                    veh2 = calculer_champs(veh2)
                    ecrire("vehicules.csv", veh2)
                    # L'immatriculation étant l'identifiant, un changement
                    # doit être répercuté sur l'historique lié
                    n_maj = 0
                    if nouvelle_immat != vsel:
                        for t in ["missions.csv", "carburant.csv",
                                  "maintenance.csv"]:
                            df_t = lire(t)
                            if df_t is None or "vehicule_id" not in df_t.columns:
                                continue
                            m = df_t.vehicule_id == vsel
                            if m.any():
                                df_t.loc[m, "vehicule_id"] = nouvelle_immat
                                ecrire(t, df_t)
                                n_maj += int(m.sum())
                    st.success(
                        f"✅ Véhicule **{nouvelle_immat}** mis à jour"
                        + (f" — immatriculation modifiée depuis {vsel}, "
                           f"{n_maj} ligne(s) d'historique mise(s) à jour."
                           if nouvelle_immat != vsel
                           else " (échéances recalculées)."))
                    st.rerun()

                # --- Suppression avec confirmation oui/non ---
                st.markdown("")
                if st.button(f"🗑️ Supprimer le véhicule {vsel}"):
                    st.session_state["confirm_suppr"] = vsel
                if st.session_state.get("confirm_suppr") == vsel:
                    st.warning(
                        f"⚠️ **Voulez-vous confirmer la suppression du "
                        f"véhicule {vsel} ({ligne.get('marque', '')} "
                        f"{ligne.get('modele', '')}) ?** "
                        f"L'historique (missions, pleins, entretiens) sera conservé "
                        f"mais ne sera plus rattaché à un véhicule actif.")
                    c1, c2, _ = st.columns([1, 1, 3])
                    if c1.button("✅ Oui, supprimer", type="primary"):
                        veh2 = veh[veh.vehicule_id != vsel]
                        ecrire("vehicules.csv", veh2)
                        del st.session_state["confirm_suppr"]
                        st.success(f"🗑️ Véhicule **{vsel}** supprimé.")
                        st.rerun()
                    if c2.button("❌ Non, annuler"):
                        del st.session_state["confirm_suppr"]
                        st.rerun()

    # ── 📄 TEMPLATE ───────────────────────────────────────────────────
    with t_tpl:
        st.markdown(
            "Téléchargez le modèle, remplissez-le (une ligne = un véhicule), "
            "puis importez-le dans **📥 Import données réelles**.\n\n"
            "- Colonnes *(calculé)* : laissez vide, l'application les remplit.\n"
            "- Dates au format **AAAA-MM-JJ**.\n"
            "- `type_vehicule` : Voiture ou Moto · `combustible` : Gasoil ou Super · "
            "états : Bon / Pas bon.")
        tpl = construire_template()
        st.dataframe(tpl, use_container_width=True, hide_index=True)
        c1, c2 = st.columns(2)
        c1.download_button("⬇️ Template CSV",
                           tpl.to_csv(index=False).encode("utf-8-sig"),
                           "template_vehicules.csv", "text/csv",
                           use_container_width=True)
        buf = io.BytesIO()
        tpl.to_excel(buf, index=False, engine="openpyxl")
        c2.download_button("⬇️ Template Excel", buf.getvalue(),
                           "template_vehicules.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
