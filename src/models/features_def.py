"""
Définition des variables du modèle de maintenance prédictive.

Module volontairement SANS dépendance lourde (pas de xgboost/sklearn) :
il est importé à la fois par l'entraînement (train_panne.py) et par
l'application (dashboard/app.py), qui n'a pas besoin des bibliothèques
d'entraînement pour consulter les prédictions.
"""

FEATURES_NUM = [
    "age_annees", "km_total", "km_90j", "km_30j", "n_missions_90j",
    "piste_moy_90j", "charge_moy_90j", "surconso_90j", "surconso_30j",
    "tendance_surconso", "km_piste_90j", "km_piste_cumules",
    "jours_depuis_maint", "km_depuis_maint", "n_pannes_12m",
]

FEATURES_CAT = ["type_vehicule", "localite", "marque"]

TARGET = "panne_30j"
