"""
Pipeline completo (CRISP-DM): dados -> preparação -> modelagem -> avaliação -> artefatos para API/dashboard.

    python -m src.pipeline              # usa dados reais em data/raw (ou sintéticos se não houver)
    python -m src.pipeline --download   # baixa/atualiza as fontes públicas antes (precisa de internet)
    python -m src.pipeline --synthetic  # força dados sintéticos (testes/CI)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import time
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone

from src import config
from src.data import download, synthetic
from src.data.chuva import carregar_chuva_diaria
from src.data.garantia_safra import carregar_pagamentos_mensais, construir_painel_safras
from src.features.build import DESCRICAO_FEATURES, FEATURES, FEATURES_CHUVA, montar_base
from src.models import classifier, segment

log = logging.getLogger("pipeline")
MESES = {12: "dez", 1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun"}


def _tem_dados_reais() -> bool:
    return any(config.GS_RAW_DIR.glob("*.zip")) or any(config.GS_RAW_DIR.glob("*.csv"))


def preparar_dados(baixar: bool, sintetico: bool) -> str:
    config.ensure_dirs()
    if sintetico or config.USE_SYNTHETIC == "1":
        log.warning("Usando dados SINTÉTICOS (apenas para validar o fluxo).")
        for d in (config.GS_RAW_DIR, config.CHUVA_RAW_DIR, config.INTERIM_DIR):
            shutil.rmtree(d, ignore_errors=True)
        config.ensure_dirs()
        synthetic.gerar()
        return "sintetico"
    if baixar:
        download.baixar_tudo()
    if _tem_dados_reais():
        return "real"
    if config.USE_SYNTHETIC == "0":
        raise FileNotFoundError("Sem dados em data/raw. Rode com --download.")
    log.warning("Sem dados reais em data/raw: gerando dados SINTÉTICOS. Use --download para os reais.")
    synthetic.gerar()
    return "sintetico"


def meses_ate_pagamento(painel: pd.DataFrame, mes_corte: int) -> float:
    """Mediana de meses entre o fim do mês de corte e o início do pagamento (antecedência real)."""
    pg = painel[painel["acionou"] == 1].dropna(subset=["mes_inicio_pagamento"])
    if pg.empty:
        return float("nan")
    a = pg["mes_inicio_pagamento"].str.slice(0, 4).astype(int)
    m = pg["mes_inicio_pagamento"].str.slice(5, 7).astype(int)
    return float(np.median((a * 12 + m) - (pg["safra"].map(lambda y: config.ano_do_corte(y, mes_corte)) * 12 + mes_corte)))


def meses_ate_colheita(mes_corte: int) -> int:
    """Horizonte da previsão dentro do ciclo: meses entre o corte e o fim da colheita (junho)."""
    return (config.MES_COLHEITA - mes_corte) % 12


def experimento_antecedencia(painel, chuva) -> tuple[pd.DataFrame, dict]:
    """Pergunta 1: desempenho conforme o mês em que a previsão é feita (jan..jun)."""
    linhas, bases = [], {}
    gb = classifier.modelos()["Gradient Boosting"]
    for mes in config.MESES_CORTE:
        base = montar_base(painel, chuva, mes)
        bases[mes] = base
        y = base["acionou"].astype(int)
        for rotulo, feats in (("só chuva", FEATURES_CHUVA), ("chuva + histórico", FEATURES)):
            oof, _ = classifier.validar_por_safra(base, gb, feats)
            ok = oof.notna()
            linhas.append({"mes_corte": mes, "mes": MESES[mes], "atributos": rotulo,
                           "meses_ate_colheita": meses_ate_colheita(mes),
                           "meses_ate_pagamento": meses_ate_pagamento(painel, mes),
                           **classifier.metricas(y[ok], oof[ok])})
        log.info("Antecedência: corte em %s concluído", MESES[mes])
    return pd.DataFrame(linhas), bases


def responder_perguntas(antecedencia, comparacao, importancia, perfil, resumo_seg, previsao_atual,
                        painel) -> dict:
    ant = antecedencia[antecedencia["atributos"] == "chuva + histórico"].sort_values("meses_ate_colheita", ascending=False)
    melhor = ant["pr_auc"].max()
    suficiente = ant[ant["pr_auc"] >= 0.95 * melhor].iloc[0]
    so_chuva = antecedencia[antecedencia["atributos"] == "só chuva"].set_index("mes_corte")["roc_auc"]
    base_hist = comparacao[comparacao["modelo"] == "Histórico do município (baseline)"].iloc[0]

    rec = perfil[perfil["recorrente"]]
    estrutural = resumo_seg.iloc[0]
    atual_alto = previsao_atual[previsao_atual["prob_acionar"] >= 0.5] if previsao_atual is not None else None

    return {
        "pergunta_1": {
            "pergunta": config.PERGUNTA_1,
            "mes_corte_recomendado": MESES[int(suficiente["mes_corte"])],
            "meses_de_antecedencia": float(suficiente["meses_ate_pagamento"]),
            "meses_antes_da_colheita": int(suficiente["meses_ate_colheita"]),
            "roc_auc": float(suficiente["roc_auc"]), "pr_auc": float(suficiente["pr_auc"]),
            "pr_auc_maximo": float(melhor),
            "roc_auc_so_chuva_por_mes": {MESES[int(k)]: round(float(v), 3) for k, v in so_chuva.items()},
            "roc_auc_baseline_historico": float(base_hist["roc_auc"]),
            "principais_fatores": importancia.head(5)["feature"].map(DESCRICAO_FEATURES).tolist(),
            "taxa_acionamento": float(painel["acionou"].mean()),
        },
        "pergunta_2": {
            "pergunta": config.PERGUNTA_2,
            "municipios_analisados": int(len(perfil)),
            "municipios_recorrentes": int(len(rec)),
            "criterio_recorrente": f"recebeu o benefício em >= {int(segment.LIMIAR_RECORRENTE * 100)}% das safras",
            "pct_valor_pago_recorrentes": float(100 * rec["valor_total_pago"].sum()
                                                / max(perfil["valor_total_pago"].sum(), 1)),
            "segmento_estrutural": {
                "municipios": int(estrutural["municipios"]),
                "freq_acionamento": float(estrutural["freq_acionamento"]),
                "chuva_normal_mm": float(estrutural["chuva_normal_mm"]),
                "pct_valor_pago": float(estrutural["pct_valor_pago"]),
            },
            "ufs_mais_recorrentes": rec["uf"].value_counts().head(5).to_dict(),
            "top_municipios": rec.sort_values(["freq_acionamento", "valor_total_pago"], ascending=False)
            .head(15)[["municipio", "uf", "freq_acionamento"]].to_dict("records"),
            "recorrentes_com_risco_alto_na_safra_atual": (
                int(atual_alto["codigo_siafi"].isin(rec["codigo_siafi"]).sum()) if atual_alto is not None else None
            ),
        },
    }


def escrever_respostas_md(resp: dict, modo: str) -> str:
    p1, p2 = resp["pergunta_1"], resp["pergunta_2"]
    aviso = ("\n> **Atenção: resultados com dados SINTÉTICOS** (apenas validação do fluxo). "
             "Rode `python -m src.pipeline --download` para os números reais.\n") if modo == "sintetico" else ""
    top = "\n".join(f"| {m['municipio']} | {m['uf']} | {m['freq_acionamento']:.0%} |" for m in p2["top_municipios"])
    return f"""# Respostas às perguntas do projeto
{aviso}
## Pergunta 1 — {p1['pergunta']}

