"""
API REST do projeto (FastAPI).

    uvicorn api.main:app --port 8000      ->  Swagger em http://localhost:8000/docs
"""
from __future__ import annotations

import math

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from api.artifacts import Artefatos, carregar

app = FastAPI(
    title="Garantia-Safra: risco de perda de safra no Semiárido",
    description="Previsão de quais municípios vão precisar do Garantia-Safra a partir da chuva "
                "(NASA POWER) e do histórico de pagamentos (Portal da Transparência). ODS 2 e 13.",
    version="1.0.0",
)

NAO_TREINADO = "Modelo ainda não treinado. Rode `python -m src.pipeline` antes de subir a API."


def _art() -> Artefatos:
    try:
        return carregar()
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail=NAO_TREINADO) from None


def _limpar(registros: list[dict]) -> list[dict]:
    """NaN não é JSON válido: troca por None."""
    return [{k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()} for r in registros]


class EntradaPrevisao(BaseModel):
    chuva_total_mm: float = Field(..., ge=0, description="Chuva acumulada de outubro até o mês de corte")
    chuva_pct_normal: float = Field(..., ge=0, description="Chuva da estação em % da média do local")
    chuva_anomalia_z: float = Field(0.0, description="Desvio em desvios-padrão")
    dias_com_chuva: int = Field(..., ge=0)
    max_dias_secos_seguidos: int = Field(..., ge=0)
    chuva_trimestre_pct_normal: float = Field(100.0, ge=0)
    chuva_safra_anterior_pct_normal: float = Field(100.0, ge=0)
    historico_acionamento: float = Field(0.5, ge=0, le=1)
    latitude: float = Field(-8.0, ge=-35, le=6)
    longitude: float = Field(-39.0, ge=-75, le=-30)


@app.get("/health")
def health():
    try:
        meta = carregar().metadata
    except FileNotFoundError:
        return {"status": "sem_modelo", "detail": NAO_TREINADO}
    return {"status": "ok", "versao": meta["versao"], "modo_dados": meta["modo_dados"],
            "modelo": meta["modelo"], "mes_corte": meta["mes_corte"], "safra_atual": meta["safra_atual"]}


@app.get("/respostas")
def respostas():
    """Respostas às duas perguntas do projeto, calculadas pelo pipeline."""
    return _art().respostas


@app.get("/segmentos")
def segmentos():
    return _limpar(_art().segmentos.to_dict("records"))


@app.get("/municipios")
def municipios(uf: str | None = None, segmento: str | None = None, recorrente: bool | None = None):
    p = _art().perfil
    if uf:
        p = p[p["uf"] == uf.upper()]
    if segmento:
        p = p[p["segmento"].str.lower() == segmento.lower()]
    if recorrente is not None:
        p = p[p["recorrente"] == recorrente]
    cols = ["codigo_ibge", "municipio", "uf", "segmento", "freq_acionamento", "safras_acionadas",
            "safras_observadas", "valor_total_pago", "chuva_normal_mm"] + (["prob_acionar"] if "prob_acionar" in p else [])
    return _limpar(p[cols].sort_values("freq_acionamento", ascending=False).to_dict("records"))


@app.get("/municipios/{codigo_ibge}")
def municipio(codigo_ibge: int):
    art = _art()
    p = art.perfil[art.perfil["codigo_ibge"] == codigo_ibge]
    if p.empty:
        raise HTTPException(status_code=404, detail="Município fora da área do Garantia-Safra analisada.")
    hist = art.historico[art.historico["codigo_ibge"] == codigo_ibge].sort_values("safra")
    return {
        "perfil": _limpar(p.to_dict("records"))[0],
        "historico": _limpar(hist[["safra", "acionou", "beneficiarios", "valor_pago", "chuva_total_mm",
                                   "chuva_pct_normal", "max_dias_secos_seguidos", "prob_fora_da_amostra"]]
                             .to_dict("records")),
    }


@app.get("/risco/safra-atual")
def risco_safra_atual(uf: str | None = None, min_prob: float = Query(0.0, ge=0, le=1),
                      limite: int = Query(50, ge=1, le=5000)):
    """Ranking de risco para a safra em andamento (resultado oficial ainda não publicado)."""
    art = _art()
    if art.previsao is None:
        raise HTTPException(status_code=404, detail="Ainda não há chuva suficiente para prever a safra atual.")
    p = art.previsao
    if uf:
        p = p[p["uf"] == uf.upper()]
    p = p[p["prob_acionar"] >= min_prob].sort_values("prob_acionar", ascending=False).head(limite)
    return {"safra": int(art.metadata["safra_atual"]), "mes_corte": art.metadata["mes_corte"],
            "municipios": _limpar(p[["codigo_ibge", "municipio", "uf", "prob_acionar", "chuva_pct_normal",
                                     "max_dias_secos_seguidos"]].to_dict("records"))}


@app.post("/prever")
def prever(entrada: EntradaPrevisao):
    """Simulador: probabilidade de o município precisar do benefício para um cenário de chuva."""
    art = _art()
    X = pd.DataFrame([entrada.model_dump()])[art.features]
    prob = float(art.modelo.predict_proba(X)[:, 1][0])
    return {"prob_acionar": prob, "risco": "alto" if prob >= 0.5 else "moderado" if prob >= 0.25 else "baixo",
            "modelo": art.metadata["modelo"], "mes_corte": art.metadata["mes_corte"]}
