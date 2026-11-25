"""
Gera dados SINTÉTICOS no mesmo formato das fontes reais (municípios, chuva NASA POWER e folhas
do Garantia-Safra). Serve só para validar o fluxo (testes, CI e ambientes sem internet).
Os resultados com esses dados NÃO dizem nada sobre o mundo real.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.data.download import celula_grade

UFS_SEMIARIDO = {21: "MA", 22: "PI", 23: "CE", 24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG"}
COLUNAS_PORTAL = ["MÊS REFERÊNCIA", "UF", "CÓDIGO MUNICÍPIO SIAFI", "NOME MUNICÍPIO",
                  "NIS FAVORECIDO", "NOME FAVORECIDO", "VALOR PARCELA"]


def gerar(n_municipios: int = int(os.environ.get("PROEX_SYNTH_N", 180)), seed: int = config.RANDOM_STATE, raw_dir: Path | None = None) -> None:
    rng = np.random.default_rng(seed)
    raw_dir = raw_dir or config.RAW_DIR
    gs_dir, chuva_dir = raw_dir / "garantia_safra", raw_dir / "chuva"
    gs_dir.mkdir(parents=True, exist_ok=True)
    chuva_dir.mkdir(parents=True, exist_ok=True)

    # 1) municípios: interior do Nordeste (mais seco a oeste/centro), mais alguns no litoral (úmidos)
    lat = rng.uniform(-16.0, -3.5, n_municipios)
    lon = rng.uniform(-44.5, -35.5, n_municipios)
    ufs = list(UFS_SEMIARIDO)
    mun = pd.DataFrame({
        "codigo_ibge": 2900000 + np.arange(n_municipios),
        "nome": [f"Município Sintético {i:03d}" for i in range(n_municipios)],
        "latitude": lat.round(4), "longitude": lon.round(4), "capital": 0,
        "codigo_uf": rng.choice(ufs, n_municipios),
        "siafi_id": 9000 + np.arange(n_municipios),
        "ddd": 0, "fuso_horario": "America/Sao_Paulo",
    })
    mun.to_csv(raw_dir / "municipios.csv", index=False)

    # 2) chuva diária por célula da grade
    inicio = date(config.SAFRA_INICIAL - 2, config.MES_INICIO_ESTACAO, 1)
    fim = date.today() - timedelta(days=7)
    dias = pd.date_range(inicio, fim, freq="D")
    safras_todas = range(config.SAFRA_INICIAL - 1, config.SAFRA_ATUAL + 2)
    choque_ano = {s: rng.normal(0, 0.28) for s in safras_todas}  # secas/anos chuvosos regionais
    sazonal = 1 + 1.6 * np.cos((dias.month.to_numpy() - 3) / 12 * 2 * np.pi)  # pico em março
    sazonal = np.clip(sazonal, 0.05, None)
    safra_do_dia = np.where(dias.month >= config.MES_INICIO_ESTACAO, dias.year + 1, dias.year)

    celulas = {celula_grade(a, b) for a, b in zip(mun["latitude"], mun["longitude"])}
    total_estacao: dict[tuple, dict[int, float]] = {}
    for la, lo in celulas:
        aridez = 0.6 + 0.5 * np.clip((lo + 44.5) / 9, 0, 1) * (1 - abs(la + 8) / 9)  # centro mais seco
        media_dia = 2.6 / aridez
        local = {s: np.exp(choque_ano[s] + rng.normal(0, 0.12)) for s in safras_todas}
        fator = np.vectorize(local.get)(safra_do_dia)
        prob = np.clip(0.30 * sazonal * fator, 0.01, 0.9)
        chove = rng.random(len(dias)) < prob
        mm = np.where(chove, rng.gamma(0.9, media_dia * fator / 0.9 * sazonal / 1.2), 0.0)
        serie = {d.strftime("%Y%m%d"): round(float(v), 2) for d, v in zip(dias, mm)}
        (chuva_dir / f"power_{la:+.4f}_{lo:+.4f}.json").write_text(json.dumps({
            "lat": la, "lon": lo, "inicio": dias[0].strftime("%Y%m%d"), "fim": dias[-1].strftime("%Y%m%d"),
            "PRECTOTCORR": serie}))
        s = pd.Series(mm, index=dias)
        total_estacao[(la, lo)] = {
            sf: float(s.loc[pd.Timestamp(sf - 1, 10, 1):pd.Timestamp(sf, 6, 30)].sum()) for sf in safras_todas[:-1]
        }

    # 3) folhas do Garantia-Safra: perda quando a estação fica bem abaixo da normal
    vulnerab = rng.normal(0, 0.8, n_municipios)
    n_benef = rng.integers(15, 60, n_municipios)
    folhas: dict[str, list] = {}
    for i, row in mun.iterrows():
        cel = celula_grade(row["latitude"], row["longitude"])
        tot = total_estacao[cel]
        normal = np.mean(list(tot.values()))
        for sf in range(config.SAFRA_INICIAL - 1, config.SAFRA_ATUAL):
            deficit = 1 - tot[sf] / normal
            p = 1 / (1 + np.exp(-(8 * deficit + vulnerab[i] - 0.8)))
            if rng.random() > p:
                continue
            ano_pg, mes_pg = (sf, 12) if rng.random() < 0.4 else (sf + 1, int(rng.integers(1, 4)))
            n_parcelas, valor = (5, 170.0) if sf < 2021 else (1, 1200.0 if sf >= 2023 else 850.0)
            for k in range(n_parcelas):
                m, a = mes_pg + k, ano_pg
                if m > 12:
                    m, a = m - 12, a + 1
                if date(a, m, 1) > date.today():
                    continue
                yyyymm = f"{a}{m:02d}"
                for b in range(n_benef[i]):
                    folhas.setdefault(yyyymm, []).append([
                        f"{a}{m:02d}", UFS_SEMIARIDO[row["codigo_uf"]], row["siafi_id"], row["nome"].upper(),
                        f"{row['siafi_id']:05d}{b:06d}", f"AGRICULTOR {b}", f"{valor:,.2f}".replace(",", "X")
                        .replace(".", ",").replace("X", "."),
                    ])
    for yyyymm, linhas in folhas.items():
        pd.DataFrame(linhas, columns=COLUNAS_PORTAL).to_csv(
            gs_dir / f"{yyyymm}_GarantiaSafra.csv", sep=";", index=False, encoding="latin-1")


if __name__ == "__main__":
    config.ensure_dirs()
    gerar()
    print("Dados sintéticos gerados em", config.RAW_DIR)