Com a chuva acumulada até o fim de **{p1['mes_corte_recomendado']}**, o modelo já alcança
{p1['pr_auc'] / p1['pr_auc_maximo']:.0%} do melhor desempenho possível (ROC-AUC {p1['roc_auc']:.2f},
PR-AUC {p1['pr_auc']:.2f}; taxa base de acionamento {p1['taxa_acionamento']:.0%}).
A previsão é feita dentro do ciclo da lavoura: no fim de {p1['mes_corte_recomendado']} faltam
**{p1['meses_antes_da_colheita']} meses** para o fim da colheita (junho), e o pagamento do benefício só começa, em
mediana, {p1['meses_de_antecedencia']:.0f} meses depois. O horizonte máximo testado é de 6 meses (dezembro).

Escopo: Semiárido (área da Sudene) e as lavouras de sequeiro cobertas pelo programa (feijão, milho, arroz,
mandioca e algodão), com uma safra por ano.

- ROC-AUC usando só chuva, por mês de corte: {', '.join(f'{m}: {v:.2f}' for m, v in p1['roc_auc_so_chuva_por_mes'].items())}
- Baseline "histórico do município": ROC-AUC {p1['roc_auc_baseline_historico']:.2f}
- Fatores mais importantes: {'; '.join(p1['principais_fatores'])}

