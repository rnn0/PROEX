"""
Engenharia de atributos: chuva da estação (out/Y-1 até o mês de corte em Y) por célula e safra,
mais o histórico de acionamento do município (somente safras anteriores, sem vazamento).

Variar o mês de corte (jan..jun) responde à pergunta 1: com quanta antecedência dá para prever.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config
from src.data.download import celula_grade

FEATURES_CHUVA = [
    "chuva_total_mm", "chuva_pct_normal", "chuva_anomalia_z", "dias_com_chuva",
    "max_dias_secos_seguidos", "chuva_trimestre_pct_normal", "chuva_safra_anterior_pct_normal",
]
FEATURES_MUNICIPIO = ["historico_acionamento", "latitude", "longitude"]
FEATURES = FEATURES_CHUVA + FEATURES_MUNICIPIO

DESCRICAO_FEATURES = {
    "chuva_total_mm": "Chuva acumulada na estação (out até o mês de corte)",
    "chuva_pct_normal": "Chuva da estação em % da média histórica do local",
    "chuva_anomalia_z": "Desvio da chuva da estação em desvios-padrão",
    "dias_com_chuva": "Dias com chuva >= 1 mm na estação",
    "max_dias_secos_seguidos": "Maior veranico (dias secos seguidos) de dez até o corte",
    "chuva_trimestre_pct_normal": "Chuva dos 3 meses antes do corte em % da média",
    "chuva_safra_anterior_pct_normal": "Chuva da estação anterior (out-jun) em % da média",
    "historico_acionamento": "Fração das safras anteriores em que o município recebeu o benefício",
    "latitude": "Latitude do município",
    "longitude": "Longitude do município",
}


def _max_seguidos(secos: np.ndarray) -> int:
    melhor = atual = 0
    for s in secos:
        atual = atual + 1 if s else 0
        melhor = max(melhor, atual)
    return melhor


def _janela(safra: int, mes_corte: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    inicio = pd.Timestamp(safra - 1, config.MES_INICIO_ESTACAO, 1)
    fim = pd.Timestamp(config.ano_do_corte(safra, mes_corte), mes_corte, 1) + pd.offsets.MonthEnd(0)
    return inicio, fim


def features_chuva_por_celula(chuva: pd.DataFrame, safras: list[int], mes_corte: int) -> pd.DataFrame:
    """Atributos de chuva por célula (lat, lon) e safra, para um mês de corte."""
    linhas = []
    for (lat, lon), serie in chuva.groupby(["lat", "lon"]):
        s = serie.set_index("data")["chuva_mm"].sort_index()
        for safra in safras:
            ini, fim = _janela(safra, mes_corte)
            jan = s.loc[ini:fim]
            # exige ao menos 90% dos dias da janela
            if jan.notna().sum() < 0.9 * ((fim - ini).days + 1):
                continue
            tri_ini = fim - pd.offsets.MonthBegin(3)
            veranico = s.loc[pd.Timestamp(safra - 1, 12, 1):fim]  # a lavoura já está no campo
            ant_ini, ant_fim = _janela(safra - 1, 6)
            ant = s.loc[ant_ini:ant_fim]
            linhas.append({
                "lat": lat, "lon": lon, "safra": safra,
                "chuva_total_mm": float(jan.sum()),
                "dias_com_chuva": int((jan >= config.DIA_SECO_MM).sum()),
                "max_dias_secos_seguidos": _max_seguidos((veranico.fillna(0) < config.DIA_SECO_MM).to_numpy()),
                "chuva_trimestre_mm": float(s.loc[tri_ini:fim].sum()),
                "chuva_safra_anterior_mm": float(ant.sum()) if ant.notna().sum() > 200 else np.nan,
            })
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    # normal climatológica do próprio local (média de todas as safras disponíveis)
    g = df.groupby(["lat", "lon"])
    media, desvio = g["chuva_total_mm"].transform("mean"), g["chuva_total_mm"].transform("std")
    df["chuva_pct_normal"] = 100 * df["chuva_total_mm"] / media.replace(0, np.nan)
    df["chuva_anomalia_z"] = (df["chuva_total_mm"] - media) / desvio.replace(0, np.nan)
    df["chuva_trimestre_pct_normal"] = 100 * df["chuva_trimestre_mm"] / g["chuva_trimestre_mm"].transform("mean").replace(0, np.nan)
    df["chuva_safra_anterior_pct_normal"] = (
        100 * df["chuva_safra_anterior_mm"] / g["chuva_safra_anterior_mm"].transform("mean").replace(0, np.nan)
    )
    return df


def montar_base(painel: pd.DataFrame, chuva: pd.DataFrame, mes_corte: int,
                safras_extra: list[int] | None = None) -> pd.DataFrame:
    """
    Junta painel (alvo) + chuva + histórico para um mês de corte.
    `safras_extra` inclui safras sem alvo conhecido (ex.: a safra atual, para previsão).
    """
    safras = sorted(set(painel["safra"]) | set(safras_extra or []))
    feats = features_chuva_por_celula(chuva, safras, mes_corte)

    base = painel.copy()
    if safras_extra:
        mun = painel.drop_duplicates("codigo_siafi")[
            ["codigo_siafi", "codigo_ibge", "municipio", "codigo_uf", "uf", "latitude", "longitude"]]
        extra = pd.concat([mun.assign(safra=s) for s in safras_extra if s not in set(painel["safra"])],
                          ignore_index=True) if safras_extra else pd.DataFrame()
        if not extra.empty:
            extra["acionou"] = np.nan
            base = pd.concat([base, extra], ignore_index=True)

    base = adicionar_historico(base)
    cel = [celula_grade(la, lo) for la, lo in zip(base["latitude"], base["longitude"])]
    base["lat"], base["lon"] = [c[0] for c in cel], [c[1] for c in cel]
    base = base.merge(feats, on=["lat", "lon", "safra"], how="inner")
    base["mes_corte"] = mes_corte
    return base


def adicionar_historico(base: pd.DataFrame) -> pd.DataFrame:
    """Fração das safras ANTERIORES (com alvo conhecido) em que o município recebeu o benefício."""
    base = base.sort_values(["codigo_siafi", "safra"]).copy()
    conhecido = base["acionou"].notna()
    soma = base["acionou"].fillna(0).groupby(base["codigo_siafi"]).cumsum() - base["acionou"].fillna(0)
    n = conhecido.astype(int).groupby(base["codigo_siafi"]).cumsum() - conhecido.astype(int)
    base["historico_acionamento"] = (soma / n.replace(0, np.nan)).astype(float)
    return base
