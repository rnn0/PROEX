"""
Modelos de classificação: o município vai precisar do Garantia-Safra nesta safra?

Validação "deixa uma safra de fora" (leave-one-season-out): cada safra é prevista por um modelo que
não viu nenhum dado dela. Isso é essencial porque a seca atinge muitos municípios no mesmo ano;
um split aleatório misturaria o mesmo ano em treino e teste e inflaria as métricas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src import config
from src.features.build import FEATURES, FEATURES_CHUVA


def modelos() -> dict:
    return {
        "Regressão logística": make_pipeline(
            SimpleImputer(strategy="median"), StandardScaler(),
            LogisticRegression(max_iter=2000, class_weight="balanced")),
        "Random Forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(n_estimators=200, min_samples_leaf=5, class_weight="balanced_subsample",
                                   n_jobs=1, random_state=config.RANDOM_STATE)),
        "Gradient Boosting": HistGradientBoostingClassifier(
            max_iter=150, learning_rate=0.08, max_leaf_nodes=31, l2_regularization=1.0,
            class_weight="balanced", random_state=config.RANDOM_STATE),
    }


def metricas(y: np.ndarray, p: np.ndarray, limiar: float = 0.5) -> dict:
    y = np.asarray(y).astype(int)
    if len(np.unique(y)) < 2:
        return {"roc_auc": np.nan, "pr_auc": np.nan, "brier": brier_score_loss(y, p), "f1": np.nan}
    return {
        "roc_auc": roc_auc_score(y, p),
        "pr_auc": average_precision_score(y, p),
        "brier": brier_score_loss(y, p),
        "f1": f1_score(y, (p >= limiar).astype(int), zero_division=0),
    }


def validar_por_safra(base: pd.DataFrame, modelo, features: list[str],
                      importancia: bool = False) -> tuple[pd.Series, pd.DataFrame | None]:
    """Previsões fora da amostra (cada safra prevista sem vê-la) e, opcionalmente, importância por permutação."""
    oof = pd.Series(np.nan, index=base.index)
    imps = []
    for safra in sorted(base["safra"].unique()):
        teste = base["safra"] == safra
        treino = ~teste
        if base.loc[treino, "acionou"].nunique() < 2:
            continue
        m = clone(modelo).fit(base.loc[treino, features], base.loc[treino, "acionou"].astype(int))
        oof[teste] = m.predict_proba(base.loc[teste, features])[:, 1]
        if importancia and base.loc[teste, "acionou"].nunique() == 2:
            r = permutation_importance(m, base.loc[teste, features], base.loc[teste, "acionou"].astype(int),
                                       scoring="average_precision", n_repeats=3,
                                       random_state=config.RANDOM_STATE, n_jobs=1)
            imps.append(r.importances_mean)
    imp = None
    if imps:
        imp = pd.DataFrame({"feature": features, "importancia": np.mean(imps, axis=0)}) \
            .sort_values("importancia", ascending=False).reset_index(drop=True)
    return oof, imp


def baseline_historico(base: pd.DataFrame) -> pd.Series:
    """Baseline: probabilidade = frequência com que o município acionou nas safras anteriores."""
    return base["historico_acionamento"].fillna(base["acionou"].mean())


def comparar_modelos(base: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Compara baselines e modelos (com e sem histórico do município) na validação por safra."""
    linhas, previsoes = [], {}
    y = base["acionou"].astype(int)

    prev = pd.Series(y.mean(), index=base.index)
    linhas.append({"modelo": "Taxa média (baseline)", "atributos": "-", **metricas(y, prev)})
    prev = baseline_historico(base)
    linhas.append({"modelo": "Histórico do município (baseline)", "atributos": "histórico", **metricas(y, prev)})
    previsoes["Histórico do município (baseline)"] = prev

    for nome, modelo in modelos().items():
        for rotulo, feats in (("só chuva", FEATURES_CHUVA), ("chuva + histórico", FEATURES)):
            oof, _ = validar_por_safra(base, modelo, feats)
            ok = oof.notna()
            linhas.append({"modelo": nome, "atributos": rotulo, **metricas(y[ok], oof[ok])})
            previsoes[f"{nome} | {rotulo}"] = oof
    return pd.DataFrame(linhas), previsoes


def metricas_por_safra(base: pd.DataFrame, oof: pd.Series) -> pd.DataFrame:
    linhas = []
    for safra, g in base.assign(p=oof).dropna(subset=["p"]).groupby("safra"):
        linhas.append({"safra": int(safra), "municipios": len(g), "acionaram": int(g["acionou"].sum()),
                       "previstos_risco_alto": int((g["p"] >= 0.5).sum()),
                       **metricas(g["acionou"], g["p"])})
    return pd.DataFrame(linhas)
