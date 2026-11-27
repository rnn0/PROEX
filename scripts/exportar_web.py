"""
Exporta os resultados do pipeline para o dashboard estático em web/ (hospedado na Vercel).

    python scripts/exportar_web.py            # lê de demo/ (ou da saída do pipeline) e escreve web/dados/

O dashboard estático não roda Python: o simulador usa uma grade de previsões já calculadas pelo modelo.
"""
from __future__ import annotations

import json
import shutil
import sys
from itertools import product
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from src import config  # noqa: E402
from src.features.build import DESCRICAO_FEATURES  # noqa: E402

WEB = RAIZ / "web"
DADOS = WEB / "dados"


def _json(nome: str, obj) -> None:
    (DADOS / nome).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


def _r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


def main() -> None:
    DADOS.mkdir(parents=True, exist_ok=True)
    proc, rep, mod = config.PROCESSED_DIR, config.REPORTS_DIR, config.MODELS_DIR
    hist = pd.read_parquet(proc / "historico_municipio_safra.parquet")
    perfil = pd.read_parquet(proc / "perfil_municipios.parquet")
    prev_arq = proc / "previsao_safra_atual.parquet"
    prev = pd.read_parquet(prev_arq) if prev_arq.exists() else None
    meta = json.loads((mod / "metadata.json").read_text())
    respostas = json.loads((rep / "respostas.json").read_text())

    # municípios (uma linha cada) com histórico safra a safra em arrays compactos
    safras = sorted(hist["safra"].unique().tolist())
    h = hist.set_index(["codigo_siafi", "safra"])
    prev_por = prev.set_index("codigo_siafi") if prev is not None else None
    municipios = []
    for _, m in perfil.sort_values(["uf", "municipio"]).iterrows():
        sid = m["codigo_siafi"]
        linhas = [h.loc[(sid, s)] if (sid, s) in h.index else None for s in safras]
        p = prev_por.loc[sid] if prev_por is not None and sid in prev_por.index else None
        municipios.append({
            "id": int(m["codigo_ibge"]), "nome": m["municipio"], "uf": m["uf"],
            "lat": _r(m["latitude"], 4), "lon": _r(m["longitude"], 4),
            "seg": m["segmento"], "freq": _r(m["freq_acionamento"]),
            "acion": int(m["safras_acionadas"]), "obs": int(m["safras_observadas"]),
            "valor": round(float(m["valor_total_pago"])), "chuvaNormal": _r(m["chuva_normal_mm"], 0),
            "prob": _r(p["prob_acionar"]) if p is not None else None,
            "chuvaAtual": _r(p["chuva_pct_normal"], 0) if p is not None else None,
            "veranicoAtual": int(p["max_dias_secos_seguidos"]) if p is not None else None,
            "hAcion": [None if x is None else int(x["acionou"]) for x in linhas],
            "hChuva": [None if x is None else _r(x["chuva_pct_normal"], 0) for x in linhas],
            "hProb": [None if x is None else _r(x["prob_fora_da_amostra"]) for x in linhas],
        })

    por_safra = hist.groupby("safra").agg(pct=("acionou", "mean"), valor=("valor_pago", "sum"),
                                          chuva=("chuva_pct_normal", "median")).reset_index()
    resumo = {
        "versao": meta["versao"], "modelo": meta["modelo"], "mesCorte": meta["mes_corte"],
        "safraAtual": meta.get("safra_atual"), "safras": safras,
        "perguntas": [config.PERGUNTA_1, config.PERGUNTA_2],
        "porSafra": [{"safra": int(r.safra), "pct": _r(r.pct), "valor": round(float(r.valor)), "chuva": _r(r.chuva, 1)}
                     for r in por_safra.itertuples()],
        "dados": json.loads((rep / "relatorio_dados.json").read_text()),
        "respostas": respostas,
    }

    def tabela(nome):
        return json.loads(pd.read_csv(rep / nome).to_json(orient="records", force_ascii=False))

    imp = pd.read_csv(rep / "importancia_atributos.csv")
    imp["descricao"] = imp["feature"].map(DESCRICAO_FEATURES)
    _json("resumo.json", resumo)
    _json("municipios.json", municipios)
    _json("antecedencia.json", tabela("antecedencia.csv"))
    _json("comparacao.json", tabela("comparacao_modelos.csv"))
    _json("por_safra_metricas.json", tabela("metricas_por_safra.csv"))
    _json("segmentos.json", tabela("segmentos.csv"))
    _json("importancia.json", json.loads(imp.to_json(orient="records", force_ascii=False)))

    # simulador: grade de previsões do modelo de produção
    pacote = joblib.load(mod / "modelo_risco.joblib")
    modelo, feats = pacote["modelo"], pacote["features"]
    a, b = np.polyfit(hist["chuva_pct_normal"].clip(0, 250), hist["dias_com_chuva"], 1)  # dias ~ chuva
    lat, lon = float(perfil["latitude"].median()), float(perfil["longitude"].median())
    normal = float(perfil["chuva_normal_mm"].median())
    pcts, veranicos, hists = list(range(20, 181, 10)), list(range(0, 101, 10)), [i / 8 for i in range(9)]
    linhas = [{
        "chuva_total_mm": normal * pc / 100, "chuva_pct_normal": pc, "chuva_anomalia_z": (pc - 100) / 25,
        "dias_com_chuva": a * pc + b, "max_dias_secos_seguidos": v, "chuva_trimestre_pct_normal": pc,
        "chuva_safra_anterior_pct_normal": 100.0, "historico_acionamento": hh, "latitude": lat, "longitude": lon,
    } for pc, v, hh in product(pcts, veranicos, hists)]
    probs = modelo.predict_proba(pd.DataFrame(linhas)[feats])[:, 1]
    _json("simulador.json", {"pct": pcts, "veranico": veranicos, "hist": hists,
                             "prob": [round(float(p), 3) for p in probs]})

    js = Path(__import__("plotly").__file__).parent / "package_data" / "plotly.min.js"
    shutil.copy(js, WEB / "plotly.min.js")
    print(f"web/dados atualizado: {len(municipios)} municípios, safras {safras[0]}-{safras[-1]}")


if __name__ == "__main__":
    main()
