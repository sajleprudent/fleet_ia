"""
Génération d'activité simulée à partir des RÉFÉRENTIELS RÉELS importés.

À exécuter depuis la racine du projet :
    python src/data/generer_activite.py

Principe
--------
Les véhicules (vehicules.csv) et les staffs (staffs.csv) sont vos données
réelles : ils ne sont JAMAIS modifiés. Seules les tables transactionnelles
sont générées :
    missions.csv · carburant.csv · maintenance.csv

L'activité produite n'est pas aléatoire : elle encode des relations
causales réalistes que les modèles devront redécouvrir —
    piste + charge + âge + style de conduite   -> consommation
    kilomètres + piste + âge                   -> usure
    usure                                      -> probabilité de panne

Les paramètres ci-dessous sont ajustables selon votre contexte.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "dashboard"))

import numpy as np
import pandas as pd

from config import (DATA_RAW, CENTRES_SERVICE, CODES_DEPT, PRIX_CARBURANT,
                    TYPES_PANNES, SEED)
import crud

# ══ PARAMÈTRES AJUSTABLES ═════════════════════════════════════════════
ANNEES_HISTORIQUE = 3          # profondeur de l'historique généré
DATE_FIN = pd.Timestamp.today().normalize()

# Probabilité qu'un véhicule parte en mission un jour de semaine donné
P_MISSION_SEMAINE = 0.30
P_MISSION_WEEKEND = 0.07
MOIS_PICS = (3, 4, 10, 11)     # périodes de forte activité programme

# Distance moyenne aller-retour (km) par zone
DIST_MOY = {"Bureau National": 90, "Zone Centre": 210, "Zone Sud": 260}
DIST_MOTO = 35                 # les motos font des trajets courts

# Part de piste moyenne par zone (routes non bitumées)
PART_PISTE = {"Bureau National": 0.15, "Zone Centre": 0.55, "Zone Sud": 0.70}

KM_ENTRE_ENTRETIENS = 5000
TAUX_ANOMALIE_CARBURANT = 0.025   # pleins anormaux (fuite, détournement)

OBJETS = ["Suivi programme", "Distribution", "Supervision terrain",
          "Réunion partenaires", "Évaluation", "Logistique", "Visite IT",
          "Mission de contrôle", "Formation"]
STATUTS_HISTORIQUES = (["Approved"] * 88 + ["Canceled"] * 7
                       + ["Rejected"] * 5)

rng = np.random.default_rng(SEED)


# ══════════════════════════════════════════════════════════════════════
def _num(serie, defaut):
    s = (serie.astype(str).str.replace("\u00a0", "", regex=False)
         .str.replace(" ", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce").fillna(defaut)


def charger_referentiels():
    veh = crud.lire("vehicules")
    staffs = crud.lire("staffs")
    if veh is None or veh.empty:
        raise SystemExit("❌ Aucun véhicule en base : importez d'abord "
                         "votre parc.")
    if staffs is None or staffs.empty:
        raise SystemExit("❌ Aucun staff en base : importez d'abord "
                         "votre personnel.")

    # Clé véhicule = immatriculation
    if "vehicule_id" not in veh.columns:
        veh["vehicule_id"] = veh["immatriculation"]
    veh = veh[veh.vehicule_id.notna()].copy()
    veh["vehicule_id"] = veh.vehicule_id.astype(str).str.strip()

    # Localité : depuis le centre de service
    if "localite" not in veh.columns or veh.localite.isna().any():
        veh["localite"] = veh.get("centre_service", "").map(
            CENTRES_SERVICE).fillna("Bureau National")
    veh["localite"] = veh.localite.fillna("Bureau National")

    veh["annee"] = _num(veh.get("annee_mise_en_service",
                                pd.Series(2018, index=veh.index)), 2018)
    veh["conso"] = _num(veh.get("conso_nominale_l_100km",
                                pd.Series(11.0, index=veh.index)), 11.0) \
        .replace(0, 11.0)
    veh["km_init"] = _num(veh.get("km_initial",
                                  pd.Series(0, index=veh.index)), 0)
    veh["est_moto"] = veh.get("type_vehicule", "").astype(str) \
                         .str.lower().str.startswith("moto")
    # Les véhicules non fonctionnels ne roulent pas
    if "etat_vehicule" in veh.columns:
        hs = veh.etat_vehicule.astype(str).str.lower().str.startswith("non")
        if hs.any():
            print(f"   {int(hs.sum())} véhicule(s) non fonctionnel(s) exclu(s)")
        veh = veh[~hs].copy()

    # Staffs
    staffs["staff_id"] = staffs.staff_id.astype(str).str.strip()
    if "localite" not in staffs.columns:
        staffs["localite"] = staffs.get("centre_service", "").map(
            CENTRES_SERVICE).fillna("Bureau National")
    staffs["localite"] = staffs.localite.fillna("Bureau National")
    roles = staffs.get("roles", pd.Series("", index=staffs.index)).astype(str)
    chauffeurs = staffs[roles.str.contains("chauffeur", case=False, na=False)]
    approbateurs = staffs[roles.str.contains("approbateur", case=False,
                                             na=False)]
    if chauffeurs.empty:
        raise SystemExit(
            "❌ Aucun staff n'a le rôle « Chauffeur ».\n"
            "   Attribuez ce rôle dans 👥 Staffs, ou renseignez la colonne "
            "`roles` de staffs.csv, puis relancez.")
    if approbateurs.empty:
        print("   ⚠️  Aucun approbateur : le champ sera laissé vide.")

    print(f"   {len(veh)} véhicule(s) · {len(staffs)} staff(s) dont "
          f"{len(chauffeurs)} chauffeur(s) et {len(approbateurs)} "
          f"approbateur(s)")
    return veh, staffs, chauffeurs, approbateurs


# ══════════════════════════════════════════════════════════════════════
def simuler(veh, staffs, chauffeurs, approbateurs):
    debut = DATE_FIN - pd.DateOffset(years=ANNEES_HISTORIQUE)
    dates = pd.date_range(debut, DATE_FIN, freq="D")
    centres = list(CENTRES_SERVICE.keys())
    depts = [d for d in CODES_DEPT if d in
             {"ICT", "Finance", "Administration", "Operations",
              "Supply chain", "People & Culture", "HEA"}] or ["Operations"]

    # Profil de conduite latent par chauffeur (0 = souple, 1 = agressif)
    agressivite = {c: float(np.clip(rng.beta(2.2, 3.5), 0.02, 0.98))
                   for c in chauffeurs.staff_id}

    # Un parc réel n'est pas homogène : quelques véhicules assurent
    # l'essentiel des déplacements, d'autres roulent peu. On tire donc une
    # intensité d'usage par véhicule et une disponibilité par chauffeur,
    # de sorte que les analyses d'utilisation et d'exposition portent sur
    # des situations contrastées.
    intensite = {}
    for i, v in enumerate(veh.itertuples()):
        tirage = rng.random()
        if tirage < 0.15:
            intensite[v.vehicule_id] = float(rng.uniform(1.8, 2.6))   # intensif
        elif tirage < 0.75:
            intensite[v.vehicule_id] = float(rng.uniform(0.7, 1.3))   # courant
        else:
            intensite[v.vehicule_id] = float(rng.uniform(0.10, 0.45))  # dormant
    dispo_chauffeur = {c: float(np.clip(rng.beta(2.0, 2.0) * 2, 0.15, 2.2))
                       for c in chauffeurs.staff_id}
    print(f"   profils : "
          f"{sum(1 for x in intensite.values() if x > 1.6)} véhicule(s) "
          f"intensif(s), "
          f"{sum(1 for x in intensite.values() if x < 0.5)} peu utilisé(s)")
    ch_par_loc = {loc: chauffeurs[chauffeurs.localite == loc]
                  for loc in set(veh.localite)}
    for loc, sous in ch_par_loc.items():          # repli si aucun sur zone
        if sous.empty:
            ch_par_loc[loc] = chauffeurs
    st_par_loc = {loc: staffs[staffs.localite == loc]
                  for loc in set(veh.localite)}
    for loc, sous in st_par_loc.items():
        if sous.empty:
            st_par_loc[loc] = staffs
    idx_staff = staffs.set_index("staff_id")

    # Le compteur part du kilométrage réel saisi dans la fiche et
    # s'incrémente à chaque mission : les relevés portés sur les
    # interventions de maintenance sont ainsi cohérents.
    etat = {v.vehicule_id: {
        "km": float(v.km_init),
        "usure": float(np.clip(0.04 * max(0, DATE_FIN.year - v.annee)
                               + rng.normal(0, 0.05), 0, 0.75)),
        "indispo": None,
        "km_entretien": float(rng.integers(0, KM_ENTRE_ENTRETIENS)),
    } for v in veh.itertuples()}

    missions, carburant, maintenance = [], [], []
    n_mis = n_fuel = n_mnt = 0
    seq_num = 0

    for date in dates:
        hivernage = date.month in (7, 8, 9, 10)
        p_base = P_MISSION_SEMAINE if date.weekday() < 5 else P_MISSION_WEEKEND
        if date.month in MOIS_PICS:
            p_base *= 1.3

        for v in veh.itertuples():
            st_v = etat[v.vehicule_id]
            if st_v["indispo"] is not None and date <= st_v["indispo"]:
                continue

            # ── Entretien préventif ───────────────────────────────────
            if st_v["km_entretien"] >= KM_ENTRE_ENTRETIENS:
                n_mnt += 1
                maintenance.append({
                    "maintenance_id": f"MT-{n_mnt:05d}",
                    "vehicule_id": v.vehicule_id, "date": date.date(),
                    "type_intervention": "Entretien préventif",
                    "categorie": "Vidange/Révision",
                    "cout_fcfa": int(max(25_000, rng.normal(
                        30_000 if v.est_moto else 85_000, 15_000))),
                    "jours_immobilisation": 1,
                    "km_compteur": int(st_v["km"]),
                })
                st_v["km_entretien"] = 0
                st_v["usure"] = max(0.0, st_v["usure"] - 0.015)
                st_v["indispo"] = date
                continue

            p_veh = min(0.95, p_base * intensite.get(v.vehicule_id, 1.0))
            if rng.random() > p_veh:
                continue

            # ── Affectation ───────────────────────────────────────────
            pool_ch = ch_par_loc[v.localite]
            poids = np.array([dispo_chauffeur.get(c, 1.0)
                              for c in pool_ch.staff_id], dtype=float)
            poids = poids / poids.sum() if poids.sum() else None
            ch = pool_ch.iloc[int(rng.choice(len(pool_ch), p=poids))]
            pool_st = st_par_loc[v.localite]
            agent = pool_st.iloc[int(rng.integers(0, len(pool_st)))]
            n_pax = int(rng.integers(0, 3))
            pax = pool_st.sample(min(n_pax, len(pool_st)),
                                 random_state=int(rng.integers(0, 1e6)))
            ids_bord = [agent.staff_id] + [p for p in pax.staff_id
                                           if p != agent.staff_id]
            noms_bord = [idx_staff.loc[i, "nom_complet"] for i in ids_bord]

            # ── Trajet ────────────────────────────────────────────────
            base = DIST_MOTO if v.est_moto else DIST_MOY.get(v.localite, 120)
            dist = max(10.0, float(rng.normal(base, base * 0.45)))
            piste = float(np.clip(rng.normal(PART_PISTE.get(v.localite, 0.3),
                                             0.12), 0, 1))
            charge = float(np.clip(rng.beta(2, 2.5), 0.05, 1.0))
            duree = 1 if dist < 300 else int(rng.integers(1, 4))
            origine = v.centre_service if "centre_service" in veh.columns \
                and pd.notna(getattr(v, "centre_service", None)) else "Dakar"
            dest = rng.choice([c for c in centres if c != origine])
            dept = str(rng.choice(depts))
            seq_num = (seq_num % 9999) + 1
            statut = str(rng.choice(STATUTS_HISTORIQUES))

            n_mis += 1
            numero = (f"WVS-{CODES_DEPT.get(dept, 'GEN')}-"
                      f"{date:%Y-%m-%d}-{seq_num:04d}")
            missions.append({
                "numero_mission": numero,
                "statut": statut, "objet": str(rng.choice(OBJETS)),
                "departement": dept, "imputation": f"DEPARTMENT / {dept}",
                "agent_principal": agent.nom_complet,
                "agent_id": agent.staff_id,
                "fonction_agent": agent.get("fonction", ""),
                "telephone_agent": agent.get("telephone", ""),
                "personnes_a_bord": ", ".join(noms_bord),
                "personnes_ids": ",".join(ids_bord),
                "approbateur": (approbateurs.iloc[int(rng.integers(
                    0, len(approbateurs)))].nom_complet
                    if len(approbateurs) else ""),
                "approbateur_id": (approbateurs.iloc[int(rng.integers(
                    0, len(approbateurs)))].staff_id
                    if len(approbateurs) else ""),
                "date_approbation": (f"{date - pd.Timedelta(days=1):%Y-%m-%d %H:%M}"
                                     if statut == "Approved" else ""),
                "vehicule_id": v.vehicule_id, "chauffeur_id": ch.staff_id,
                "origine": origine, "destination": dest,
                "date_depart": f"{date:%Y-%m-%d} 07:00",
                "date_fin": f"{date + pd.Timedelta(days=duree - 1):%Y-%m-%d} 18:00",
                "duree_jours": duree, "distance_km": round(dist, 1),
                "part_piste": round(piste, 2), "taux_charge": round(charge, 2),
                "observations": "",
            })

            # Une mission annulée ou rejetée n'a pas eu lieu
            if statut != "Approved":
                continue

            # ── Consommation ──────────────────────────────────────────
            agg = agressivite.get(ch.staff_id, 0.4)
            age = max(0, DATE_FIN.year - v.annee)
            conso = v.conso * (1 + 0.22 * piste + 0.13 * charge
                               + 0.25 * agg + 0.012 * age
                               + (0.05 if hivernage else 0.0)
                               + 0.20 * st_v["usure"])
            litres = dist / 100 * conso * rng.normal(1.0, 0.05)
            anomalie = rng.random() < TAUX_ANOMALIE_CARBURANT
            if anomalie:
                litres *= rng.uniform(1.35, 1.9)
            n_fuel += 1
            carburant.append({
                "plein_id": f"FL-{n_fuel:06d}", "numero_mission": numero,
                "vehicule_id": v.vehicule_id, "chauffeur_id": ch.staff_id,
                "date": date.date(), "litres": round(max(1.0, litres), 1),
                "montant_fcfa": int(max(1.0, litres) * PRIX_CARBURANT),
                "_anomalie_reelle": int(anomalie),
            })

            # ── Usure et panne ────────────────────────────────────────
            st_v["km"] += dist
            st_v["km_entretien"] += dist
            st_v["usure"] = min(1.0, st_v["usure"] + (dist / 1000) * (
                0.003 + 0.020 * piste + 0.005 * agg + 0.0015 * age))

            p_panne = 0.0006 + 0.018 * st_v["usure"] ** 2.2 + 0.002 * (age > 9)
            if rng.random() < p_panne:
                cat = str(rng.choice(list(TYPES_PANNES.keys())))
                _, cout_moy, immo_moy = TYPES_PANNES[cat]
                immo = max(1, int(rng.normal(immo_moy, 1)))
                n_mnt += 1
                maintenance.append({
                    "maintenance_id": f"MT-{n_mnt:05d}",
                    "vehicule_id": v.vehicule_id,
                    "date": (date + pd.Timedelta(days=duree)).date(),
                    "type_intervention": "Panne", "categorie": cat,
                    "cout_fcfa": int(max(25_000,
                                         rng.normal(cout_moy, cout_moy * 0.3))),
                    "jours_immobilisation": immo,
                    "km_compteur": int(st_v["km"]),
                })
                st_v["indispo"] = date + pd.Timedelta(days=duree + immo)
                st_v["usure"] = max(0.0, st_v["usure"] - 0.10)

    return (pd.DataFrame(missions), pd.DataFrame(carburant),
            pd.DataFrame(maintenance))


# ══════════════════════════════════════════════════════════════════════
def main():
    print("── Référentiels réels ──────────────────────────")
    veh, staffs, chauffeurs, approbateurs = charger_referentiels()

    if crud.BASE.exists():
        sauv = crud.BASE.with_name(
            f"fleet_ia_sauvegarde_{datetime.now():%Y%m%d_%H%M%S}.db")
        shutil.copy(crud.BASE, sauv)
        print(f"💾 Base sauvegardée : {sauv.name}")

    print(f"\n── Simulation de {ANNEES_HISTORIQUE} an(s) d'activité "
          f"jusqu'au {DATE_FIN.date()} ──")
    mis, fuel, mnt = simuler(veh, staffs, chauffeurs, approbateurs)

    crud.ecrire("missions", mis)
    crud.ecrire("carburant", fuel)
    crud.ecrire("maintenance", mnt)

    pannes = mnt[mnt.type_intervention == "Panne"]
    print(f"\n✅ missions.csv     : {len(mis):>7,} "
          f"({(mis.statut == 'Approved').sum():,} approuvées)")
    print(f"✅ carburant.csv    : {len(fuel):>7,} pleins "
          f"({fuel._anomalie_reelle.sum():,} anomalies simulées)")
    print(f"✅ maintenance.csv  : {len(mnt):>7,} interventions "
          f"dont {len(pannes):,} pannes")
    if len(mis):
        km = mis.loc[mis.statut == "Approved", "distance_km"].sum()
        print(f"\n   Km parcourus : {km:,.0f} — soit "
              f"{km / max(1, len(veh)) / ANNEES_HISTORIQUE:,.0f} "
              f"km/véhicule/an")
        print(f"   Carburant    : {fuel.montant_fcfa.sum() / 1e6:,.1f} M FCFA")
        print(f"   Maintenance  : {mnt.cout_fcfa.sum() / 1e6:,.1f} M FCFA")
    if len(pannes) < 100:
        print("\n⚠️  Peu de pannes générées : augmentez ANNEES_HISTORIQUE "
              "en tête de ce fichier pour un apprentissage plus fiable.")

    print("\n🎯 Étapes suivantes :")
    print("   python src/models/features_maintenance.py")
    print("   python src/models/train_panne.py")


if __name__ == "__main__":
    main()
