"""
Éléments d'interface et calculs partagés par toutes les pages.

Ce module évite les imports croisés entre pages : chacune importe `ui`,
aucune n'importe une autre page.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

# ── Identité visuelle World Vision ───────────────────────────────────
WV_ROUGE = "#E2231A"
WV_ORANGE = "#F58220"
WV_TITRE = "#C2570A"
NAV_FONCE = "#7E3410"


def titre_page(texte, emoji=""):
    """Titre de page en capitales, orange World Vision, souligné.

    Rendu en HTML plutôt que par feuille de style : le résultat ne dépend
    d'aucun sélecteur interne de Streamlit, qui changent selon la version.
    """
    st.markdown(
        f"<div style='margin:0 0 18px'>"
        f"<h1 style='font-size:2.05rem;font-weight:700;margin:0;"
        f"text-transform:uppercase;color:{WV_TITRE};letter-spacing:.02em;"
        f"line-height:1.15'>{emoji} {texte}</h1>"
        f"<div style='height:4px;width:100%;margin-top:8px;border-radius:2px;"
        f"background:linear-gradient(90deg,{WV_ORANGE} 0%,"
        f"{WV_ORANGE}55 45%,transparent 100%)'></div></div>",
        unsafe_allow_html=True)


def carte(fig, legende=None):
    """Graphique encadré. `st.container(border=True)` est natif : le cadre
    s'affiche sans dépendre d'une feuille de style."""
    try:
        boite = st.container(border=True)
    except TypeError:            # Streamlit antérieur à 1.29
        boite = st.container()
    with boite:
        st.plotly_chart(fig, use_container_width=True)
        if legende:
            st.caption(legende)


# ══════════════════════════════════════════════════════════════════════
# Distances routières entre centres de service
# ══════════════════════════════════════════════════════════════════════
# Distances routières approximatives en kilomètres (aller simple).
# Ce sont des ORDRES DE GRANDEUR destinés à pré-remplir le formulaire :
# la valeur reste modifiable à la saisie, et devrait être corrigée avec
# les distances réellement pratiquées par l'organisation.
DISTANCES_KM = {
    # Distances routières réelles (km, aller simple), fournies par
    # World Vision Sénégal. Les liaisons vers la Casamance passent soit
    # par la Transgambienne, soit par Tambacounda pour contourner la
    # Gambie — d'où des écarts importants entre trajets voisins.
    ("Dakar", "Fatick"): 146,        # via A1/N1
    ("Dakar", "Kaffrine"): 283,      # via A1/N1
    ("Dakar", "Tamba"): 464,         # via N1
    ("Dakar", "Kedougou"): 739,      # via Tambacounda (N1/N7)
    ("Dakar", "Kolda"): 568,         # via la Transgambienne
    ("Dakar", "Tanaf"): 593,         # via la Transgambienne
    ("Dakar", "Oussouye"): 484,      # via la Transgambienne

    ("Fatick", "Kaffrine"): 137,     # via N1 (Kaolack)
    ("Fatick", "Tamba"): 319,        # via N1
    ("Fatick", "Kedougou"): 552,     # via Tambacounda
    ("Fatick", "Kolda"): 294,        # via la Transgambienne
    ("Fatick", "Tanaf"): 358,        # via la Transgambienne
    ("Fatick", "Oussouye"): 339,     # via la Transgambienne

    ("Kaffrine", "Tamba"): 215,      # via N1 direct
    ("Kaffrine", "Kedougou"): 448,   # via N1 puis N7 (Tamba)
    ("Kaffrine", "Kolda"): 245,      # via la Gambie (Farafenni)
    ("Kaffrine", "Tanaf"): 309,      # via la Gambie
    ("Kaffrine", "Oussouye"): 290,   # via la Gambie

    ("Tamba", "Kedougou"): 234,      # via N7 direct
    ("Tamba", "Kolda"): 224,         # via N6, Sénégal uniquement
    ("Tamba", "Tanaf"): 289,         # via N6, Sénégal uniquement
    ("Tamba", "Oussouye"): 447,      # via N6 et Ziguinchor

    ("Kedougou", "Kolda"): 448,      # via Tamba puis N6
    ("Kedougou", "Tanaf"): 513,      # via Tamba puis N6
    ("Kedougou", "Oussouye"): 672,   # via Tamba, N6 puis Ziguinchor

    ("Kolda", "Tanaf"): 69,          # liaison directe Casamance (N6)
    ("Kolda", "Oussouye"): 227,      # via N6 / Ziguinchor

    ("Tanaf", "Oussouye"): 160,      # via Ziguinchor / R20
}


def _cle_centre(t):
    """Comparaison insensible aux accents et à la casse : « Kédougou »
    et « Kedougou » désignent le même centre."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(t).strip())
                   if unicodedata.category(c) != "Mn").lower()


