"""Validation de la cohérence des données synthétiques générées."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from config import DATA_RAW

pd.set_option("display.width", 120)

veh = pd.read_csv(DATA_RAW / "vehicules.csv")
ch = pd.read_csv(DATA_RAW / "chauffeurs.csv")
mis = pd.read_csv(DATA_RAW / "missions.csv", parse_dates=["date_depart"])
fuel = pd.read_csv(DATA_RAW / "carburant.csv", parse_dates=["date"])
mnt = pd.read_csv(DATA_RAW / "maintenance.csv", parse_dates=["date"])

print("═" * 60)
print("A. RÉPARTITION DU PARC")
print("═" * 60)
print(veh.groupby("localite").size().to_string())
print()
print(veh.groupby("type_vehicule").size().to_string())
print(f"\nÂge moyen du parc (2026): {2026 - veh.annee_mise_en_service.mean():.1f} ans")

print("\n" + "═" * 60)
print("B. VÉRIFICATION DES RELATIONS CAUSALES")
print("═" * 60)

# 1. Consommation vs part de piste
fuel_m = fuel.merge(mis[["mission_id", "distance_km", "part_piste"]], on="mission_id")
fuel_m["conso_100"] = fuel_m.litres / fuel_m.distance_km * 100
fuel_m["tranche_piste"] = pd.cut(fuel_m.part_piste, [0, 0.25, 0.5, 0.75, 1.0])
print("\n1) Conso moyenne (L/100km) par part de piste (doit croître):")
print(fuel_m.groupby("tranche_piste", observed=True).conso_100.mean().round(2).to_string())

# 2. Consommation vs agressivité chauffeur (sur conso NORMALISÉE par véhicule)
fuel_c = fuel_m.merge(ch[["chauffeur_id", "_aggressivite_latente"]], on="chauffeur_id")
fuel_c = fuel_c.merge(veh[["vehicule_id", "conso_nominale_l_100km"]], on="vehicule_id")
fuel_c["surconso"] = fuel_c.conso_100 / fuel_c.conso_nominale_l_100km
corr = fuel_c._aggressivite_latente.corr(fuel_c.surconso)
print(f"\n2) Corrélation agressivité chauffeur <-> surconsommation : {corr:.3f} (attendu > 0.15)")

# 3. Taux de panne vs âge du véhicule
pannes = mnt[mnt.type_intervention == "Panne"].groupby("vehicule_id").size()
veh2 = veh.set_index("vehicule_id")
veh2["n_pannes"] = pannes
veh2["n_pannes"] = veh2.n_pannes.fillna(0)
veh2["age"] = 2026 - veh2.annee_mise_en_service
veh2["tranche_age"] = pd.cut(veh2.age, [0, 4, 8, 12, 20])
print("\n3) Nb moyen de pannes (3 ans) par tranche d'âge (doit croître):")
print(veh2.groupby("tranche_age", observed=True).n_pannes.mean().round(2).to_string())

# 4. Pannes par localité (Zone Sud = plus de piste = plus de pannes/km)
km_loc = mis.merge(veh[["vehicule_id", "localite"]], on="vehicule_id") \
            .groupby("localite").distance_km.sum()
pannes_loc = mnt[mnt.type_intervention == "Panne"] \
    .merge(veh[["vehicule_id", "localite"]], on="vehicule_id") \
    .groupby("localite").size()
print("\n4) Pannes pour 100 000 km par localité (Zone Sud doit dominer):")
print((pannes_loc / km_loc * 100_000).round(2).to_string())

print("\n" + "═" * 60)
print("C. INDICATEURS ÉCONOMIQUES GLOBAUX (plausibilité)")
print("═" * 60)
print(f"Km total parcourus (3 ans)   : {mis.distance_km.sum():>15,.0f} km")
print(f"Km moyen / véhicule / an     : {mis.distance_km.sum()/141/3:>15,.0f} km")
print(f"Carburant total              : {fuel.montant_fcfa.sum():>15,.0f} FCFA")
print(f"Maintenance totale           : {mnt.cout_fcfa.sum():>15,.0f} FCFA")
print(f"Coût maintenance / véhicule / an : {mnt.cout_fcfa.sum()/141/3:>11,.0f} FCFA")
print(f"Taux d'anomalies carburant   : {fuel._anomalie_reelle.mean()*100:>14.2f} %")