## Pergunta 2 — {p2['pergunta']}

**{p2['municipios_recorrentes']} de {p2['municipios_analisados']} municípios** ({p2['criterio_recorrente']})
concentram **{p2['pct_valor_pago_recorrentes']:.0f}%** de todo o valor pago no período.
O K-Means isolou um segmento de **perda estrutural** com {p2['segmento_estrutural']['municipios']} municípios,
que acionaram o benefício em {p2['segmento_estrutural']['freq_acionamento']:.0%} das safras em média
(chuva normal de {p2['segmento_estrutural']['chuva_normal_mm']:.0f} mm na estação).
Para esses municípios, a perda não é exceção: é a regra — o que indica a necessidade de políticas
permanentes (cisternas e tecnologias de captação de água, sementes adaptadas, assistência técnica),
e não só do seguro emergencial.

UFs com mais municípios recorrentes: {', '.join(f'{uf} ({n})' for uf, n in p2['ufs_mais_recorrentes'].items())}.
Municípios recorrentes com risco alto já previsto para a safra atual: {p2['recorrentes_com_risco_alto_na_safra_atual']}.

| Município | UF | Safras com benefício |
|---|---|---|
{top}
"""


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def run(baixar: bool = False, sintetico: bool = False) -> dict:
    t0 = time.time()
    # o pipeline sempre escreve na raiz do projeto, nunca nos resultados de demonstração (demo/)
    config.PROCESSED_DIR = config.DATA_DIR / "processed"
    config.MODELS_DIR, config.REPORTS_DIR = config.ROOT / "models", config.ROOT / "reports"
    modo = preparar_dados(baixar, sintetico)

    # 1) Entendimento/preparação dos dados
    municipios = pd.read_csv(config.MUNICIPIOS_CSV)
    mensal = carregar_pagamentos_mensais()
    painel, rel_dados = construir_painel_safras(mensal, municipios)
    chuva = carregar_chuva_diaria()
    rel_dados["celulas_chuva"] = int(chuva[["lat", "lon"]].drop_duplicates().shape[0])
    rel_dados["dias_chuva_ausentes_pct"] = round(float(chuva["chuva_mm"].isna().mean() * 100), 3)
    log.info("Painel: %s", rel_dados)

    # 2) Pergunta 1: antecedência
    antecedencia, bases = experimento_antecedencia(painel, chuva)

    # 3) Modelo de produção (mês de corte padrão)
    corte = config.MES_CORTE_PRODUCAO
    base = bases[corte]
    comparacao, previsoes = classifier.comparar_modelos(base)
    ml = comparacao[comparacao["atributos"] == "chuva + histórico"]
    nome_melhor = ml.sort_values("pr_auc", ascending=False).iloc[0]["modelo"]
    modelo = classifier.modelos()[nome_melhor]
    oof, importancia = classifier.validar_por_safra(base, modelo, FEATURES, importancia=True)
    por_safra = classifier.metricas_por_safra(base, oof)
    final = clone(modelo).fit(base[FEATURES], base["acionou"].astype(int))

    # previsão da safra atual (resultado oficial ainda desconhecido)
    previsao_atual = None
    base_atual = montar_base(painel, chuva, corte, safras_extra=[config.SAFRA_ATUAL])
    base_atual = base_atual[base_atual["safra"] == config.SAFRA_ATUAL]
    if not base_atual.empty:
        previsao_atual = base_atual.assign(prob_acionar=final.predict_proba(base_atual[FEATURES])[:, 1])
    else:
        log.warning("Sem chuva suficiente para prever a safra %s até %s.", config.SAFRA_ATUAL, MESES[corte])

    # 4) Pergunta 2: segmentação
    chuva_safra = bases[config.MES_COLHEITA][["codigo_siafi", "safra", "chuva_total_mm", "chuva_pct_normal"]]
    perfil = segment.perfil_municipios(painel, chuva_safra)
    perfil, resumo_seg, silhuetas = segment.segmentar(perfil)
    if previsao_atual is not None:
        perfil = perfil.merge(previsao_atual[["codigo_siafi", "prob_acionar"]], on="codigo_siafi", how="left")

    respostas = responder_perguntas(antecedencia, comparacao, importancia, perfil, resumo_seg, previsao_atual, painel)

    # 5) Artefatos
    versao = datetime.now().strftime("%Y%m%d-%H%M%S")
    historico = base[["codigo_siafi", "codigo_ibge", "municipio", "uf", "latitude", "longitude", "safra",
                      "acionou", "beneficiarios", "valor_pago", *FEATURES_CHUVA, "historico_acionamento"]] \
        .assign(prob_fora_da_amostra=oof.values)
    historico.to_parquet(config.PROCESSED_DIR / "historico_municipio_safra.parquet", index=False)
    perfil.to_parquet(config.PROCESSED_DIR / "perfil_municipios.parquet", index=False)
    if previsao_atual is not None:
        colunas = list(dict.fromkeys(["codigo_siafi", "codigo_ibge", "municipio", "uf", "latitude", "longitude",
                                      "safra", *FEATURES, "prob_acionar"]))
        previsao_atual[colunas].to_parquet(
            config.PROCESSED_DIR / "previsao_safra_atual.parquet", index=False)

    antecedencia.to_csv(config.REPORTS_DIR / "antecedencia.csv", index=False)
    comparacao.to_csv(config.REPORTS_DIR / "comparacao_modelos.csv", index=False)
    importancia.assign(descricao=importancia["feature"].map(DESCRICAO_FEATURES)).to_csv(
        config.REPORTS_DIR / "importancia_atributos.csv", index=False)
    por_safra.to_csv(config.REPORTS_DIR / "metricas_por_safra.csv", index=False)
    resumo_seg.to_csv(config.REPORTS_DIR / "segmentos.csv", index=False)
    silhuetas.to_csv(config.REPORTS_DIR / "silhueta_kmeans.csv", index=False)
    pd.Series(rel_dados).to_json(config.REPORTS_DIR / "relatorio_dados.json", force_ascii=False, indent=2)
    (config.REPORTS_DIR / "respostas.json").write_text(json.dumps(respostas, ensure_ascii=False, indent=2,
                                                                  default=float))
    (config.REPORTS_DIR / "respostas.md").write_text(escrever_respostas_md(respostas, modo))

    joblib.dump({"modelo": final, "features": FEATURES, "nome": nome_melhor, "mes_corte": corte},
                config.MODELS_DIR / "modelo_risco.joblib")
    metadata = {
        "versao": versao, "modo_dados": modo, "git_commit": _git_commit(),
        "modelo": nome_melhor, "mes_corte": MESES[corte], "safras_treino": rel_dados["safras"],
        "safra_atual": config.SAFRA_ATUAL if previsao_atual is not None else None,
        "metricas_validacao": {k: float(v) for k, v in classifier.metricas(
            base["acionou"][oof.notna()], oof[oof.notna()]).items()},
        "dados": rel_dados, "duracao_s": round(time.time() - t0, 1),
    }
    (config.MODELS_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    with open(config.MODELS_DIR / "registry.jsonl", "a") as f:
        f.write(json.dumps({k: metadata[k] for k in ("versao", "modo_dados", "modelo", "metricas_validacao")},
                           ensure_ascii=False) + "\n")
    log.info("Pipeline concluído em %.0fs (modelo: %s, dados: %s)", time.time() - t0, nome_melhor, modo)
    return metadata


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", action="store_true", help="baixa/atualiza as fontes públicas antes")
    ap.add_argument("--synthetic", action="store_true", help="força dados sintéticos")
    args = ap.parse_args()
    run(baixar=args.download, sintetico=args.synthetic)
