"""
Étape 2.2 — Modèle de prédiction de panne à 30 jours.

- Split TEMPOREL (train: oct 2023 → juin 2025 ; test: juil 2025 → mai 2026)
- Baseline régression logistique vs XGBoost
- Métriques: ROC-AUC, PR-AUC + métrique opérationnelle precision@top-15
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier
import joblib

from config import DATA_PROCESSED, MODELS_DIR
from features_def import FEATURES_NUM, FEATURES_CAT, TARGET

DATE_SPLIT = "2025-07-01"


def precision_at_topk(df_test, scores, k=15):
    """Sur chaque snapshot hebdo: si on inspecte les k véhicules les plus
    à risque, quelle part a réellement une panne sous 30j ? Et quelle part
    des pannes réelles capture-t-on (rappel) ?"""
    d = df_test.copy()
    d["score"] = scores
    prec, rap = [], []
    for _, g in d.groupby("date_snapshot"):
        top = g.nlargest(k, "score")
        prec.append(top[TARGET].mean())
        tot = g[TARGET].sum()
        if tot > 0:
            rap.append(top[TARGET].sum() / tot)
    return np.mean(prec), np.mean(rap)


def main():
    df = pd.read_parquet(DATA_PROCESSED / "features_maintenance.parquet")
    train = df[df.date_snapshot < DATE_SPLIT]
    test = df[df.date_snapshot >= DATE_SPLIT]
    print(f"Train: {len(train):,} snapshots ({train[TARGET].mean()*100:.1f}% positifs)")
    print(f"Test : {len(test):,} snapshots ({test[TARGET].mean()*100:.1f}% positifs)")

    X_tr, y_tr = train[FEATURES_NUM + FEATURES_CAT], train[TARGET]
    X_te, y_te = test[FEATURES_NUM + FEATURES_CAT], test[TARGET]

    prep = ColumnTransformer([
        ("num", StandardScaler(), FEATURES_NUM),
        ("cat", OneHotEncoder(handle_unknown="ignore"), FEATURES_CAT),
    ])

    modeles = {
        "Régression logistique (baseline)": Pipeline([
            ("prep", prep),
            ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
        ]),
        "XGBoost (régularisé anti-drift)": Pipeline([
            ("prep", prep),
            ("clf", XGBClassifier(
                n_estimators=150, max_depth=3, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.7,
                min_child_weight=25, reg_lambda=10, gamma=0.5,
                scale_pos_weight=(y_tr == 0).sum() / (y_tr == 1).sum(),
                eval_metric="aucpr", random_state=42,
            )),
        ]),
    }

    resultats, best_name, best_ap, best_model, best_scores = {}, None, -1, None, None
    for nom, pipe in modeles.items():
        pipe.fit(X_tr, y_tr)
        scores = pipe.predict_proba(X_te)[:, 1]
        auc = roc_auc_score(y_te, scores)
        ap = average_precision_score(y_te, scores)
        p15, r15 = precision_at_topk(test, scores, k=15)
        resultats[nom] = (auc, ap, p15, r15)
        if ap > best_ap:
            best_name, best_ap, best_model, best_scores = nom, ap, pipe, scores

    print("\n── Résultats (test temporel juil 2025 → mai 2026) ─────────────")
    print(f"{'Modèle':<35} {'ROC-AUC':>8} {'PR-AUC':>8} {'Prec@15':>8} {'Rappel@15':>10}")
    base_rate = y_te.mean()
    print(f"{'(hasard)':<35} {'0.500':>8} {base_rate:>8.3f} {base_rate:>8.3f} {'—':>10}")
    for nom, (auc, ap, p15, r15) in resultats.items():
        print(f"{nom:<35} {auc:>8.3f} {ap:>8.3f} {p15:>8.3f} {r15:>10.3f}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(best_model, MODELS_DIR / "modele_panne_30j.joblib")
    np.save(MODELS_DIR / "scores_test.npy", best_scores)
    test.to_parquet(MODELS_DIR / "test_set.parquet", index=False)
    print(f"\nMeilleur modèle sauvegardé : {best_name} → modele_panne_30j.joblib")

    # ── Calibration de Platt (temporelle) ─────────────────────────────
    # Le class_weight="balanced" fausse les probabilités. On réajuste :
    # fit sur début du train, calibration sur fin du train (jamais le test).
    DATE_CALIB = "2025-01-01"
    tr_early = train[train.date_snapshot < DATE_CALIB]
    tr_late = train[train.date_snapshot >= DATE_CALIB]
    from sklearn.base import clone
    m_early = clone(best_model).fit(
        tr_early[FEATURES_NUM + FEATURES_CAT], tr_early[TARGET]
    )
    s_late = m_early.predict_proba(tr_late[FEATURES_NUM + FEATURES_CAT])[:, 1]
    calib = LogisticRegression().fit(s_late.reshape(-1, 1), tr_late[TARGET])
    joblib.dump(calib, MODELS_DIR / "calibrateur_panne.joblib")

    p_cal = calib.predict_proba(best_scores.reshape(-1, 1))[:, 1]
    print("\n── Calibration (probabilités vs réalité, sur le test) ─────────")
    d = pd.DataFrame({"brut": best_scores, "calibre": p_cal, "reel": y_te.values})
    d["decile"] = pd.qcut(d.calibre, 5, duplicates="drop")
    tab = d.groupby("decile", observed=True).agg(
        proba_brute=("brut", "mean"),
        proba_calibree=("calibre", "mean"),
        taux_reel=("reel", "mean"),
    ).round(3)
    print(tab.to_string())
    print("(proba_calibree doit être proche de taux_reel)")


if __name__ == "__main__":
    main()
