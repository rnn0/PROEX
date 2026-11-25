"""Leitura das séries diárias de chuva (NASA POWER) baixadas por célula da grade."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from src import config


def carregar_chuva_diaria(raw_dir: Path | None = None) -> pd.DataFrame:
    """Devolve um DataFrame longo: lat, lon, data, chuva_mm (valores ausentes -999 viram NaN)."""
    raw_dir = raw_dir or config.CHUVA_RAW_DIR
    tabelas = []
    for arq in sorted(raw_dir.glob("power_*.json")):
        meta = json.loads(arq.read_text())
        serie = pd.Series(meta["PRECTOTCORR"], dtype=float)
        df = pd.DataFrame({
            "lat": meta["lat"], "lon": meta["lon"],
            "data": pd.to_datetime(serie.index, format="%Y%m%d"),
            "chuva_mm": serie.values,
        })
        tabelas.append(df)
    if not tabelas:
        raise FileNotFoundError(f"Nenhuma série de chuva em {raw_dir}")
    chuva = pd.concat(tabelas, ignore_index=True)
    chuva.loc[chuva["chuva_mm"] < 0, "chuva_mm"] = np.nan
    return chuva
