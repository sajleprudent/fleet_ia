"""
Étape 2.1 — Feature engineering pour la maintenance prédictive.

Approche "snapshots" : chaque semaine, pour chaque véhicule actif, on
construit un vecteur de caractéristiques observables à cette date, et
la cible = survenue d'une panne dans les 30 jours suivants.

Règle d'or : AUCUNE variable du futur, AUCUNE variable latente (_*).
La surconsommation récente sert de proxy observable de l'usure.

v9.0 — tolérance aux données réelles :
  - dates de formats mélangés (simulation + saisie + import)
  - colonnes optionnelles absentes (part_piste, taux_charge, km_compteur…)
  - carburant non rattaché à une mission
  - diagnostic explicite quand l'historique est insuffisant
"""
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "dashboard"))

import numpy as np
import pandas as pd

from config import DATA_RAW, DATA_PROCESSED
import crud

HORIZON_J = 30          # horizon de prédiction (jours)
FREQ_SNAPSHOT = "W-MON" # une photo par semaine
MIN_JOURS = 150         # historique minimal exploitable (120j + horizon)

# Valeurs par défaut des colonnes optionnelles absentes des imports réels
DEFAUTS = {
    "part_piste": 0.3,
    "taux_charge": 0.5,
    "duree_jours": 1,
    "conso_nominale_l_100km": 10.0,
    "km_initial": 0,
    "km_compteur": np.nan,
    "cout_fcfa": 0,
}


# ══════════════════════════════════════════════════════════════════════
def _dates(df, cols):
    """Convertit des colonnes en dates même si les formats sont mélangés
    (2023-07-01, 2026-07-14 07:00:00, formats importés)."""
    for c in cols:
        if c in df.columns:
            try:
                df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed")
            except (ValueError, TypeError):
                df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def _assurer(df, colonnes, nom_table):
    """Crée les colonnes optionnelles manquantes avec leur valeur par défaut
    et signale ce qui a été complété (transparence méthodologique)."""
    manquantes = [c for c in colonnes if c not in df.columns]
    for c in manquantes:
        df[c] = DEFAUTS.get(c, np.nan)
    if manquantes:
        print(f"   ⚠️  {nom_table} : colonne(s) absente(s) complétée(s) par "
              f"défaut → {', '.join(manquantes)}")
    return df


