# Fleet-IA

**Système intelligent d'aide à la décision pour la gestion prédictive d'une flotte automobile — cas de World Vision Sénégal**

Mémoire de Master IA. Le système fait évoluer la gestion de flotte d'un modèle réactif (suivi de conformité via Power Apps/SharePoint) vers un modèle prédictif et prescriptif basé sur le machine learning.

## Structure du projet

```
fleet_ia/
├── data/
│   ├── raw/               # Données sources (synthétiques puis réelles)
│   └── processed/         # Features préparées pour les modèles
├── src/
│   ├── config.py          # Configuration centrale (flotte, paramètres)
│   ├── data/
│   │   ├── generate_data.py   # Générateur de données synthétiques
│   │   └── validate_data.py   # Validation de cohérence
│   ├── models/            # Modèles ML (itérations 2-4)
│   ├── optimization/      # Affectations & tournées (itération 4)
│   └── dashboard/         # Streamlit + API (itération 5)
├── notebooks/             # Explorations
├── tests/
└── docs/                  # Documentation finale
```

## Données

5 tables simulant 3 ans d'activité (2023-2026), calibrées sur le parc réel
(141 véhicules, 3 localités : Bureau National, Zone Centre, Zone Sud) :

| Table | Contenu | Volume |
|---|---|---|
| `vehicules.csv` | Référentiel du parc | 141 |
| `chauffeurs.csv` | Référentiel chauffeurs (profil de conduite latent) | 96 |
| `missions.csv` | Ordres de mission (distance, piste, charge) | ~41 500 |
| `carburant.csv` | Pleins (avec ~2,5 % d'anomalies étiquetées) | ~41 500 |
| `maintenance.csv` | Entretiens préventifs + pannes | ~1 800 |

Relations causales encodées (validées par `validate_data.py`) :
- La part de piste et la charge augmentent la consommation
- Le style de conduite du chauffeur (variable latente) impacte conso et usure
- L'âge et l'usure augmentent la probabilité de panne
- Zone Sud (70 % piste) subit plus de pannes/km que Bureau National

⚠️ Les colonnes préfixées `_` (`_aggressivite_latente`, `_anomalie_reelle`)
sont la **vérité terrain** servant uniquement à évaluer les modèles.
Elles ne doivent JAMAIS être utilisées comme features.

## Utilisation

```bash
pip install -r requirements.txt
python src/data/generate_data.py    # Génère les données
python src/data/validate_data.py    # Vérifie la cohérence
```

## État d'avancement

- [x] **Itération 1** — Structure + génération et validation des données
- [ ] Itération 2 — Module maintenance prédictive (classification + survie)
- [ ] Itération 3 — Module carburant (régression + détection d'anomalies)
- [ ] Itération 4 — Optimisation affectations + prévision de la demande
- [ ] Itération 5 — Dashboard Streamlit + API FastAPI
- [ ] Documentation finale
