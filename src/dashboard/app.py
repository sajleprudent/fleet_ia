"""
Fleet-IA — Application complète de gestion prédictive de flotte
World Vision Sénégal

Lancement :  streamlit run src/dashboard/app.py

Pages :
  📊 Vue d'ensemble          KPIs et graphiques de la flotte
  🚙 Véhicules               consultation / ajout / modification / suppression
  👤 Chauffeurs              consultation / ajout / modification / suppression
  🗺️ Missions                saisie et historique des déplacements
  ⛽ Carburant               saisie des pleins + analyse de consommation
  🛠️ Maintenance             saisie des interventions + historique
  🔮 Prédictions             risque de panne à 30 jours (modèle ML)
  📤 Extraction              export filtré de toutes les tables (CSV/Excel)
  📥 Import données réelles  remplacement de la simulation par vos fichiers
"""
import io
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path

SRC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(SRC / "dashboard"))

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from config import (DATA_RAW, DATA_PROCESSED, MODELS_DIR, TYPES_VEHICULES,
                    LOCALITES, MARQUES, TYPES_PANNES, PRIX_CARBURANT,
                    CENTRES_SERVICE)
from crud import (lire, ecrire, prochain_id, editeur_table,
                  compter as crud_compter)
import auth
import ui
import referentiels

# ── Identité visuelle World Vision ───────────────────────────────────
WV_ROUGE = "#E2231A"      # rouge de la marque
WV_ORANGE = "#F58220"     # orange de la marque
WV_TITRE = "#C2570A"      # orange assombri : lisible en gros titres
NAV_FONCE = "#7E3410"     # terre brûlée pour la navigation
APP_VERSION = "v10.7"
st.set_page_config(page_title="Fleet-IA — World Vision Sénégal",
                   page_icon="🚙", layout="wide")


# Valeurs canoniques : toute variante de casse ou d'accent y est ramenée
CANONIQUES = {
    "localite": ["Bureau National", "Zone Centre", "Zone Sud"],
    "centre_service": list(CENTRES_SERVICE.keys()),
    "type_vehicule": ["Voiture", "Moto"],
    "combustible": ["Gasoil", "Super"],
    "etat_vehicule": ["Fonctionnel", "Non fonctionnel"],
    "etat_visite_technique": ["Bon", "Pas bon"],
    "etat_assurance": ["Bon", "Pas bon"],
    "etat_at": ["Bon", "Pas bon"],
    "etat_carte_grise": ["Bon", "Pas bon"],
    "type_intervention": ["Panne", "Entretien préventif"],
    "actif": ["Oui", "Non"],
}
# Colonnes mises en Capitales Initiales (marques, modèles, noms de personnes)
CAPITALISER = ["marque", "modele"]


def _sans_acc(t):
    return "".join(c for c in unicodedata.normalize("NFD", str(t).strip())
                   if unicodedata.category(c) != "Mn").lower()


def normaliser_libelles(df):
    """« ZONE CENTRE », « zone centre » et « Zone Centre » désignent la même
    chose : on ramène chaque libellé à sa forme canonique pour que les
    regroupements et les graphiques ne les comptent pas séparément."""
    if df is None or df.empty:
        return df
    df = df.copy()
    for col, valeurs in CANONIQUES.items():
        if col in df.columns:
            table = {_sans_acc(v): v for v in valeurs}
            df[col] = df[col].map(
                lambda x, t=table: t.get(_sans_acc(x), str(x).strip())
                if pd.notna(x) else x)
    for col in CAPITALISER:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.title() \
                              .replace({"Nan": None, "None": None})
    return df


@st.cache_data
def charger():
    return {n: normaliser_libelles(lire(f"{n}.csv")) for n in
            ["vehicules", "staffs", "chauffeurs", "missions", "carburant",
             "maintenance"]}


# ══════════════════════════════════════════════════════════════════════
# Mise en page : titres, cartes, thème
# ══════════════════════════════════════════════════════════════════════
titre_page = ui.titre_page      # définis dans ui.py, partagés par les pages
carte = ui.carte


def appliquer_theme():
    """Couleurs de marque appliquées à la navigation, aux indicateurs et
    aux onglets. Complément esthétique : l'essentiel de la mise en forme
    ne dépend pas de cette feuille de style."""
    st.markdown(f"""<style>
      section[data-testid="stSidebar"] > div {{
          background: linear-gradient(180deg, {NAV_FONCE} 0%, #5E2610 100%);
      }}
      section[data-testid="stSidebar"] * {{ color: #FBEDE3; }}
      section[data-testid="stSidebar"] [role="radiogroup"] label {{
          padding: 2px 6px; border-radius: 6px;
      }}
      section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{
          background: rgba(255,255,255,.10);
      }}
      section[data-testid="stSidebar"] .stButton button {{
          background: rgba(255,255,255,.12);
          border: 1px solid rgba(255,255,255,.30); color: #fff;
      }}
      div[data-testid="stMetric"] {{
          background: #FFFFFF; border: 1px solid #ECE7E1;
          border-left: 4px solid {WV_ORANGE}; border-radius: 10px;
          padding: 12px 14px; box-shadow: 0 1px 3px rgba(30,20,10,.05);
      }}
      div[data-testid="stMetricValue"] {{
          color: #23303E; font-size: 1.6rem; white-space: nowrap;
      }}
      button[data-baseweb="tab"][aria-selected="true"] {{
          color: {WV_TITRE} !important;
      }}
      div[data-baseweb="tab-highlight"] {{ background-color: {WV_ORANGE}; }}
      section.main h2, section.main h3 {{ color: #33404F; }}
    </style>""", unsafe_allow_html=True)


