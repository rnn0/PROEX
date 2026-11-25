"""Carrega (uma vez) os artefatos gerados pelo pipeline: modelo, tabelas e respostas."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache

import joblib
import pandas as pd

from src import config


@dataclass
class Artefatos:
    modelo: object
    features: list[str]
    metadata: dict
    perfil: pd.DataFrame
    historico: pd.DataFrame
    previsao: pd.DataFrame | None
    respostas: dict
    segmentos: pd.DataFrame


@lru_cache(maxsize=1)
def carregar() -> Artefatos:
    arq_modelo = config.MODELS_DIR / "modelo_risco.joblib"
    if not arq_modelo.exists():
        raise FileNotFoundError(arq_modelo)
    pacote = joblib.load(arq_modelo)
    prev = config.PROCESSED_DIR / "previsao_safra_atual.parquet"
    return Artefatos(
        modelo=pacote["modelo"],
        features=pacote["features"],
        metadata=json.loads((config.MODELS_DIR / "metadata.json").read_text()),
        perfil=pd.read_parquet(config.PROCESSED_DIR / "perfil_municipios.parquet"),
        historico=pd.read_parquet(config.PROCESSED_DIR / "historico_municipio_safra.parquet"),
        previsao=pd.read_parquet(prev) if prev.exists() else None,
        respostas=json.loads((config.REPORTS_DIR / "respostas.json").read_text()),
        segmentos=pd.read_csv(config.REPORTS_DIR / "segmentos.csv"),
    )
