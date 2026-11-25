"""
Segmentação de municípios (K-Means) pelo perfil de perda e de chuva — responde à pergunta 2:
quais municípios têm perda RECORRENTE e precisariam de políticas permanentes de convivência com a seca,
em vez de depender todo ano de um benefício emergencial?
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from src import config

FEATURES_SEGMENTO = ["freq_acionamento", "chuva_normal_mm", "cv_chuva", "freq_estacao_seca"]
ROTULOS = ["Perda estrutural", "Perda frequente", "Perda ocasional", "Baixo risco",
           "Risco muito baixo", "Risco mínimo"]
LIMIAR_RECORRENTE = 0.5  # acionou em pelo menos metade das safras


def perfil_municipios(painel: pd.DataFrame, chuva_safra: pd.DataFrame) -> pd.DataFrame:
    """
    Uma linha por município. `chuva_safra` = atributos de chuva com corte em junho (estação inteira),
    uma linha por município e safra (colunas codigo_siafi, safra, chuva_total_mm, chuva_pct_normal).
    """
    p = painel.groupby(["codigo_siafi", "codigo_ibge", "municipio", "uf", "latitude", "longitude"], as_index=False).agg(
        safras_observadas=("acionou", "size"), safras_acionadas=("acionou", "sum"),
        freq_acionamento=("acionou", "mean"), valor_total_pago=("valor_pago", "sum"),
        beneficiarios_medio=("beneficiarios", lambda s: s[s > 0].mean() if (s > 0).any() else 0.0),
    )
    c = chuva_safra.groupby("codigo_siafi").agg(
        chuva_normal_mm=("chuva_total_mm", "mean"),
        cv_chuva=("chuva_total_mm", lambda s: s.std() / s.mean() if s.mean() > 0 else np.nan),
        freq_estacao_seca=("chuva_pct_normal", lambda s: (s < 70).mean()),
    ).reset_index()
    perfil = p.merge(c, on="codigo_siafi", how="inner")
    perfil["recorrente"] = perfil["freq_acionamento"] >= LIMIAR_RECORRENTE
    return perfil


def escolher_k(X: np.ndarray, ks=range(2, 7)) -> pd.DataFrame:
    linhas = []
    for k in ks:
        if k >= len(X):
            break
        km = KMeans(n_clusters=k, n_init=20, random_state=config.RANDOM_STATE).fit(X)
        linhas.append({"k": k, "inercia": km.inertia_, "silhueta": silhouette_score(X, km.labels_)})
    return pd.DataFrame(linhas)


def segmentar(perfil: pd.DataFrame, k: int = config.N_CLUSTERS):
    X = StandardScaler().fit_transform(perfil[FEATURES_SEGMENTO].fillna(perfil[FEATURES_SEGMENTO].median()))
    k = min(k, len(perfil) - 1)
    km = KMeans(n_clusters=k, n_init=20, random_state=config.RANDOM_STATE).fit(X)
    perfil = perfil.copy()
    perfil["cluster"] = km.labels_
    # rótulo pela frequência média de acionamento (maior -> "Perda estrutural")
    ordem = perfil.groupby("cluster")["freq_acionamento"].mean().sort_values(ascending=False).index
    rotulo = {c: ROTULOS[i] for i, c in enumerate(ordem)}
    perfil["segmento"] = perfil["cluster"].map(rotulo)
    perfil["ordem_segmento"] = perfil["cluster"].map({c: i for i, c in enumerate(ordem)})
    resumo = perfil.groupby(["ordem_segmento", "segmento"], as_index=False).agg(
        municipios=("codigo_siafi", "size"), freq_acionamento=("freq_acionamento", "mean"),
        chuva_normal_mm=("chuva_normal_mm", "mean"), cv_chuva=("cv_chuva", "mean"),
        freq_estacao_seca=("freq_estacao_seca", "mean"), valor_total_pago=("valor_total_pago", "sum"),
        beneficiarios_medio=("beneficiarios_medio", "mean"),
    ).sort_values("ordem_segmento")
    resumo["pct_valor_pago"] = 100 * resumo["valor_total_pago"] / resumo["valor_total_pago"].sum()
    silhuetas = escolher_k(X)
    return perfil, resumo.drop(columns="ordem_segmento"), silhuetas