_DISTANCES_NORM = {}
for (_a, _b), _km in DISTANCES_KM.items():
    _DISTANCES_NORM[(_cle_centre(_a), _cle_centre(_b))] = _km
    _DISTANCES_NORM[(_cle_centre(_b), _cle_centre(_a))] = _km

def distance_aller(origine, destination) -> int:
    """Distance routière aller simple entre deux centres (km).
    Retourne 0 si l'origine et la destination sont identiques."""
    o, d = _cle_centre(origine), _cle_centre(destination)
    if o == d:
        return 0
    return _DISTANCES_NORM.get((o, d), 0)


def distance_aller_retour(origine, destination) -> int:
    """Distance à saisir dans l'ordre de mission : aller-retour."""
    return distance_aller(origine, destination) * 2


# ══════════════════════════════════════════════════════════════════════
# Kilométrage des véhicules
# ══════════════════════════════════════════════════════════════════════
STATUTS_EFFECTIFS = {"approved", "approuvée", "terminée"}


def _nombre(serie_ou_valeur, defaut=0.0):
    """Conversion numérique tolérante : « 85 000 », « 11,5 », « N/A »."""
    s = pd.Series(serie_ou_valeur) if not isinstance(
        serie_ou_valeur, pd.Series) else serie_ou_valeur
    s = (s.astype(str)
         .str.replace("\u00a0", "", regex=False)
         .str.replace(" ", "", regex=False)
         .str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce").fillna(defaut)


def _missions_effectuees(missions):
    """Missions réellement réalisées : les annulées et rejetées n'ont pas
    fait rouler le véhicule."""
    if missions is None or not len(missions):
        return None
    if "statut" not in missions.columns:
        return missions
    st_ = missions.statut.astype(str).str.strip().str.lower()
    return missions[st_.isin(STATUTS_EFFECTIFS) | st_.eq("")]


def km_parcourus(vehicule_id, missions) -> float:
    """Kilomètres parcourus en mission par un véhicule."""
    m = _missions_effectuees(missions)
    if m is None or "vehicule_id" not in m.columns:
        return 0.0
    m = m[m.vehicule_id.astype(str) == str(vehicule_id)]
    return float(_nombre(m.get("distance_km")).sum())


def km_actuel(v, missions=None) -> int:
    """Kilométrage courant : compteur à l'enregistrement du véhicule,
    augmenté des kilomètres parcourus en mission depuis."""
    initial = float(_nombre([v.get("km_initial")]).iloc[0])
    return int(initial + km_parcourus(v.get("vehicule_id"), missions))


def table_kilometrage(veh, missions) -> pd.DataFrame:
    """Kilométrage courant de tout le parc, en une passe."""
    if veh is None or veh.empty:
        return pd.DataFrame(columns=["vehicule_id", "km_actuel"])
    m = _missions_effectuees(missions)
    if m is None or "vehicule_id" not in m.columns:
        parcourus = pd.Series(0.0, index=veh.vehicule_id)
    else:
        parcourus = (_nombre(m.get("distance_km"))
                     .groupby(m.vehicule_id.astype(str)).sum())
    init = _nombre(veh.get("km_initial"))
    res = pd.DataFrame({
        "vehicule_id": veh.vehicule_id.astype(str),
        "km_actuel": (init.values
                      + veh.vehicule_id.astype(str).map(parcourus)
                      .fillna(0).values).round(0).astype(int)})
    return res


# ══════════════════════════════════════════════════════════════════════
# Validation des dates
# ══════════════════════════════════════════════════════════════════════
def controler_periode(date_debut, heure_debut, date_fin, heure_fin):
    """Vérifie la cohérence d'une période. Retourne (valide, message).

    Le contrôle porte sur l'instant complet — date ET heure — de sorte
    qu'un retour le même jour à une heure antérieure soit refusé.
    """
    debut = pd.Timestamp(f"{date_debut} {heure_debut}")
    fin = pd.Timestamp(f"{date_fin} {heure_fin}")
    if fin < debut:
        return False, (f"La fin de mission ({fin:%d/%m/%Y %H:%M}) est "
                       f"antérieure au départ ({debut:%d/%m/%Y %H:%M}).")
    if fin == debut:
        return False, "Le départ et le retour sont au même instant : "\
                      "précisez une heure de retour postérieure."
    duree = (fin - debut).total_seconds() / 3600
    if duree > 24 * 60:
        return False, (f"La mission durerait {duree / 24:.0f} jours : "
                       f"vérifiez les dates saisies.")
    return True, ""


def duree_jours(date_debut, heure_debut, date_fin, heure_fin) -> int:
    """Nombre de jours couverts par la mission, bornes incluses."""
    d1 = pd.Timestamp(f"{date_debut} {heure_debut}").normalize()
    d2 = pd.Timestamp(f"{date_fin} {heure_fin}").normalize()
    return max(1, int((d2 - d1).days) + 1)


# ══════════════════════════════════════════════════════════════════════
# État de conformité d'un véhicule : vert / jaune / rouge
# ══════════════════════════════════════════════════════════════════════
VERT, JAUNE, ROUGE, GRIS = "#1F7A5C", "#B8860B", "#C0392B", "#7A8794"
FOND = {VERT: "#E8F4EF", JAUNE: "#FCF3DC", ROUGE: "#FBE9E7", GRIS: "#EEF1F4"}

# Champs sans lesquels le véhicule ne peut pas être exploité correctement
CHAMPS_ESSENTIELS = {
    "immatriculation": "Immatriculation",
    "marque": "Marque",
    "modele": "Modèle",
    "type_vehicule": "Type de véhicule",
    "centre_service": "Centre de service",
    "date_premiere_circulation": "1re mise en circulation",
    "conso_nominale_l_100km": "Consommation nominale",
    "km_initial": "Kilométrage",
    "capacite_reservoir_l": "Capacité du réservoir",
}

DOCUMENTS = {
    "Visite technique": "prochaine_visite_technique",
    "Assurance": "renouvellement_assurance",
    "Admission temporaire": "renouvellement_at",
}


def _vide(valeur) -> bool:
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return True
    t = str(valeur).strip().lower()
    return t in ("", "nan", "none", "nat", "0", "<na>")


def statut_document(echeance):
    """(couleur, libellé, jours restants) pour une échéance de document."""
    d = pd.to_datetime(echeance, errors="coerce")
    if pd.isna(d):
        return ROUGE, "Non renseignée", None
    jours = (d.normalize() - pd.Timestamp.today().normalize()).days
    if jours < 0:
        return ROUGE, f"Expiré depuis {abs(jours)} j", jours
    if jours <= 30:
        return JAUNE, f"Expire dans {jours} j", jours
    return VERT, f"Valide — {jours} j restants", jours


def etat_vehicule(v) -> dict:
    """Diagnostic complet d'un véhicule : documents, champs essentiels,
    état déclaré. Retourne une liste de contrôles et une synthèse."""
    controles = []

    for libelle, colonne in DOCUMENTS.items():
        couleur, texte, _ = statut_document(v.get(colonne))
        controles.append({"bloc": "Conformité", "libelle": libelle,
                          "valeur": texte, "couleur": couleur})

    for libelle, colonne in [("Carte grise", "etat_carte_grise"),
                             ("État du véhicule", "etat_vehicule")]:
        val = str(v.get(colonne) or "").strip()
        if _vide(val):
            couleur, texte = ROUGE, "Non renseigné"
        elif val.lower() in ("bon", "fonctionnel"):
            couleur, texte = VERT, val
        else:
            couleur, texte = ROUGE, val
        controles.append({"bloc": "Conformité", "libelle": libelle,
                          "valeur": texte, "couleur": couleur})

    for colonne, libelle in CHAMPS_ESSENTIELS.items():
        val = v.get(colonne)
        manquant = _vide(val)
        controles.append({
            "bloc": "Données essentielles", "libelle": libelle,
            "valeur": "Manquant" if manquant else str(val),
            "couleur": ROUGE if manquant else VERT})

    n_rouge = sum(1 for c in controles if c["couleur"] == ROUGE)
    n_jaune = sum(1 for c in controles if c["couleur"] == JAUNE)
    if n_rouge:
        synthese = (ROUGE, f"{n_rouge} point(s) bloquant(s)")
    elif n_jaune:
        synthese = (JAUNE, f"{n_jaune} échéance(s) sous 30 jours")
    else:
        synthese = (VERT, "Véhicule entièrement conforme")
    return {"controles": controles, "synthese": synthese,
            "n_rouge": n_rouge, "n_jaune": n_jaune}


def pastille(libelle, valeur, couleur):
    """Une pastille colorée : libellé au-dessus, valeur en dessous."""
    return (f"<div style='background:{FOND[couleur]};border-left:4px solid "
            f"{couleur};border-radius:6px;padding:8px 11px;margin-bottom:8px'>"
            f"<div style='font-size:10.5px;letter-spacing:.05em;"
            f"text-transform:uppercase;color:#6B7785'>{libelle}</div>"
            f"<div style='font-weight:600;color:{couleur};font-size:13.5px'>"
            f"{valeur}</div></div>")


def bandeau_etat_vehicule(v):
    """Affiche l'état d'un véhicule : synthèse puis pastilles par contrôle."""
    etat = etat_vehicule(v)
    couleur, message = etat["synthese"]
    st.markdown(
        f"<div style='background:{FOND[couleur]};border:1px solid {couleur}44;"
        f"border-left:6px solid {couleur};border-radius:8px;padding:11px 16px;"
        f"margin-bottom:12px'><b style='color:{couleur};font-size:15px'>"
        f"{message}</b></div>", unsafe_allow_html=True)

    for bloc in ("Conformité", "Données essentielles"):
        items = [c for c in etat["controles"] if c["bloc"] == bloc]
        if not items:
            continue
        st.markdown(f"**{bloc}**")
        colonnes = st.columns(min(5, len(items)))
        for i, c in enumerate(items):
            with colonnes[i % len(colonnes)]:
                st.markdown(pastille(c["libelle"], c["valeur"], c["couleur"]),
                            unsafe_allow_html=True)
    return etat


# ══════════════════════════════════════════════════════════════════════
# État de conformité d'un véhicule
# ══════════════════════════════════════════════════════════════════════
SEUIL_ALERTE_J = 30      # en deçà, le document est signalé comme à renouveler

# Champs sans lesquels le véhicule ne peut être ni suivi ni prédit
CHAMPS_ESSENTIELS = {
    "immatriculation": "Immatriculation",
    "marque": "Marque",
    "modele": "Modèle",
    "type_vehicule": "Type de véhicule",
    "centre_service": "Centre de service",
    "date_premiere_circulation": "1re mise en circulation",
    "km_initial": "Kilométrage",
    "conso_nominale_l_100km": "Consommation nominale",
}

DOCUMENTS = {
    "Visite technique": "prochaine_visite_technique",
    "Assurance": "renouvellement_assurance",
    "Admission temporaire": "renouvellement_at",
}

VERT, JAUNE, ROUGE, GRIS = "#1F7A5C", "#B5652F", "#E2231A", "#7B8794"


def _pastille(libelle, valeur, couleur, fond):
    return (f"<div style='flex:1 1 190px;background:{fond};"
            f"border-left:4px solid {couleur};border-radius:8px;"
            f"padding:9px 12px;margin:0 8px 8px 0'>"
            f"<div style='font-size:10.5px;letter-spacing:.06em;"
            f"text-transform:uppercase;color:#6B7785'>{libelle}</div>"
            f"<div style='font-weight:600;color:{couleur};font-size:14px'>"
            f"{valeur}</div></div>")


def etat_document(echeance):
    """(libellé, couleur, fond) selon l'échéance d'un document."""
    d = pd.to_datetime(echeance, errors="coerce")
    if pd.isna(d):
        return "Non renseigné", ROUGE, "#FCEAE9"
    jours = (d.normalize() - pd.Timestamp.today().normalize()).days
    if jours < 0:
        return f"Expiré depuis {abs(jours)} j", ROUGE, "#FCEAE9"
    if jours <= SEUIL_ALERTE_J:
        return f"Expire dans {jours} j", JAUNE, "#FBF1E8"
    return f"Conforme — {d:%d/%m/%Y}", VERT, "#EAF4EF"


def champs_manquants(v) -> list:
    """Champs essentiels vides ou nuls, qui empêchent l'exploitation."""
    manquants = []
    for col, libelle in CHAMPS_ESSENTIELS.items():
        val = v.get(col)
        vide = (val is None or (isinstance(val, float) and pd.isna(val))
                or str(val).strip().lower() in ("", "nan", "none", "0"))
        if vide:
            manquants.append(libelle)
    return manquants


def panneau_conformite(v):
    """Bandeau coloré résumant l'état d'un véhicule : vert conforme,
    jaune à moins de trente jours, rouge expiré ou champ essentiel
    manquant."""
    blocs = []
    for libelle, colonne in DOCUMENTS.items():
        txt, couleur, fond = etat_document(v.get(colonne))
        blocs.append(_pastille(libelle, txt, couleur, fond))

    for libelle, colonne in [("État du véhicule", "etat_vehicule"),
                             ("Carte grise", "etat_carte_grise")]:
        val = str(v.get(colonne) or "").strip()
        if not val or val.lower() in ("nan", "none"):
            blocs.append(_pastille(libelle, "Non renseigné", ROUGE, "#FCEAE9"))
        elif val.lower().startswith(("non", "pas")):
            blocs.append(_pastille(libelle, val, ROUGE, "#FCEAE9"))
        else:
            blocs.append(_pastille(libelle, val, VERT, "#EAF4EF"))

    st.markdown(f"<div style='display:flex;flex-wrap:wrap'>"
                f"{''.join(blocs)}</div>", unsafe_allow_html=True)

    manquants = champs_manquants(v)
    if manquants:
        st.error(f"🔴 **Champ(s) essentiel(s) non renseigné(s)** : "
                 f"{', '.join(manquants)}. Sans ces informations, le véhicule "
                 f"est exclu des analyses et des prédictions.")
    else:
        st.success("🟢 Fiche complète : toutes les informations nécessaires "
                   "au suivi et à la prédiction sont renseignées.")
    return manquants


def couleur_ligne_vehicule(v) -> str:
    """Pastille de synthèse pour une ligne de liste."""
    if champs_manquants(v):
        return "🔴 Incomplet"
    etats = [etat_document(v.get(c))[1] for c in DOCUMENTS.values()]
    if ROUGE in etats:
        return "🔴 Non conforme"
    if JAUNE in etats:
        return "🟠 À renouveler"
    return "🟢 Conforme"


# ══════════════════════════════════════════════════════════════════════
# Sélection multiple pour les actions en masse
# ══════════════════════════════════════════════════════════════════════
def selection_multiple(df, colonnes, cle, message=None):
    """Tableau à cases à cocher. Retourne les lignes sélectionnées.

    Repli automatique si la version de Streamlit ne gère pas la
    sélection : le tableau reste consultable, sans action en masse.
    """
    if df is None or df.empty:
        st.info("Aucun élément.")
        return df.iloc[0:0] if df is not None else None
    st.caption(message or "☑️ Cochez une ou plusieurs lignes pour agir "
                          "sur l'ensemble.")
    aff = df[[c for c in colonnes if c in df.columns]].reset_index(drop=True)
    try:
        ev = st.dataframe(aff, use_container_width=True, hide_index=True,
                          on_select="rerun", selection_mode="multi-row",
                          key=cle)
        idx = list(ev.selection.rows)
    except TypeError:
        st.dataframe(aff, use_container_width=True, hide_index=True)
        st.info("💡 Mettez à jour Streamlit pour les actions en masse : "
                "`pip install -U streamlit`")
        idx = []
    return df.reset_index(drop=True).iloc[idx]


def confirmer_action(cle, libelle, n, detail=""):
    """Demande de confirmation avant une action en masse.
    Retourne True une seule fois, quand l'utilisateur a confirmé."""
    if st.button(libelle, key=f"btn_{cle}"):
        st.session_state[f"conf_{cle}"] = True
    if st.session_state.get(f"conf_{cle}"):
        st.warning(f"⚠️ **Confirmer « {libelle} » sur {n} élément(s) ?** "
                   f"{detail}")
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("✅ Oui, appliquer", key=f"oui_{cle}", type="primary"):
            del st.session_state[f"conf_{cle}"]
            return True
        if c2.button("❌ Annuler", key=f"non_{cle}"):
            del st.session_state[f"conf_{cle}"]
            st.rerun()
    return False


def puce_document(echeance) -> str:
    """Indicateur court à accoler au libellé d'un champ de conformité."""
    d = pd.to_datetime(echeance, errors="coerce")
    if pd.isna(d):
        return "🔴 non renseignée"
    jours = (d.normalize() - pd.Timestamp.today().normalize()).days
    if jours < 0:
        return f"🔴 expirée depuis {abs(jours)} j"
    if jours <= SEUIL_ALERTE_J:
        return f"🟠 expire dans {jours} j"
    return "🟢 conforme"


def puce_champ(valeur) -> str:
    """Indicateur pour un champ essentiel : vide ou nul = à renseigner."""
    vide = (valeur is None
            or (isinstance(valeur, float) and pd.isna(valeur))
            or str(valeur).strip().lower() in ("", "nan", "none", "0"))
    return "🔴 à renseigner" if vide else ""


# ══════════════════════════════════════════════════════════════════════
# Personnes : staffs et collaborateurs externes
# ══════════════════════════════════════════════════════════════════════
def est_externe(personne) -> bool:
    """Un collaborateur externe est un participant qui n'appartient pas
    au personnel : consultant, partenaire, bénéficiaire accompagné."""
    v = personne.get("externe") if hasattr(personne, "get") else None
    return str(v or "").strip().lower() in ("oui", "true", "1", "externe")


def nom_personne(personne, avec_mention=True) -> str:
    """« Marie Sagna » ou « Marie Sagna (Externe) »."""
    nom = str(personne.get("nom_complet") or "").strip()
    if avec_mention and est_externe(personne):
        return f"{nom} (Externe)"
    return nom