def logo_entete():
    """Logo World Vision en haut à droite. le fichier est dans
    src/dashboard/assets/logo_wv.png ; sinon un libellé le remplace."""
    import base64
    dossier = Path(__file__).resolve().parent / "assets"
    contenu = None
    for nom in ("logo_wv.png", "logo_wv.jpg", "logo.png"):
        f = dossier / nom
        if f.exists():
            b64 = base64.b64encode(f.read_bytes()).decode()
            mime = "jpeg" if f.suffix in (".jpg", ".jpeg") else "png"
            contenu = (f"<img src='data:image/{mime};base64,{b64}' "
                       f"style='height:40px'>")
            break
    if contenu is None:
        contenu = (f"<span style='font-family:Segoe UI,sans-serif;"
                   f"font-weight:700;font-size:18px;color:#33404F'>World "
                   f"Vision <span style='color:{WV_ORANGE}'>✦</span></span>")
    st.markdown(
        f"<div style='position:fixed;top:58px;right:22px;z-index:999;"
        f"background:rgba(255,255,255,.92);padding:6px 14px;border-radius:10px;"
        f"box-shadow:0 1px 4px rgba(0,0,0,.08)'>{contenu}</div>",
        unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════
# 📊 VUE D'ENSEMBLE
# ══════════════════════════════════════════════════════════════════════
# Utilitaires de lecture (encodages Excel, formats de dates mixtes)
# ══════════════════════════════════════════════════════════════════════
def lire_csv_robuste(fichier):
    """Lit un CSV quel que soit son encodage (UTF-8, UTF-8 BOM, Windows
    cp1252, latin-1) et son séparateur (virgule ou point-virgule).
    Excel en environnement français produit du cp1252 avec des ';'.
    Retourne (DataFrame, encodage détecté, séparateur détecté)."""
    import io
    brut = fichier.read() if hasattr(fichier, "read") else open(fichier, "rb").read()
    if hasattr(fichier, "seek"):
        fichier.seek(0)
    texte = encodage = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            texte, encodage = brut.decode(enc), enc
            break
        except UnicodeDecodeError:
            continue
    if texte is None:
        texte, encodage = brut.decode("latin-1", errors="replace"), "latin-1"
    premiere = texte.split("\n", 1)[0]
    sep = ";" if premiere.count(";") > premiere.count(",") else ","
    return pd.read_csv(io.StringIO(texte), sep=sep), encodage, sep


def attribuer_ids(df, colonne, prefixe, largeur):
    """Complète les identifiants manquants sans écraser ceux fournis.

    Tolère : colonne absente, entièrement vide, texte du template, ou
    identifiants non numériques. Ajoute une colonne temporaire
    `_id_genere` indiquant les lignes complétées.
    """
    df = df.copy()
    placeholders = {"", "nan", "none", "(laisser vide : généré automatiquement)"}
    if colonne not in df.columns:
        df[colonne] = pd.NA
    valeurs = df[colonne].astype(str).str.strip()
    vide = df[colonne].isna() | valeurs.str.lower().isin(placeholders)
    df["_id_genere"] = vide
    if not vide.any():
        return df
    nums = pd.to_numeric(valeurs.where(~vide).str.extract(r"(\d+)$")[0],
                         errors="coerce").dropna()
    base = int(nums.max()) if len(nums) else 0
    df.loc[vide, colonne] = [f"{prefixe}{base + i + 1:0{largeur}d}"
                             for i in range(int(vide.sum()))]
    # Doublons éventuels entre identifiants fournis et générés
    if df[colonne].duplicated().any():
        n = base + int(vide.sum())
        for idx in df.index[df[colonne].duplicated()]:
            n += 1
            df.loc[idx, colonne] = f"{prefixe}{n:0{largeur}d}"
    return df


def _dates(df, cols):
    """Convertit des colonnes en dates, y compris si les formats sont
    mélangés (2023-07-01 et 2026-07-14 07:00:00)."""
    if df is None or not len(df):
        return df
    df = df.copy()
    for c in cols:
        if c in df.columns:
            try:
                df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
            except (ValueError, TypeError):
                df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


# ══════════════════════════════════════════════════════════════════════
# Charte graphique des visualisations
# ══════════════════════════════════════════════════════════════════════
PALETTE = ["#E2231A", "#F58220", "#2E5496", "#4A90A4", "#7B8794", "#C9CFD6"]
GRIS_TXT = "#3C4552"


def _style(fig, hauteur=330, sans_legende=False, marge_gauche=10):
    """Applique une mise en forme sobre et homogène à toutes les figures."""
    fig.update_layout(
        height=hauteur,
        margin=dict(l=marge_gauche, r=14, t=32, b=10),
        font=dict(family="Segoe UI, Helvetica, sans-serif", size=12,
                  color=GRIS_TXT),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(bgcolor="white", font_size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                    title_text="", bgcolor="rgba(0,0,0,0)"),
        showlegend=not sans_legende,
        xaxis=dict(showgrid=False, zeroline=False,
                   linecolor="#E3E7EC", ticks="outside", tickcolor="#E3E7EC"),
        yaxis=dict(gridcolor="#EEF1F4", zeroline=False, linecolor="rgba(0,0,0,0)"),
    )
    return fig


def _barres_h(df, x, y, titre, couleur=None, suffixe="", hauteur=320):
    """Barres horizontales triées — format le plus lisible pour un top N."""
    d = df.sort_values(x)
    fig = px.bar(d, x=x, y=y, orientation="h", text=d[x],
                 color=couleur, color_discrete_sequence=PALETTE)
    fig.update_traces(
        texttemplate="%{text:,.0f}" + suffixe, textposition="outside",
        cliponaxis=False,
        marker_line_width=0, width=0.72)
    if couleur is None:
        fig.update_traces(marker_color=PALETTE[2])
    fig.update_layout(title=dict(text=titre, font=dict(size=14)))
    fig.update_xaxes(title_text="", showticklabels=False)
    fig.update_yaxes(title_text="")
    return _style(fig, hauteur, sans_legende=couleur is None, marge_gauche=4)


# ══════════════════════════════════════════════════════════════════════
# 📊 VUE D'ENSEMBLE
# ══════════════════════════════════════════════════════════════════════
def page_vue_ensemble(d):
    titre_page("Vue d'ensemble de la flotte", "📊")
    veh, mis, fuel, mnt = (d["vehicules"], d["missions"], d["carburant"],
                           d["maintenance"])
    staffs = d.get("staffs")
    if veh is None or veh.empty:
        st.error("Aucune donnée véhicule. Importez votre parc dans "
                 "📥 Import données réelles.")
        return

    mis = _dates(mis, ["date_depart", "date_fin"])
    fuel = _dates(fuel, ["date"])
    mnt = _dates(mnt, ["date"])

    # ── Période d'analyse ─────────────────────────────────────────────
    ref = mis.date_depart.max() if mis is not None and len(mis) \
        else pd.Timestamp.today()
    if pd.isna(ref):
        ref = pd.Timestamp.today()
    choix = st.radio("Période d'analyse", ["3 mois", "6 mois", "12 mois",
                                           "Tout l'historique"],
                     index=2, horizontal=True, label_visibility="collapsed")
    jours = {"3 mois": 90, "6 mois": 182, "12 mois": 365,
             "Tout l'historique": 100_000}[choix]
    debut = ref - pd.Timedelta(days=jours)

    m = mis[mis.date_depart >= debut].copy() if mis is not None and len(mis) \
        else pd.DataFrame()
    # Seules les missions réellement effectuées comptent dans l'activité
    if len(m) and "statut" in m.columns:
        effectuees = m.statut.astype(str).str.lower().isin(
            ["approved", "approuvée", "terminée", ""])
        m = m[effectuees | m.statut.isna()]
    f = fuel[fuel.date >= debut] if fuel is not None and len(fuel) \
        else pd.DataFrame()
    k = mnt[mnt.date >= debut] if mnt is not None and len(mnt) \
        else pd.DataFrame()
    pannes = k[k.type_intervention == "Panne"] if len(k) else pd.DataFrame()

    # ── Indicateurs clés ──────────────────────────────────────────────
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Véhicules", len(veh))
    dispo = (veh.etat_vehicule == "Fonctionnel").sum() \
        if "etat_vehicule" in veh.columns else len(veh)
    c2.metric("Disponibles", f"{dispo}", f"{dispo / len(veh) * 100:.0f} % du parc",
              delta_color="off")
    age = ref.year - pd.to_numeric(veh.get("annee_mise_en_service"),
                                   errors="coerce").mean()
    c3.metric("Âge moyen", f"{age:.1f} ans" if pd.notna(age) else "—")
    c4.metric("Missions", f"{len(m):,}".replace(",", " "))
    km = m.distance_km.sum() if len(m) and "distance_km" in m.columns else 0
    c5.metric("Kilomètres", f"{km:,.0f}".replace(",", " "))
    c6.metric("Pannes", len(pannes))

    st.divider()

    # ══ PARC ══════════════════════════════════════════════════════════
    st.subheader("Composition du parc")
    g, dr = st.columns(2)
    with g:
        cle = "localite" if "localite" in veh.columns else "centre_service"
        rep = veh.groupby([cle, "type_vehicule"]).size().reset_index(name="n")
        fig = px.bar(rep, x=cle, y="n", color="type_vehicule",
                     color_discrete_sequence=PALETTE[2:], text="n")
        fig.update_traces(marker_line_width=0, textposition="inside")
        fig.update_layout(title=dict(text="Répartition par zone et type",
                                     font=dict(size=14)), barmode="stack")
        fig.update_xaxes(title_text="")
        fig.update_yaxes(title_text="Véhicules")
        carte(_style(fig), "Effectif par zone opérationnelle, ventilé "
              "par type de véhicule.")
    with dr:
        an = pd.to_numeric(veh.get("annee_mise_en_service"), errors="coerce")
        ages = (ref.year - an).dropna()
        if len(ages):
            tr = pd.cut(ages, [-1, 3, 6, 9, 12, 100],
                        labels=["0-3 ans", "4-6 ans", "7-9 ans",
                                "10-12 ans", "13 ans et +"])
            dd = tr.value_counts().sort_index().reset_index()
            dd.columns = ["tranche", "n"]
            fig = px.bar(dd, x="tranche", y="n", text="n",
                         color_discrete_sequence=[PALETTE[0]])
            fig.update_traces(marker_line_width=0, textposition="outside",
                              cliponaxis=False)
            fig.update_layout(title=dict(text="Pyramide des âges du parc",
                                         font=dict(size=14)))
            fig.update_xaxes(title_text="")
            fig.update_yaxes(title_text="Véhicules")
            carte(_style(fig, sans_legende=True),
                  "Répartition du parc par tranche d'âge : un parc "
                  "vieillissant appelle une politique de renouvellement.")

    if not len(m):
        st.info("Aucune mission sur la période sélectionnée.")
        return

    # ══ ACTIVITÉ ══════════════════════════════════════════════════════
    st.divider()
    st.subheader("Activité et sollicitation")
    st.caption(f"Période : {debut.date()} → {ref.date()} · "
               f"missions effectuées uniquement")

    lib_veh = veh.set_index("vehicule_id")
    g, dr = st.columns(2)
    with g:
        top_v = (m.groupby("vehicule_id")
                  .agg(missions=("numero_mission", "count"),
                       km=("distance_km", "sum"))
                  .nlargest(10, "missions").reset_index())
        top_v["libelle"] = top_v.vehicule_id.map(
            lambda x: f"{x} · {lib_veh.loc[x, 'modele']}"
            if x in lib_veh.index and pd.notna(lib_veh.loc[x].get("modele"))
            else str(x))
        carte(_barres_h(top_v, "missions", "libelle",
                        "Top 10 des véhicules les plus mobilisés"),
              "Nombre de missions effectuées sur la période.")
    with dr:
        top_km = (m.groupby("vehicule_id").distance_km.sum()
                   .nlargest(10).reset_index())
        top_km["libelle"] = top_km.vehicule_id.map(
            lambda x: f"{x} · {lib_veh.loc[x, 'modele']}"
            if x in lib_veh.index and pd.notna(lib_veh.loc[x].get("modele"))
            else str(x))
        carte(_barres_h(top_km, "distance_km", "libelle",
                        "Top 10 des véhicules les plus exposés (km)",
                        suffixe=" km"),
              "Kilométrage cumulé : premier facteur d'usure.")

    # ── Staffs ────────────────────────────────────────────────────────
    if staffs is not None and len(staffs):
        noms = staffs.set_index(staffs.staff_id.astype(str)).nom_complet
        g, dr = st.columns(2)
        with g:
            if "personnes_ids" in m.columns:
                part = (m.personnes_ids.fillna("").astype(str)
                        .str.split(",").explode().str.strip())
                part = part[part != ""]
            else:
                part = m.get("agent_id", pd.Series(dtype=str)).astype(str)
            if len(part):
                top_s = part.value_counts().head(10).reset_index()
                top_s.columns = ["staff_id", "missions"]
                top_s["libelle"] = top_s.staff_id.map(
                    lambda x: noms.get(x, x))
                carte(_barres_h(top_s, "missions", "libelle",
                                "Top 10 des staffs les plus en mission"),
                      "Agents comptés comme participants réels.")
        with dr:
            if "chauffeur_id" in m.columns and "duree_jours" in m.columns:
                exp = (m.assign(cid=m.chauffeur_id.astype(str))
                        .groupby("cid")
                        .agg(jours=("duree_jours", "sum"),
                             km=("distance_km", "sum"))
                        .nlargest(10, "jours").reset_index())
                exp["libelle"] = exp.cid.map(lambda x: noms.get(x, x))
                carte(_barres_h(exp, "jours", "libelle",
                                "Top 10 des chauffeurs les plus exposés "
                                "(jours sur la route)", suffixe=" j"),
                      "Jours passés en mission : indicateur de fatigue.")

    # ══ MAINTENANCE ═══════════════════════════════════════════════════
    st.divider()
    st.subheader("Maintenance et coûts")
    g, dr = st.columns(2)
    with g:
        if len(pannes):
            pm = (pannes.assign(mois=pannes.date.dt.to_period("M")
                                .dt.to_timestamp())
                  .groupby("mois").size().reset_index(name="pannes"))
            fig = px.area(pm, x="mois", y="pannes", markers=True,
                          color_discrete_sequence=[PALETTE[0]])
            fig.update_traces(line=dict(width=2.5),
                              fillcolor="rgba(226,35,26,0.10)")
            fig.update_layout(title=dict(text="Évolution mensuelle des pannes",
                                         font=dict(size=14)))
            fig.update_xaxes(title_text="")
            fig.update_yaxes(title_text="Pannes", rangemode="tozero")
            carte(_style(fig, sans_legende=True),
                  "Évolution du nombre de pannes mois par mois.")
        else:
            st.info("Aucune panne enregistrée sur la période.")
    with dr:
        if len(k) and "localite" in veh.columns:
            kl = k.merge(veh[["vehicule_id", "localite"]], on="vehicule_id")
            cl = kl.groupby(["localite", "type_intervention"]) \
                   .cout_fcfa.sum().reset_index()
            cl["millions"] = cl.cout_fcfa / 1e6
            fig = px.bar(cl, x="localite", y="millions",
                         color="type_intervention", barmode="group",
                         color_discrete_sequence=[PALETTE[0], PALETTE[4]],
                         text="millions")
            fig.update_traces(texttemplate="%{text:.1f}", marker_line_width=0,
                              textposition="outside", cliponaxis=False)
            fig.update_layout(title=dict(text="Coûts de maintenance par zone "
                                              "(millions FCFA)",
                                         font=dict(size=14)))
            fig.update_xaxes(title_text="")
            fig.update_yaxes(title_text="M FCFA")
            carte(_style(fig), "Dépenses de maintenance par zone, "
                  "distinguant préventif et curatif.")

    # ── Répartition des pannes & carburant ────────────────────────────
    g, dr = st.columns(2)
    with g:
        if len(pannes) and "categorie" in pannes.columns:
            cat = pannes.categorie.value_counts().head(8).reset_index()
            cat.columns = ["categorie", "n"]
            carte(_barres_h(cat, "n", "categorie",
                            "Pannes par organe défaillant", hauteur=300),
                  "Organes les plus fréquemment défaillants.")
    with dr:
        if len(f) and "montant_fcfa" in f.columns:
            fm = (f.assign(mois=f.date.dt.to_period("M").dt.to_timestamp())
                   .groupby("mois").montant_fcfa.sum().reset_index())
            fm["millions"] = fm.montant_fcfa / 1e6
            fig = px.bar(fm, x="mois", y="millions",
                         color_discrete_sequence=[PALETTE[1]])
            fig.update_traces(marker_line_width=0)
            fig.update_layout(title=dict(text="Dépense carburant mensuelle "
                                              "(millions FCFA)",
                                         font=dict(size=14)))
            fig.update_xaxes(title_text="")
            fig.update_yaxes(title_text="M FCFA")
            carte(_style(fig, sans_legende=True),
                  f"Total sur la période : "
                  f"{f.montant_fcfa.sum() / 1e6:,.1f} M FCFA")


# ══════════════════════════════════════════════════════════════════════
# 🚙 VÉHICULES — voir vehicules_page.py
# ══════════════════════════════════════════════════════════════════════
from vehicules_page import (page_vehicules, table_conformite, niveau_reservoir)


# ══════════════════════════════════════════════════════════════════════
# 👥 STAFFS & RÔLES — voir staffs_page.py (remplace la page Chauffeurs :
#    chauffeur/approbateur/gestionnaire/admin sont des rôles des staffs)
# ══════════════════════════════════════════════════════════════════════
from staffs_page import page_staffs, initialiser_staffs


# ══════════════════════════════════════════════════════════════════════
# 🗺️ MISSIONS — voir missions_page.py
# ══════════════════════════════════════════════════════════════════════
from missions_page import page_missions, page_approbations


# ══════════════════════════════════════════════════════════════════════
# ⛽ CARBURANT (saisie + analyse)
# ══════════════════════════════════════════════════════════════════════
def page_carburant(d):
    titre_page("Carburant", "⛽")
    veh, mis, fuel = d["vehicules"], d["missions"], d["carburant"]
    t1, t2, t3 = st.tabs(["➕ Saisir un plein", "📜 Historique", "📈 Analyse"])

    # ══ SAISIE ════════════════════════════════════════════════════════
    with t1:
        if auth.bloquer("gerer_carburant",
                        "🔒 Consultation seule : la saisie des pleins est "
                        "réservée aux gestionnaires."):
            pass
        elif veh is None or veh.empty:
            st.warning("Enregistrez d'abord des véhicules.")
        else:
            idx_v = veh.set_index("vehicule_id")

            def _lib(x):
                r = idx_v.loc[x]
                mo = r.get("modele") or r.get("type_vehicule") or ""
                return f"{x} — {mo} ({r.get('centre_service', '')})"

            vsel = st.selectbox("Véhicule *", veh.vehicule_id,
                                format_func=_lib, key="carb_veh")
            v = idx_v.loc[vsel].to_dict()
            v["vehicule_id"] = vsel
            etat = niveau_reservoir(v, mis)

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Capacité", f"{etat['capacite']:.0f} L")
            c2.metric("Carburant en cours", f"{etat['niveau']:.0f} L",
                      f"{etat['pourcentage']:.0f} % du réservoir",
                      delta_color="off")
            c3.metric("Chargeable au maximum", f"{etat['disponible']:.0f} L")
            if etat["consomme"]:
                c4.metric("Consommé depuis le dernier relevé",
                          f"-{etat['consomme']:.0f} L", delta_color="off")
            st.progress(min(1.0, etat["niveau"] / max(1, etat["capacite"])))

            plein = etat["disponible"] <= max(2.0, etat["capacite"] * 0.05)
            if plein:
                st.success(f"⛽ **Véhicule déjà chargé** — le réservoir "
                           f"contient {etat['niveau']:.0f} L sur "
                           f"{etat['capacite']:.0f} L. Un nouveau plein "
                           f"n'est pas nécessaire.")
            elif etat["niveau"] <= etat["capacite"] * 0.15:
                st.warning(f"🔻 Réservoir presque vide : "
                           f"{etat['niveau']:.0f} L restants.")

            # Missions proposées : celles de ce véhicule, plus celles qui
            # n'ont pas encore de véhicule affecté
            mis_dispo = pd.DataFrame()
            if mis is not None and len(mis):
                col_v = mis.get("vehicule_id", pd.Series(dtype=str)).astype(str)
                sans_veh = col_v.isin(["", "nan", "None"]) | mis.vehicule_id.isna()
                mis_dispo = mis[(col_v == str(vsel)) | sans_veh] \
                    .sort_values("date_depart", ascending=False).head(100)

            with st.form("form_fuel", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                maxi = max(0.5, etat["disponible"])
                litres = c1.number_input(
                    f"Litres (maximum {maxi:.0f} L) *", 0.5, float(maxi),
                    float(maxi) if not plein else 0.5, step=1.0,
                    help="Limité à l'espace disponible : on ne peut pas "
                         "charger au-delà de la capacité du réservoir.")
                prix_l = c2.number_input("Prix/litre (FCFA)", 400, 2000,
                                         PRIX_CARBURANT)
                dte = c3.date_input("Date du plein", date.today())

                options = ["(aucune)"] + list(mis_dispo.numero_mission) \
                    if len(mis_dispo) else ["(aucune)"]

                def _libm(x):
                    if x == "(aucune)":
                        return x
                    r = mis_dispo.set_index("numero_mission").loc[x]
                    marque = "" if str(r.get("vehicule_id") or "") == str(vsel) \
                        else "  ⚠️ sans véhicule affecté"
                    return (f"{x} → {r.get('destination', '')} "
                            f"({pd.Timestamp(r['date_depart']).date()})"
                            f"{marque}")

                midx = st.selectbox("Mission concernée (recommandé)", options,
                                    format_func=_libm)
                st.caption("Seules les missions de ce véhicule et celles sans "
                           "véhicule affecté sont proposées. Le rattachement "
                           "permet de calculer la consommation aux 100 km.")

                if st.form_submit_button("Enregistrer le plein",
                                         type="primary", disabled=plein):
                    if litres > etat["disponible"] + 0.01:
                        st.error(f"❌ {litres:.0f} L dépassent l'espace "
                                 f"disponible ({etat['disponible']:.0f} L).")
                    else:
                        fid = prochain_id(fuel, "plein_id", "FL-", 6)
                        chauf = None
                        if midx != "(aucune)" and len(mis_dispo):
                            chauf = mis_dispo.set_index("numero_mission") \
                                .loc[midx].get("chauffeur_id")
                        ligne = {"plein_id": fid,
                                 "numero_mission": None if midx == "(aucune)"
                                 else midx,
                                 "vehicule_id": vsel, "chauffeur_id": chauf,
                                 "date": str(dte), "litres": float(litres),
                                 "montant_fcfa": int(litres * prix_l)}
                        ecrire("carburant.csv", pd.concat(
                            [fuel if fuel is not None else pd.DataFrame(),
                             pd.DataFrame([ligne])], ignore_index=True))
                        # Si la mission n'avait pas de véhicule, on l'affecte
                        if midx != "(aucune)" and mis is not None:
                            m2 = mis.copy()
                            cible = m2.numero_mission == midx
                            vide = m2.loc[cible, "vehicule_id"].isna().all() \
                                or (m2.loc[cible, "vehicule_id"].astype(str)
                                    .isin(["", "nan", "None"]).all())
                            if vide:
                                m2.loc[cible, "vehicule_id"] = vsel
                                ecrire("missions.csv", m2)
                        veh2 = veh.copy()
                        veh2.loc[veh2.vehicule_id == vsel,
                                 "niveau_carburant_l"] = round(
                            min(etat["capacite"], etat["niveau"] + litres), 1)
                        veh2.loc[veh2.vehicule_id == vsel,
                                 "date_niveau"] = str(pd.Timestamp.now())
                        ecrire("vehicules.csv", veh2)
                        st.success(
                            f"✅ Plein **{fid}** : {litres:.0f} L pour "
                            f"{int(litres * prix_l):,} FCFA — réservoir à "
                            f"{min(etat['capacite'], etat['niveau'] + litres):.0f} L"
                            .replace(",", " "))
                        st.rerun()

            with st.expander("🔧 Corriger le niveau de carburant "
                             "(relevé de jauge)"):
                st.caption("À utiliser si la jauge ne correspond pas à "
                           "l'estimation : siphonnage, fuite, ou "
                           "consommation réelle différente de l'estimation.")
                c1, c2 = st.columns([2, 1])
                corrige = c1.number_input(
                    "Niveau relevé (L)", 0.0, float(etat["capacite"]),
                    float(etat["niveau"]), step=1.0, key="corr_niv")
                if c2.button("Enregistrer le relevé"):
                    veh2 = veh.copy()
                    veh2.loc[veh2.vehicule_id == vsel,
                             "niveau_carburant_l"] = round(corrige, 1)
                    veh2.loc[veh2.vehicule_id == vsel,
                             "date_niveau"] = str(pd.Timestamp.now())
                    ecrire("vehicules.csv", veh2)
                    st.success(f"✅ Niveau de {vsel} fixé à {corrige:.0f} L.")
                    st.rerun()

    # ══ HISTORIQUE ════════════════════════════════════════════════════
    with t2:
        if fuel is None or fuel.empty:
            st.info("Aucun plein enregistré.")
        else:
            f = _dates(fuel.copy(), ["date"])
            c1, c2, c3 = st.columns(3)
            vfil = c1.selectbox("Véhicule", ["(tous)"]
                                + sorted(f.vehicule_id.dropna().unique()),
                                key="hist_veh")
            nj = c2.slider("Période (derniers jours)", 7, 1200, 365,
                           key="hist_nj")
            lien = c3.selectbox("Rattachement",
                                ["(tous)", "Rattachés à une mission",
                                 "Sans mission"], key="hist_lien")
            ref = f.date.max()
            if pd.notna(ref):
                f = f[f.date >= ref - pd.Timedelta(days=nj)]
            if vfil != "(tous)":
                f = f[f.vehicule_id == vfil]
            if lien == "Rattachés à une mission":
                f = f[f.get("numero_mission").notna()]
            elif lien == "Sans mission":
                f = f[f.get("numero_mission").isna()]

            c1, c2, c3 = st.columns(3)
            c1.metric("Pleins", len(f))
            c2.metric("Volume total", f"{f.litres.sum():,.0f} L"
                      .replace(",", " "))
            c3.metric("Dépense", f"{f.montant_fcfa.sum():,.0f} FCFA"
                      .replace(",", " "))

            cols = [c for c in ["plein_id", "date", "vehicule_id",
                                "numero_mission", "chauffeur_id", "litres",
                                "montant_fcfa"] if c in f.columns]
            st.dataframe(f.sort_values("date", ascending=False)[cols],
                         use_container_width=True, hide_index=True)
            st.download_button("📥 Exporter (CSV)",
                               f[cols].to_csv(index=False).encode("utf-8-sig"),
                               "historique_carburant.csv", "text/csv")

            if len(f) > 1:
                top = (f.groupby("vehicule_id")
                       .agg(litres=("litres", "sum"),
                            depense=("montant_fcfa", "sum"))
                       .nlargest(min(10, f.vehicule_id.nunique()), "depense")
                       .reset_index())
                carte(_barres_h(top, "litres", "vehicule_id",
                                "Volume chargé par véhicule (litres)",
                                suffixe=" L"),
                      "Volumes cumulés sur la période filtrée.")

    # ══ ANALYSE ═══════════════════════════════════════════════════════
    with t3:
        if fuel is None or fuel.empty:
            st.info("Aucun plein enregistré : l'analyse sera disponible dès "
                    "les premières saisies.")
            return
        f = _dates(fuel.copy(), ["date"])

        c1, c2, c3 = st.columns(3)
        c1.metric("Dépense totale",
                  f"{f.montant_fcfa.sum() / 1e6:,.1f} M FCFA")
        c2.metric("Volume total", f"{f.litres.sum():,.0f} L".replace(",", " "))
        c3.metric("Prix moyen du litre",
                  f"{f.montant_fcfa.sum() / max(1, f.litres.sum()):,.0f} FCFA")

        # Consommation : uniquement sur les pleins rattachés à une mission
        rattaches = pd.DataFrame()
        if mis is not None and len(mis) and "numero_mission" in f.columns:
            rattaches = f.merge(
                mis[["numero_mission", "distance_km"]].drop_duplicates(),
                on="numero_mission", how="inner")
            if veh is not None and "conso_nominale_l_100km" in veh.columns:
                rattaches = rattaches.merge(
                    veh[["vehicule_id", "conso_nominale_l_100km"]]
                    .drop_duplicates("vehicule_id"),
                    on="vehicule_id", how="left")

        n_lies = len(rattaches)
        st.caption(f"{n_lies} plein(s) sur {len(f)} sont rattachés à une "
                   f"mission — seuls ceux-là permettent de calculer la "
                   f"consommation aux 100 km.")

        r = pd.DataFrame()
        if n_lies:
            r = rattaches[pd.to_numeric(rattaches.distance_km,
                                        errors="coerce").fillna(0) > 0].copy()
            if len(r):
                r["conso_100"] = r.litres / r.distance_km * 100
                r["nominale"] = pd.to_numeric(
                    r.get("conso_nominale_l_100km"), errors="coerce").fillna(10)
                r["surconso_pct"] = (r.conso_100 / r.nominale - 1) * 100
                r = r[r.conso_100.between(1, 60)]

        if len(r):
            c1, c2 = st.columns(2)
            c1.metric("Consommation moyenne",
                      f"{r.conso_100.mean():.1f} L/100km")
            c2.metric("Écart moyen au nominal",
                      f"{r.surconso_pct.mean():+.0f} %")
            n = min(10, r.vehicule_id.nunique())
            top = (r.groupby("vehicule_id").surconso_pct.mean()
                   .nlargest(n).reset_index())
            carte(_barres_h(top.round(1), "surconso_pct", "vehicule_id",
                            f"Top {n} des surconsommations moyennes (%)",
                            suffixe=" %"),
                  "Écart à la consommation nominale du véhicule : "
                  "substitut observable de l'usure mécanique.")
            st.info("💡 Une surconsommation durable peut signaler une usure "
                    "mécanique, un style de conduite, ou une anomalie à "
                    "contrôler (fuite, écart de saisie).")
        else:
            st.warning("Aucun plein rattaché à une mission avec une distance "
                       "renseignée : la consommation ne peut pas être "
                       "calculée. Rattachez vos pleins à une mission lors "
                       "de la saisie.")

        # Dépense mensuelle — calculable sur tous les pleins
        if f.date.notna().any():
            fm = (f.dropna(subset=["date"])
                  .assign(mois=lambda x: x.date.dt.to_period("M")
                          .dt.to_timestamp())
                  .groupby("mois").montant_fcfa.sum().reset_index())
            fm["millions"] = fm.montant_fcfa / 1e6
            fig = px.bar(fm, x="mois", y="millions",
                         color_discrete_sequence=[PALETTE[1]])
            fig.update_traces(marker_line_width=0)
            fig.update_layout(title=dict(text="Dépense carburant mensuelle "
                                              "(millions FCFA)",
                                         font=dict(size=14)))
            fig.update_xaxes(title_text="")
            fig.update_yaxes(title_text="M FCFA")
            carte(_style(fig, sans_legende=True),
                  "Dépense de carburant agrégée par mois.")


# ══════════════════════════════════════════════════════════════════════
# 🛠️ MAINTENANCE (saisie + historique)
# ══════════════════════════════════════════════════════════════════════
def page_maintenance_crud(d):
    titre_page("Maintenance — interventions", "🛠️")
    veh, mnt = d["vehicules"], d["maintenance"]
    if veh is None:
        st.warning("Enregistrez d'abord des véhicules.")
        return
    t1, t2 = st.tabs(["➕ Nouvelle intervention", "📋 Historique"])

    with t1:
      if auth.bloquer("gerer_maintenance",
                      "🔒 Consultation seule : la saisie des interventions "
                      "est réservée aux gestionnaires."):
        pass
      else:
          with st.form("form_mnt", clear_on_submit=True):
              c1, c2, c3 = st.columns(3)
              vid = c1.selectbox("Véhicule *", veh.vehicule_id)
              typ = c2.selectbox("Type *", ["Entretien préventif", "Panne"])
              dte = c3.date_input("Date *", date.today())
              c4, c5, c6 = st.columns(3)
              cats = (referentiels.liste("categorie_maintenance")
                      or ["Vidange/Révision"] + list(TYPES_PANNES.keys()))
              cat = c4.selectbox("Catégorie *", cats,
                                 help="Liste modifiable dans 📚 Référentiels.")
              cout = c5.number_input("Coût (FCFA) *", 0, 10_000_000, 85_000, step=5_000)
              immo = c6.number_input("Jours d'immobilisation", 0, 90, 1)
              kms = ui.table_kilometrage(veh, d.get("missions")) \
                  .set_index("vehicule_id").km_actuel
              km_estime = int(kms.get(str(vid), 0))
              km = st.number_input(
                  "Kilométrage compteur", 0, 1_500_000, km_estime, step=500,
                  help="Proposé d'après le compteur à l'enregistrement du "
                       "véhicule augmenté des kilomètres des missions "
                       "effectuées. Corrigez avec le relevé réel.")
              if km_estime:
                  st.caption(f"🚙 Kilométrage estimé de **{vid}** : "
                             f"{km_estime:,} km".replace(",", " "))
              if st.form_submit_button("Enregistrer l'intervention", type="primary"):
                  mid = prochain_id(mnt, "maintenance_id", "MT-", 5)
                  ligne = {"maintenance_id": mid, "vehicule_id": vid, "date": str(dte),
                           "type_intervention": typ, "categorie": cat,
                           "cout_fcfa": int(cout), "jours_immobilisation": int(immo),
                           "km_compteur": int(km)}
                  nouveau = pd.concat([mnt if mnt is not None else pd.DataFrame(),
                                       pd.DataFrame([ligne])], ignore_index=True)
                  ecrire("maintenance.csv", nouveau)
                  st.success(f"✅ Intervention **{mid}** enregistrée.")
                  st.rerun()

    with t2:
        if mnt is None or mnt.empty:
            st.info("Aucune intervention.")
            return
        c1, c2 = st.columns(2)
        vfil = c1.selectbox("Véhicule ", ["(tous)"] + sorted(mnt.vehicule_id.unique()))
        tfil = c2.multiselect("Type", sorted(mnt.type_intervention.unique()))
        m = mnt.copy()
        if vfil != "(tous)":
            m = m[m.vehicule_id == vfil]
        if tfil:
            m = m[m.type_intervention.isin(tfil)]
        # Kilométrage courant de chaque véhicule, à côté de l'historique
        kms = ui.table_kilometrage(veh, d.get("missions"))
        m_aff = m.merge(kms, on="vehicule_id", how="left")
        cols = ["maintenance_id", "vehicule_id", "km_actuel", "date",
                "type_intervention", "categorie", "cout_fcfa",
                "jours_immobilisation", "km_compteur"]
        st.dataframe(m_aff.sort_values("date", ascending=False)[
            [c for c in cols if c in m_aff.columns]],
            use_container_width=True, hide_index=True)
        st.caption("« km_actuel » est le kilométrage estimé du véhicule "
                   "aujourd'hui ; « km_compteur » celui relevé lors de "
                   "l'intervention.")

        c1, c2, c3 = st.columns(3)
        c1.metric("Coût total affiché",
                  f"{m.cout_fcfa.sum():,.0f} FCFA".replace(",", " "))
        c2.metric("Interventions", len(m))
        if len(m):
            c3.metric("Coût moyen",
                      f"{m.cout_fcfa.mean():,.0f} FCFA".replace(",", " "))

        # ── Top 10 des véhicules les plus coûteux ─────────────────────
        st.divider()
        st.subheader("💰 Véhicules les plus coûteux en maintenance")
        if m.empty:
            st.info("Aucune intervention à analyser.")
        else:
            n = min(10, m.vehicule_id.nunique())
            totaux = m.groupby("vehicule_id").cout_fcfa.sum().nlargest(n)
            det = (m[m.vehicule_id.isin(totaux.index)]
                   .groupby(["vehicule_id", "type_intervention"])
                   .agg(cout=("cout_fcfa", "sum"),
                        nb=("cout_fcfa", "count")).reset_index())
            # Libellé enrichi du modèle, quand le référentiel le fournit
            if veh is not None and "vehicule_id" in veh.columns:
                ref = veh.set_index("vehicule_id")
                det["libelle"] = det.vehicule_id.map(
                    lambda x: f"{x} · {ref.loc[x, 'modele']}"
                    if x in ref.index and pd.notna(ref.loc[x].get("modele"))
                    and str(ref.loc[x].get("modele")).strip() else str(x))
            else:
                det["libelle"] = det.vehicule_id
            ordre = (det.groupby("libelle").cout.sum()
                     .sort_values().index.tolist())

            fig = px.bar(det, x="cout", y="libelle", orientation="h",
                         color="type_intervention",
                         color_discrete_map={"Panne": PALETTE[0],
                                             "Entretien préventif": PALETTE[4]},
                         category_orders={"libelle": ordre},
                         custom_data=["type_intervention", "nb"])
            fig.update_traces(
                marker_line_width=0, width=0.72,
                hovertemplate="%{y}<br>%{customdata[0]} : "
                              "%{x:,.0f} FCFA (%{customdata[1]} interv.)"
                              "<extra></extra>")
            fig.update_layout(barmode="stack",
                              title=dict(text=f"Top {n} par coût cumulé "
                                              f"(FCFA)", font=dict(size=14)))
            fig.update_xaxes(title_text="")
            fig.update_yaxes(title_text="")
            carte(_style(fig, hauteur=max(300, 42 * n), marge_gauche=4),
                  "Coût cumulé par véhicule, décomposé entre pannes et "
                  "entretien préventif.")

            # Tableau de synthèse : le coût seul ne dit pas tout
            syn = m[m.vehicule_id.isin(totaux.index)].groupby("vehicule_id").agg(
                cout_total=("cout_fcfa", "sum"),
                interventions=("cout_fcfa", "count"),
                pannes=("type_intervention",
                        lambda x: int((x == "Panne").sum())),
                jours_immobilise=("jours_immobilisation", "sum")
                if "jours_immobilisation" in m.columns
                else ("cout_fcfa", "size")).reset_index()
            syn = syn.sort_values("cout_total", ascending=False)
            syn.columns = ["Véhicule", "Coût total (FCFA)", "Interventions",
                           "dont pannes", "Jours immobilisé"]
            st.dataframe(
                syn.style.background_gradient(subset=["Coût total (FCFA)"],
                                              cmap="Reds"),
                use_container_width=True, hide_index=True)
            part = totaux.sum() / m.cout_fcfa.sum() * 100
            st.caption(f"Ces {n} véhicule(s) représentent **{part:.0f} %** du "
                       f"coût de maintenance affiché. Un coût élevé peut venir "
                       f"d'une panne lourde isolée ou d'une accumulation : la "
                       f"colonne « dont pannes » permet de distinguer les deux.")


# ══════════════════════════════════════════════════════════════════════
# 🔮 PRÉDICTIONS
# ══════════════════════════════════════════════════════════════════════
def page_predictions(d):
    titre_page("Prédictions — risque de panne à 30 jours", "🔮")
    feat_p = DATA_PROCESSED / "features_maintenance.parquet"
    model_p = MODELS_DIR / "modele_panne_30j.joblib"
    calib_p = MODELS_DIR / "calibrateur_panne.joblib"
    if not (feat_p.exists() and model_p.exists() and calib_p.exists()):
        st.warning("Modèle non entraîné sur les données actuelles. Exécutez :\n"
                   "```\npython src/models/features_maintenance.py\n"
                   "python src/models/train_panne.py\n```")
        return
    import joblib
    from models.features_def import FEATURES_NUM, FEATURES_CAT
    pipe = joblib.load(model_p)
    calib = joblib.load(calib_p)
    df = pd.read_parquet(feat_p)
    snap = df[df.date_snapshot == df.date_snapshot.max()].copy()
    s = pipe.predict_proba(snap[FEATURES_NUM + FEATURES_CAT])[:, 1]
    snap["risque"] = calib.predict_proba(s.reshape(-1, 1))[:, 1]

    # Le fichier de variables est produit par le script d'entraînement à
    # partir des données brutes : ses libellés n'ont pas été normalisés et
    # « ZONE SUD » y coexiste avec « Zone Sud ». On reprend donc la
    # localité du référentiel véhicules, qui fait foi et reste à jour, et
    # l'on normalise ce qui n'aurait pas de correspondance.
    veh_ref = d.get("vehicules")
    if veh_ref is not None and "localite" in veh_ref.columns:
        ref = veh_ref.drop_duplicates("vehicule_id")
        corresp = ref.set_index(ref.vehicule_id.astype(str)).localite
        snap["localite"] = (snap.vehicule_id.astype(str).map(corresp)
                            .fillna(snap.localite))
    snap = normaliser_libelles(snap)

    st.caption(f"Analyse au {df.date_snapshot.max().date()} — "
               f"{len(snap)} véhicules actifs · modèle : régression logistique "
               f"calibrée (ROC-AUC 0.66, Prec@15 17 %)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Risque moyen flotte", f"{snap.risque.mean()*100:.1f} %")
    c2.metric("Véhicules à risque élevé (top 10 %)",
              int((snap.risque >= snap.risque.quantile(0.9)).sum()))
    c3.metric("Risque max", f"{snap.risque.max()*100:.1f} %")

    n = st.slider("Véhicules à afficher", 5, 30, 15)
    top = snap.nlargest(n, "risque")[
        ["vehicule_id", "localite", "type_vehicule", "age_annees",
         "km_total", "surconso_90j", "risque"]].copy()
    top["risque"] = (top.risque * 100).round(1)
    top["km_total"] = top.km_total.astype(int)
    top["surconso_90j"] = top.surconso_90j.round(2)
    top.columns = ["Véhicule", "Localité", "Type", "Âge", "Km total",
                   "Surconso 90j", "Risque 30j (%)"]
    st.dataframe(top.style.background_gradient(subset=["Risque 30j (%)"], cmap="Reds"),
                 use_container_width=True, hide_index=True)
    st.download_button("📥 Télécharger les alertes (CSV)",
                       top.to_csv(index=False).encode("utf-8-sig"),
                       "alertes_maintenance.csv", "text/csv")
    carte(_style(px.box(snap, x="localite", y="risque", color="localite",
                        color_discrete_sequence=PALETTE,
                        labels={"risque": "Risque de panne 30 j",
                                "localite": ""})
                .update_layout(title=dict(text="Distribution du risque par "
                                               "zone", font=dict(size=14))),
                sans_legende=True),
          "Les zones à forte part de piste concentrent des risques plus "
          "élevés.")
    st.info("🚧 Modules à venir : détection d'anomalies carburant (itération 3), "
            "durée de vie restante / analyse de survie (itération 2.4), "
            "prévision de la demande et optimisation des affectations (itération 4).")


# ══════════════════════════════════════════════════════════════════════
# 📤 EXTRACTION
# ══════════════════════════════════════════════════════════════════════
def page_extraction(d):
    titre_page("Extraction de données", "📤")
    tables = {"Véhicules": "vehicules", "Chauffeurs": "chauffeurs",
              "Missions": "missions", "Carburant": "carburant",
              "Maintenance": "maintenance"}
    choix = st.selectbox("Table à extraire", list(tables.keys()))
    df = d[tables[choix]]
    if df is None or df.empty:
        st.info("Table vide.")
        return
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")])

    col_date = next((c for c in ["date_depart", "date"] if c in df.columns), None)
    if col_date is not None:
        dmin, dmax = df[col_date].min().date(), df[col_date].max().date()
        c1, c2 = st.columns(2)
        d1 = c1.date_input("Du", dmin, min_value=dmin, max_value=dmax)
        d2 = c2.date_input("Au", dmax, min_value=dmin, max_value=dmax)
        df = df[(df[col_date] >= pd.Timestamp(d1)) & (df[col_date] <= pd.Timestamp(d2))]
    if "localite" in df.columns:
        locs = st.multiselect("Localités", sorted(df.localite.unique()))
        if locs:
            df = df[df.localite.isin(locs)]
    if "vehicule_id" in df.columns and choix != "Véhicules":
        vids = st.multiselect("Véhicules", sorted(df.vehicule_id.unique()))
        if vids:
            df = df[df.vehicule_id.isin(vids)]

    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"{len(df):,} lignes sélectionnées")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ CSV (Excel-compatible)",
                       df.to_csv(index=False).encode("utf-8-sig"),
                       f"{tables[choix]}_export.csv", "text/csv",
                       use_container_width=True)
    try:
        import io
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        c2.download_button("⬇️ Excel (.xlsx)", buf.getvalue(),
                           f"{tables[choix]}_export.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)
    except ImportError:
        c2.caption("Pour l'export .xlsx : `pip install openpyxl`")


# ══════════════════════════════════════════════════════════════════════
# 📥 IMPORT DE DONNÉES RÉELLES
# ══════════════════════════════════════════════════════════════════════
SCHEMAS = {
    "vehicules.csv": ["immatriculation", "marque", "modele",
                      "type_vehicule", "centre_service",
                      "date_premiere_circulation",
                      "conso_nominale_l_100km", "km_initial"],
    "staffs.csv": ["staff_id", "nom_complet", "departement",
                   "centre_service", "roles"],
    "missions.csv": ["numero_mission", "vehicule_id", "chauffeur_id",
                     "date_depart", "distance_km"],
    "carburant.csv": ["plein_id", "numero_mission", "vehicule_id", "date",
                      "litres",
                      "montant_fcfa"],
    "maintenance.csv": ["maintenance_id", "vehicule_id", "date",
                        "type_intervention", "cout_fcfa"],
}

# Modèles d'import : une ligne d'exemple + règles de saisie par table.
# « (calculé) » = colonne remplie automatiquement, peut rester vide.
TEMPLATES = {
    "vehicules.csv": (
        [{"immatriculation": "WV-IT-01", "marque": "Toyota",
          "modele": "Hilux", "type_vehicule": "Voiture",
          "n_chassis": "AHTFR22G506123456", "centre_service": "Dakar",
          "localite": "(calculé)", "puissance_cv": 11,
          "imputation": "PRG-WASH",
          "date_premiere_circulation": "2019-05-14",
          "annee_mise_en_service": "(calculé)",
          "date_acquisition": "2019-08-01",
          "valeur_acquisition_fcfa": 28000000, "combustible": "Gasoil",
          "conso_nominale_l_100km": 11.5, "km_initial": 85000,
          "date_visite_technique": "2026-03-10",
          "etat_visite_technique": "Bon",
          "prochaine_visite_technique": "(calculé : +1 an)",
          "date_souscription_assurance": "2025-11-02",
          "etat_assurance": "Bon",
          "renouvellement_assurance": "(calculé : +1 an)",
          "date_admission_temporaire": "2025-09-15", "etat_at": "Bon",
          "renouvellement_at": "(calculé : +1 an)",
          "etat_carte_grise": "Bon", "etat_vehicule": "Fonctionnel",
          "remarques": ""}],
        ["**L'immatriculation identifie le véhicule** : obligatoire et unique.",
         "`type_vehicule` : Voiture ou Moto · `combustible` : Gasoil ou Super",
         "États : Bon / Pas bon · `etat_vehicule` : Fonctionnel / Non fonctionnel",
         "`centre_service` : Dakar, Kaffrine, Fatick, Tamba, Kolda, "
         "Kedougou, Tanaf, Oussouye",
         "Les colonnes *(calculé)* peuvent rester vides."]),

    "staffs.csv": (
        [{"staff_id": "10027846", "nom_complet": "Marc Clément Désiré Sambou",
          "email": "Marc_Sambou@wvi.org", "departement": "ICT",
          "fonction": "ICT Coordinator", "telephone": "+221 77 649 78 79",
          "centre_service": "Dakar", "localite": "(calculé)",
          "roles": "User, Approbateur", "date_permis": "", "actif": "Oui"}],
        ["`staff_id` : le **numéro d'employé** (Employee number) de votre "
         "export RH. Il identifie le staff et **n'est jamais généré** : il "
         "doit être renseigné et unique.",
         "`roles` : un ou plusieurs parmi **User, Chauffeur, Approbateur, "
         "Gestionnaire, Admin**, séparés par des virgules. **User** est le "
         "rôle par défaut (peut partir en mission, aucun droit de gestion) ; "
         "une cellule vide reçoit automatiquement « User ».",
         "⚠️ Pensez à attribuer **Chauffeur** aux conducteurs : ce rôle ne "
         "figure pas dans l'export RH mais conditionne l'affectation à une "
         "mission.",
         "`departement` : ICT, Finance, Administration, Operations, "
         "Communication, People & Culture, Supply chain, Sponsorship F&D, "
         "DN, HEA, Programs, Audit.",
         "`centre_service` : **à ajouter** — cette colonne n'existe pas dans "
         "l'export RH, c'est elle qui rattache le staff à un site.",
         "`actif` : Oui / Non — préférez « Non » à la suppression pour "
         "conserver l'historique des missions."]),

    "missions.csv": (
        [{"numero_mission": "(laisser vide : généré)",
          "statut": "Approved",
          "objet": "Visite IT", "departement": "ICT",
          "imputation": "DEPARTMENT / ICT",
          "agent_principal": "Yvon Bama", "agent_id": "10027847",
          "personnes_a_bord": "Yvon Bama, Marc Sambou",
          "personnes_ids": "10027847,10027846",
          "approbateur": "Japhet Samba", "approbateur_id": "10027848",
          "vehicule_id": "DK-1234-AB", "chauffeur_id": "10027850",
          "origine": "Dakar", "destination": "Kaffrine",
          "date_depart": "2026-04-14 07:00", "date_fin": "2026-04-16 18:00",
          "duree_jours": 3, "distance_km": 380, "part_piste": 0.2,
          "taux_charge": 0.5, "observations": ""}],
        ["`vehicule_id` : **l'immatriculation** du véhicule (DK-1234-AB) — "
         "elle doit exister dans vehicules.csv.",
         "`chauffeur_id`, `agent_id`, `approbateur_id` : le **numéro "
         "d'employé** (matricule) du staff concerné. Le chauffeur doit avoir "
         "le rôle Chauffeur, l'approbateur le rôle Approbateur.",
         "`personnes_ids` : matricules des personnes à bord, séparés par des "
         "virgules — une feuille de route est générée pour chacune.",
         "`statut` : Draft, Pending, Approved, Rejected ou Canceled.",
         "`numero_mission` : **l'identifiant de la mission**, au format "
         "`WVS-{code département}-{date}-{0001}`. C'est le numéro qui "
         "figure sur l'ordre de mission. Laissez la cellule vide pour "
         "qu'il soit généré automatiquement.",
         "Dates : `AAAA-MM-JJ` ou `AAAA-MM-JJ HH:MM`.",
         "`part_piste` et `taux_charge` : valeurs entre 0 et 1 (0.2 = 20 %), "
         "utilisées par les modèles de prédiction. Laissez vide si inconnues."]),

    "carburant.csv": (
        [{"plein_id": "(laisser vide : généré)",
          "numero_mission": "WVS-ICT-2026-04-14-0031",
          "vehicule_id": "WV-IT-01",
          "chauffeur_id": "10027850", "date": "2026-04-14",
          "litres": 45.5, "montant_fcfa": 45045}],
        ["`vehicule_id` : **l'immatriculation** du véhicule · "
         "`chauffeur_id` : le **matricule** du chauffeur.",
         "`numero_mission` : facultatif mais **fortement recommandé** — "
         "c'est le rattachement à une mission qui permet de calculer la "
         "consommation aux 100 km et de détecter les surconsommations.",
         "`litres` : décimales avec un point ou une virgule (45.5 ou 45,5).",
         "Une ligne par plein."]),

    "maintenance.csv": (
        [{"maintenance_id": "(laisser vide : généré)",
          "vehicule_id": "WV-IT-01", "date": "2026-02-20",
          "type_intervention": "Panne", "categorie": "Freinage",
          "cout_fcfa": 180000, "jours_immobilisation": 2,
          "km_compteur": 142500}],
        ["`vehicule_id` : **l'immatriculation** du véhicule.",
         "`type_intervention` : **Panne** ou **Entretien préventif** — "
         "l'orthographe compte : le modèle de prédiction n'apprend que "
         "sur les lignes marquées « Panne ».",
         "`categorie` : Freinage, Suspension, Moteur, "
         "Embrayage/Transmission, Électrique/Batterie, Pneumatique, "
         "Refroidissement, Climatisation, Vidange/Révision…",
         "`km_compteur` : kilométrage au moment de l'intervention — "
         "utile au calcul des km depuis le dernier entretien.",
         "**C'est la table la plus importante pour la prédiction** : "
         "plus l'historique des pannes est complet, plus le modèle est "
         "fiable (30 pannes minimum, 100+ recommandé)."]),
}


def _fichier_template(nom):
    """Construit le DataFrame modèle d'une table."""
    lignes, _ = TEMPLATES[nom]
    return pd.DataFrame(lignes)


def page_import():
    titre_page("Import des données réelles", "📥")
    if auth.bloquer("importer", "🔒 Seul un administrateur peut importer "
                                "des données."):
        return
    t_imp, t_tpl = st.tabs(["📤 Importer un fichier", "📄 Modèles à remplir"])

    with t_imp:
        st.markdown("Remplacez la simulation par vos fichiers réels. Les "
                    "colonnes supplémentaires sont conservées. Récupérez "
                    "d'abord le modèle dans l'onglet **📄 Modèles à "
                    "remplir**.")
        for nom, cols in SCHEMAS.items():
            with st.expander(f"**{nom}** — requis : `{'`, `'.join(cols)}`"):
                p = DATA_RAW / nom
                if p.exists():
                    try:
                        st.caption(f"Table actuelle : "
                                   f"{crud_compter(nom):,} lignes")
                    except Exception:
                        st.caption("Fichier actuel présent.")
                up = st.file_uploader(f"Remplacer {nom}", type="csv", key=f"up_{nom}")
                if up is not None:
                    try:
                        df, encodage, sep = lire_csv_robuste(up)
                    except Exception as err:
                        st.error(f"Impossible de lire le fichier : {err}")
                        st.stop()
                    st.caption(f"Lu avec l'encodage **{encodage}**, séparateur "
                               f"« {sep} » — {len(df)} lignes, "
                               f"{len(df.columns)} colonnes.")
                    # Noms de colonnes : espaces superflus et BOM éventuel
                    df.columns = [str(c).strip().lstrip("\ufeff") for c in df.columns]
                    manq = [c for c in cols if c not in df.columns]
                    if manq:
                        st.error(f"Colonnes manquantes : {manq}")
                        st.caption(f"Colonnes trouvées dans votre fichier : "
                                   f"{list(df.columns)}")
                        with st.expander("Aperçu des 5 premières lignes lues"):
                            st.dataframe(df.head(), use_container_width=True)
                    else:
                        if nom == "vehicules.csv":
                            from vehicules_page import (calculer_champs,
                                                        normaliser_immat)
                            df["immatriculation"] = normaliser_immat(
                                df.immatriculation)
                            vides = df.immatriculation.isin(
                                ["", "NAN", "NONE"]) | df.immatriculation.isna()
                            dbl = df.immatriculation.duplicated(keep=False)
                            if vides.any():
                                st.error(f"❌ {int(vides.sum())} ligne(s) sans "
                                         f"immatriculation. L'immatriculation "
                                         f"identifie le véhicule : elle est "
                                         f"obligatoire.")
                                st.dataframe(df[vides].head(10),
                                             use_container_width=True)
                                st.stop()
                            if dbl.any():
                                st.error("❌ Immatriculations en double — elles "
                                         "doivent être uniques :")
                                st.dataframe(
                                    df.loc[dbl].sort_values("immatriculation")
                                    .head(20), use_container_width=True)
                                st.stop()
                            df = calculer_champs(df)   # vehicule_id = immat
                            cols = ["immatriculation", "vehicule_id"] + [
                                c for c in df.columns
                                if c not in ("immatriculation", "vehicule_id")]
                            df = df[cols]
                        elif nom == "staffs.csv":
                            from config import ROLE_DEFAUT
                            from vehicules_page import _normaliser_centre
                            df["staff_id"] = df.staff_id.astype(str).str.strip()
                            vides = df.staff_id.isin(["", "nan", "None"])
                            dbl = df.staff_id.duplicated(keep=False)
                            if vides.any():
                                st.error(f"❌ {int(vides.sum())} ligne(s) sans "
                                         f"n° d'employé. Le matricule "
                                         f"identifie le staff : il est "
                                         f"obligatoire.")
                                st.dataframe(df[vides].head(10),
                                             use_container_width=True)
                                st.stop()
                            if dbl.any():
                                st.error("❌ Matricules en double :")
                                st.dataframe(
                                    df.loc[dbl].sort_values("staff_id").head(20),
                                    use_container_width=True)
                                st.stop()
                            # Rôle par défaut si colonne absente ou vide
                            if "roles" not in df.columns:
                                df["roles"] = ROLE_DEFAUT
                            df["roles"] = (df.roles.fillna(ROLE_DEFAUT)
                                           .astype(str).str.strip()
                                           .replace({"": ROLE_DEFAUT,
                                                     "nan": ROLE_DEFAUT,
                                                     "NaN": ROLE_DEFAUT,
                                                     "None": ROLE_DEFAUT}))
                            n_def = int((df.roles == ROLE_DEFAUT).sum())
                            # Localité déduite du centre de service
                            paires = df.centre_service.map(_normaliser_centre)
                            df["centre_service"] = paires.map(lambda x: x[0])
                            loc = paires.map(lambda x: x[1])
                            if "localite" in df.columns:
                                loc = loc.fillna(df.localite)
                            df["localite"] = loc.fillna("Bureau National")
                            if "actif" not in df.columns:
                                df["actif"] = "Oui"
                            st.info(f"{len(df)} staff(s) — dont {n_def} avec "
                                    f"le rôle « {ROLE_DEFAUT} » seul.")
                        ecrire(nom, df)
                        st.success(f"✅ {nom} remplacé ({len(df):,} lignes).")
                        st.cache_data.clear()
                        st.caption("Vérifiez que les accents s'affichent "
                                   "correctement (ex. « Kédougou ») :")
                        st.dataframe(df.head(3), use_container_width=True)
        st.divider()
        st.markdown("**Après import**, reconstruisez le modèle :\n"
                    "```\npython src/models/features_maintenance.py\n"
                    "python src/models/train_panne.py\n```")

    with t_tpl:
        st.markdown("Téléchargez le modèle de la table à remplir, "
                    "complétez-le (une ligne = un enregistrement), puis "
                    "importez-le dans l'onglet **📤 Importer**.")
        with st.expander("🔄 Correspondance avec l'export RH World Vision "
                         "(colonnes à renommer)"):
            st.markdown(
                "Votre export RH contient de nombreuses colonnes aux "
                "intitulés différents. Renommez les en-têtes ainsi avant "
                "l'import — les colonnes non listées peuvent rester, elles "
                "seront conservées.")
            st.dataframe(pd.DataFrame([
                {"Colonne de l'export RH": "Employee number - Numéro de l'employé",
                 "À renommer en": "staff_id"},
                {"Colonne de l'export RH": "(colonne contenant le nom complet)",
                 "À renommer en": "nom_complet"},
                {"Colonne de l'export RH": "Organization unit/Department",
                 "À renommer en": "departement"},
                {"Colonne de l'export RH": "Job (list) - Poste",
                 "À renommer en": "fonction"},
                {"Colonne de l'export RH": "Telephone (work) - Téléphone",
                 "À renommer en": "telephone"},
                {"Colonne de l'export RH": "Email (work) - Adresse e-mail",
                 "À renommer en": "email"},
                {"Colonne de l'export RH": "Role",
                 "À renommer en": "roles"},
                {"Colonne de l'export RH": "⚠️ (à créer, absente de l'export)",
                 "À renommer en": "centre_service"},
            ]), use_container_width=True, hide_index=True)
            st.caption("⚠️ Attention : dans certains exports, la colonne "
                       "intitulée « Email - Adresse e-mail » contient en "
                       "réalité les **noms** des agents. Vérifiez le contenu "
                       "avant de renommer.")

        st.info("💡 Ordre d'import conseillé : **véhicules** → **staffs** → "
                "**missions** → **carburant** et **maintenance**. "
                "Les missions référencent les véhicules et les staffs, qui "
                "doivent donc exister au préalable.")
        for nom, (_, regles) in TEMPLATES.items():
            with st.expander(f"**{nom}**"):
                tpl = _fichier_template(nom)
                for r in regles:
                    st.markdown(f"- {r}")
                st.caption("Colonnes requises : "
                           + ", ".join(f"`{c}`" for c in SCHEMAS[nom]))
                st.dataframe(tpl, use_container_width=True, hide_index=True)
                c1, c2 = st.columns(2)
                c1.download_button(
                    "⬇️ Modèle CSV",
                    tpl.to_csv(index=False).encode("utf-8-sig"),
                    f"template_{nom}", "text/csv",
                    key=f"tplcsv_{nom}", use_container_width=True)
                buf = io.BytesIO()
                tpl.to_excel(buf, index=False, engine="openpyxl")
                c2.download_button(
                    "⬇️ Modèle Excel", buf.getvalue(),
                    f"template_{nom.replace('.csv', '.xlsx')}",
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet",
                    key=f"tplxls_{nom}", use_container_width=True)


# ══════════════════════════════════════════════════════════════════════
def main():
    appliquer_theme()
    logo_entete()
    st.sidebar.markdown(
        "<div style='padding:4px 0 10px;border-bottom:1px solid "
        "rgba(255,255,255,.18);margin-bottom:10px'>"
        "<div style='font-size:27px;font-weight:700;color:#fff;"
        "letter-spacing:-.01em'>Fleet-IA</div>"
        "<div style='font-size:.82em;color:#F3D5BF;line-height:1.45'>"
        "Gestion prédictive de flotte<br>World Vision Sénégal · "
        f"<b>{APP_VERSION}</b></div></div>", unsafe_allow_html=True)

    # ── Connexion obligatoire ─────────────────────────────────────────
    if not auth.ecran_connexion(WV_ROUGE):
        return

    pages = {
        "📊 Vue d'ensemble": lambda d: page_vue_ensemble(d),
        "🚙 Véhicules": lambda d: page_vehicules(d),
        "👥 Staffs & rôles": lambda d: page_staffs(d),
        "🗺️ Missions": lambda d: page_missions(d),
        "✍️ Missions à approuver": lambda d: page_approbations(d),
        "⛽ Carburant": lambda d: page_carburant(d),
        "🛠️ Maintenance": lambda d: page_maintenance_crud(d),
        "🔮 Prédictions": lambda d: page_predictions(d),
        "📤 Extraction": lambda d: page_extraction(d),
        "📥 Import données réelles": lambda d: page_import(),
        "📚 Référentiels": lambda d: referentiels.page_referentiels(d),
        "🔐 Comptes utilisateurs": lambda d: auth.page_comptes(d),
    }
    pages = auth.pages_autorisees(pages)      # le menu suit les droits
    choix = st.sidebar.radio("Navigation", list(pages.keys()))

    initialiser_staffs()  # migration chauffeurs -> staffs si nécessaire
    d = charger()

    # 🔔 Notification de conformité visible partout
    if d["vehicules"] is not None and not d["vehicules"].empty:
        tc = table_conformite(d["vehicules"])
        if len(tc):
            n_exp = int((tc["Statut"] == "🔴 EXPIRÉ").sum())
            n_bientot = int((tc["Statut"] == "🟠 Expire sous 30 j").sum())
            if n_exp:
                st.sidebar.error(f"🔴 {n_exp} document(s) EXPIRÉ(S)")
            if n_bientot:
                st.sidebar.warning(f"🟠 {n_bientot} à renouveler sous 30 j")
            if not n_exp and not n_bientot:
                st.sidebar.success("🟢 Conformité : flotte en règle")

    pages[choix](d)
    auth.carte_utilisateur()   # qui est connecté, en bas de la barre

main()