def _num(serie, defaut=0.0):
    """Conversion numérique tolérante ('12 000', '11,5', 'N/A')."""
    s = (serie.astype(str)
         .str.replace("\u00a0", "", regex=False)   # espace insécable
         .str.replace(" ", "", regex=False)
         .str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce").fillna(defaut)


def _lire(nom, dates):
    """Lecture depuis la base ; repli sur le CSV si la migration n'a pas
    encore été faite."""
    df = crud.lire(nom)
    if df is None:
        p = DATA_RAW / nom if str(nom).endswith(".csv") \
            else DATA_RAW / f"{nom}.csv"
        if not p.exists():
            raise SystemExit(
                f"❌ Table « {crud.nom_table(nom)} » absente de la base et "
                f"fichier {p.name} introuvable.\n"
                f"   Lancez : python src/data/migrer_sqlite.py")
        df = pd.read_csv(p, low_memory=False)
    return _dates(df, dates)


# ══════════════════════════════════════════════════════════════════════
def charger():
    print("── Chargement des données ──────────────────────")
    veh = _lire("vehicules.csv", [])
    mis = _lire("missions.csv", ["date_depart", "date_fin"])
    fuel = _lire("carburant.csv", ["date"])
    mnt = _lire("maintenance.csv", ["date"])

    # Colonnes optionnelles
    veh = _assurer(veh, ["type_vehicule", "marque", "localite",
                         "annee_mise_en_service", "km_initial",
                         "conso_nominale_l_100km"], "vehicules")
    mis = _assurer(mis, ["part_piste", "taux_charge", "distance_km"], "missions")
    mnt = _assurer(mnt, ["type_intervention", "km_compteur", "cout_fcfa"],
                   "maintenance")

    # Lignes sans date exploitable : inutilisables pour l'apprentissage
    for nom, df, col in [("missions", mis, "date_depart"),
                         ("carburant", fuel, "date"),
                         ("maintenance", mnt, "date")]:
        n_avant = len(df)
        df.drop(df.index[df[col].isna()], inplace=True)
        if n_avant - len(df):
            print(f"   ⚠️  {nom} : {n_avant - len(df)} ligne(s) sans date "
                  f"valide, écartée(s)")

    # Numériques tolérants
    mis["distance_km"] = _num(mis.distance_km, 0.0)
    mis["part_piste"] = _num(mis.part_piste, DEFAUTS["part_piste"]).clip(0, 1)
    mis["taux_charge"] = _num(mis.taux_charge, DEFAUTS["taux_charge"]).clip(0, 1)
    veh["km_initial"] = _num(veh.km_initial, 0)
    veh["conso_nominale_l_100km"] = _num(
        veh.conso_nominale_l_100km, DEFAUTS["conso_nominale_l_100km"]) \
        .replace(0, DEFAUTS["conso_nominale_l_100km"])
    veh["annee_mise_en_service"] = _num(veh.annee_mise_en_service,
                                        pd.Timestamp.today().year)
    if "litres" in fuel.columns:
        fuel["litres"] = _num(fuel.litres, 0.0)
    mnt["km_compteur"] = _num(mnt.km_compteur, np.nan) \
        if "km_compteur" in mnt.columns else np.nan

    # ── Surconsommation : nécessite le rattachement plein -> mission ──
    if "numero_mission" in fuel.columns and "numero_mission" in mis.columns \
            and "litres" in fuel.columns:
        ref_mis = mis[["numero_mission", "distance_km"]] \
            .drop_duplicates("numero_mission")
        fuel = fuel.merge(ref_mis, on="numero_mission", how="left")
        if "conso_nominale_l_100km" not in fuel.columns:
            fuel = fuel.merge(veh[["vehicule_id", "conso_nominale_l_100km"]],
                              on="vehicule_id", how="left")
        fuel["conso_nominale_l_100km"] = fuel.conso_nominale_l_100km.fillna(
            DEFAUTS["conso_nominale_l_100km"])
        dist = fuel.distance_km.replace(0, np.nan)
        fuel["surconso"] = (fuel.litres / dist * 100) \
            / fuel.conso_nominale_l_100km
        fuel = fuel[fuel.surconso.between(0.2, 5)]   # écarte les aberrations
        n_ok = int(fuel.surconso.notna().sum())
        print(f"   Surconsommation calculable sur {n_ok:,} plein(s)")
    else:
        fuel["surconso"] = np.nan
        print("   ⚠️  Surconsommation non calculable (pleins non rattachés "
              "aux missions ou colonne 'litres' absente)")

    print(f"   Véhicules {len(veh):,} · missions {len(mis):,} · "
          f"pleins {len(fuel):,} · interventions {len(mnt):,}")
    return veh, mis, fuel, mnt


# ══════════════════════════════════════════════════════════════════════
def construire_snapshots():
    veh, mis, fuel, mnt = charger()

    est_panne = mnt.type_intervention.astype(str).str.strip().str.lower() \
                   .eq("panne")
    pannes = mnt.loc[est_panne, ["vehicule_id", "date"]]
    entretiens = mnt[["vehicule_id", "date", "km_compteur"]]

    print("\n── Construction des observations ───────────────")
    if mis.empty:
        raise SystemExit("❌ Aucune mission exploitable : impossible de "
                         "construire les observations.")
    if pannes.empty:
        print("   ⚠️  AUCUNE panne enregistrée : la variable cible sera "
              "vide et le modèle ne pourra pas être entraîné.\n"
              "       Saisissez l'historique des pannes dans "
              "🛠️ Maintenance (type d'intervention = « Panne »).")

    debut = mis.date_depart.min() + pd.Timedelta(days=120)
    fin = mis.date_depart.max() - pd.Timedelta(days=HORIZON_J)
    couverture = (mis.date_depart.max() - mis.date_depart.min()).days
    if debut > fin:
        raise SystemExit(
            f"❌ Historique insuffisant : {couverture} jours de missions "
            f"({mis.date_depart.min().date()} → {mis.date_depart.max().date()}).\n"
            f"   Il en faut au moins {MIN_JOURS} (120 j d'historique + "
            f"{HORIZON_J} j d'horizon de prédiction).\n"
            f"   Continuez la saisie ou importez l'historique rétrospectif.")

    dates_snap = pd.date_range(debut, fin, freq=FREQ_SNAPSHOT)
    print(f"   Période couverte : {couverture} jours → "
          f"{len(dates_snap)} photographies hebdomadaires")

    mis = mis.sort_values("date_depart")
    fuel = fuel.sort_values("date")

    rows = []
    for d in dates_snap:
        m90 = mis[(mis.date_depart >= d - pd.Timedelta(days=90))
                  & (mis.date_depart < d)]
        m30 = m90[m90.date_depart >= d - pd.Timedelta(days=30)]
        f90 = fuel[(fuel.date >= d - pd.Timedelta(days=90))
                   & (fuel.date < d)]

        g90 = m90.groupby("vehicule_id").agg(
            km_90j=("distance_km", "sum"),
            n_missions_90j=("numero_mission", "count")
            if "numero_mission" in m90.columns else ("distance_km", "count"),
            piste_moy_90j=("part_piste", "mean"),
            charge_moy_90j=("taux_charge", "mean"),
        )
        kp = (m90.distance_km * m90.part_piste).groupby(m90.vehicule_id).sum() \
                 .rename("km_piste_90j")
        g30 = m30.groupby("vehicule_id").distance_km.sum().rename("km_30j")
        s90 = f90.groupby("vehicule_id").surconso.mean().rename("surconso_90j") \
            if "surconso" in f90.columns else pd.Series(dtype=float,
                                                        name="surconso_90j")
        f30 = f90[f90.date >= d - pd.Timedelta(days=30)]
        s30 = f30.groupby("vehicule_id").surconso.mean().rename("surconso_30j") \
            if "surconso" in f30.columns else pd.Series(dtype=float,
                                                        name="surconso_30j")

        snap = veh.drop_duplicates("vehicule_id").set_index("vehicule_id")[
            ["type_vehicule", "marque", "localite", "annee_mise_en_service",
             "km_initial"]
        ].join([g90, kp, g30, s90, s30])
        snap["date_snapshot"] = d
        snap["age_annees"] = d.year - snap.annee_mise_en_service

        rows.append(snap.reset_index())

    df = pd.concat(rows, ignore_index=True)

    # ── Km cumulés ────────────────────────────────────────────────────
    mis_cum = mis.groupby(["vehicule_id", "date_depart"]).distance_km.sum() \
                 .groupby(level=0).cumsum().reset_index() \
                 .rename(columns={"distance_km": "km_cumules_missions"})
    df = pd.merge_asof(
        df.sort_values("date_snapshot"),
        mis_cum.sort_values("date_depart"),
        left_on="date_snapshot", right_on="date_depart",
        by="vehicule_id", direction="backward",
    ).drop(columns="date_depart")
    df["km_total"] = df.km_initial + df.km_cumules_missions.fillna(0)

    # ── Dernier entretien ─────────────────────────────────────────────
    ent = entretiens.dropna(subset=["date"]).sort_values("date") \
                    .rename(columns={"date": "date_maint"})
    if len(ent):
        df = pd.merge_asof(
            df.sort_values("date_snapshot"),
            ent[["vehicule_id", "date_maint", "km_compteur"]]
            .sort_values("date_maint"),
            left_on="date_snapshot", right_on="date_maint",
            by="vehicule_id", direction="backward",
        )
    else:
        df["date_maint"] = pd.NaT
        df["km_compteur"] = np.nan
    df["jours_depuis_maint"] = (df.date_snapshot - df.date_maint).dt.days \
                                                                 .fillna(365)
    df["km_depuis_maint"] = (df.km_total - df.km_compteur).clip(lower=0) \
                                                          .fillna(df.km_90j)
    df = df.drop(columns=["date_maint", "km_compteur", "km_cumules_missions"])

    # ── Pannes sur 12 mois & CIBLE ────────────────────────────────────
    p = pannes.rename(columns={"date": "date_panne"})
    cnt, tgt = [], []
    for d, grp in df.groupby("date_snapshot"):
        base = grp[["vehicule_id", "date_snapshot"]]
        w12 = p[(p.date_panne >= d - pd.Timedelta(days=365))
                & (p.date_panne < d)]
        c = w12.groupby("vehicule_id").size()
        cnt.append(base.assign(
            n_pannes_12m=grp.vehicule_id.map(c).fillna(0).astype(int)))
        wh = p[(p.date_panne >= d)
               & (p.date_panne < d + pd.Timedelta(days=HORIZON_J))]
        tgt.append(base.assign(
            panne_30j=grp.vehicule_id.isin(set(wh.vehicule_id)).astype(int)))
    df = df.merge(pd.concat(cnt), on=["vehicule_id", "date_snapshot"])
    df = df.merge(pd.concat(tgt), on=["vehicule_id", "date_snapshot"])

    # ── Km de piste cumulés ───────────────────────────────────────────
    mis["km_piste"] = mis.distance_km * mis.part_piste
    kp_cum = mis.groupby(["vehicule_id", "date_depart"]).km_piste.sum() \
                .groupby(level=0).cumsum().reset_index() \
                .rename(columns={"km_piste": "km_piste_cumules"})
    df = pd.merge_asof(
        df.sort_values("date_snapshot"),
        kp_cum.sort_values("date_depart"),
        left_on="date_snapshot", right_on="date_depart",
        by="vehicule_id", direction="backward",
    ).drop(columns="date_depart")
    df["km_piste_cumules"] = df.km_piste_cumules.fillna(0)

    # ── Véhicules inactifs & imputations ──────────────────────────────
    df = df[df.n_missions_90j.fillna(0) > 0].copy()
    if df.empty:
        raise SystemExit("❌ Aucun véhicule actif sur les fenêtres de 90 jours.")
    for c in ["km_90j", "km_30j", "n_missions_90j", "km_piste_90j"]:
        df[c] = df[c].fillna(0)
    med_sur = df.surconso_90j.median()
    df["surconso_90j"] = df.surconso_90j.fillna(
        med_sur if pd.notna(med_sur) else 1.0)
    df["surconso_30j"] = df.surconso_30j.fillna(df.surconso_90j)
    df["tendance_surconso"] = df.surconso_30j - df.surconso_90j
    for c in ["piste_moy_90j", "charge_moy_90j"]:
        med = df[c].median()
        df[c] = df[c].fillna(med if pd.notna(med) else DEFAUTS.get(c, 0.3))
    return df


# ══════════════════════════════════════════════════════════════════════
def main():
    DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    df = construire_snapshots()
    df.to_parquet(DATA_PROCESSED / "features_maintenance.parquet", index=False)

    n_pos = int(df.panne_30j.sum())
    print("\n── Dataset maintenance prédictive ──────────────")
    print(f"Observations     : {len(df):,}")
    print(f"Période          : {df.date_snapshot.min().date()} → "
          f"{df.date_snapshot.max().date()}")
    print(f"Taux de positifs : {df.panne_30j.mean()*100:.2f} % "
          f"({n_pos} panne-fenêtres)")

    if n_pos < 30:
        print("\n⚠️  ATTENTION : trop peu de cas positifs pour un "
              "entraînement fiable (30 minimum, 100+ recommandé).")
        print("    L'entraînement produira des résultats non significatifs.")
        print("    Options : enrichir l'historique de pannes, ou conserver "
              "le modèle entraîné sur les données de simulation.")
    else:
        print("\nContrôle de fuite temporelle — corrélations features/cible :")
        num = df.select_dtypes("number").drop(
            columns=["panne_30j", "annee_mise_en_service", "km_initial"],
            errors="ignore")
        print(num.corrwith(df.panne_30j).sort_values(ascending=False)
                 .round(3).to_string())
        print("\n(des corrélations > 0,5 signaleraient une fuite temporelle)")


if __name__ == "__main__":
    main()
