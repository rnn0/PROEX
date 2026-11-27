"""
Dashboard do projeto (Streamlit).

    streamlit run dashboard/app.py      ->  http://localhost:8501
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import joblib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config  # noqa: E402
from src.models.segment import LIMIAR_RECORRENTE  # noqa: E402

API_URL = os.environ.get("API_URL", "http://localhost:8000")
MAP_STYLE = os.environ.get("MAP_STYLE", "carto-positron")  # "white-bg" funciona sem internet

# Paleta (referência validada): categórica em ordem fixa; ordinal/sequencial em um só tom (azul)
AZUL, LARANJA = "#257de0", "#f47230"
CINZA_TEXTO, CINZA_GRADE = "#666666", "#e6e6e6"
ORDINAL = {"Perda estrutural": "#0e3d7e", "Perda frequente": "#1b64be", "Perda ocasional": "#519ced",
           "Baixo risco": "#84b9f3", "Risco muito baixo": "#b6d5f8", "Risco mínimo": "#cce3fd"}
SEQUENCIAL = ["#cce3fd", "#9dc8f7", "#6aabf1", "#338ced", "#2370cd", "#1757ac", "#0e3d7e"]

st.set_page_config(page_title="Garantia-Safra | Risco de perda no Semiárido", page_icon="🌵", layout="wide")


def estilo(fig: go.Figure, altura: int = 380) -> go.Figure:
    fig.update_layout(
        height=altura, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="white", paper_bgcolor="white",
        font=dict(color="#191919", size=13), legend=dict(orientation="h", y=1.08, x=0, title=None),
        hoverlabel=dict(bgcolor="white", font_color="#191919"),
    )
    fig.update_xaxes(showgrid=False, linecolor=CINZA_GRADE, tickfont_color=CINZA_TEXTO, title_font_color=CINZA_TEXTO)
    fig.update_yaxes(gridcolor=CINZA_GRADE, zeroline=False, tickfont_color=CINZA_TEXTO, title_font_color=CINZA_TEXTO)
    return fig


@st.cache_data(show_spinner=False)
def carregar_dados(versao: str):
    leia = lambda nome: pd.read_csv(config.REPORTS_DIR / nome)  # noqa: E731
    prev = config.PROCESSED_DIR / "previsao_safra_atual.parquet"
    return {
        "historico": pd.read_parquet(config.PROCESSED_DIR / "historico_municipio_safra.parquet"),
        "perfil": pd.read_parquet(config.PROCESSED_DIR / "perfil_municipios.parquet"),
        "previsao": pd.read_parquet(prev) if prev.exists() else None,
        "antecedencia": leia("antecedencia.csv"),
        "comparacao": leia("comparacao_modelos.csv"),
        "importancia": leia("importancia_atributos.csv"),
        "por_safra": leia("metricas_por_safra.csv"),
        "segmentos": leia("segmentos.csv"),
        "silhueta": leia("silhueta_kmeans.csv"),
        "respostas": json.loads((config.REPORTS_DIR / "respostas.json").read_text()),
        "dados": json.loads((config.REPORTS_DIR / "relatorio_dados.json").read_text()),
    }


meta_arq = config.MODELS_DIR / "metadata.json"
if not meta_arq.exists():
    st.error("Os modelos ainda não foram treinados. Rode `python -m src.pipeline` (ou `docker compose up`).")
    st.stop()
meta = json.loads(meta_arq.read_text())
d = carregar_dados(meta["versao"])

# ---------------------------------------------------------------- cabeçalho e filtros
st.title("Garantia-Safra: quem vai perder a safra no Semiárido?")
st.caption("Mineração de dados com pagamentos do Garantia-Safra (Portal da Transparência) e chuva diária "
           "(NASA POWER) · ODS 2 (Fome Zero), ODS 13 (Ação Climática) e ODS 1 (Erradicação da Pobreza)")
if meta["modo_dados"] == "sintetico":
    st.warning("**Dados SINTÉTICOS** — estes números só validam o fluxo. Rode "
               "`python -m src.pipeline --download` (ou `docker compose up`) para usar os dados reais.")

ufs = sorted(d["perfil"]["uf"].dropna().unique())
filtro_uf = st.multiselect("Filtrar estados (vale para todas as abas)", ufs, placeholder="Todos os estados")


def filtrar(df: pd.DataFrame | None) -> pd.DataFrame | None:
    if df is None or not filtro_uf:
        return df
    return df[df["uf"].isin(filtro_uf)]


hist, perfil, prev = filtrar(d["historico"]), filtrar(d["perfil"]), filtrar(d["previsao"])

aba_geral, aba_p1, aba_p2, aba_atual, aba_mun, aba_sim = st.tabs([
    "Visão geral", "Pergunta 1 · Previsão", "Pergunta 2 · Recorrência",
    f"Risco da safra {meta['safra_atual'] or ''}", "Município", "Simulador"])

# ---------------------------------------------------------------- visão geral
with aba_geral:
    c = st.columns(4)
    c[0].metric("Municípios analisados", f"{perfil['codigo_siafi'].nunique():,}".replace(",", "."))
    c[1].metric("Safras", f"{hist['safra'].min()}–{hist['safra'].max()}")
    c[2].metric("Municípios-safra com benefício", f"{hist['acionou'].mean():.0%}")
    c[3].metric("Valor pago no período", (f"R$ {hist['valor_pago'].sum() / 1e9:.2f} bi"
                 if hist["valor_pago"].sum() > 1e9 else f"R$ {hist['valor_pago'].sum() / 1e6:.1f} mi").replace(".", ","))

    por_safra = hist.groupby("safra", as_index=False).agg(
        pct=("acionou", "mean"), valor=("valor_pago", "sum"), chuva=("chuva_pct_normal", "median"))
    col1, col2 = st.columns(2)
    fig = px.bar(por_safra, x="safra", y="pct", labels={"safra": "Safra", "pct": "Municípios com benefício"},
                 title="Em quantos municípios a safra foi perdida, por ano")
    fig.update_traces(marker_color=AZUL, hovertemplate="Safra %{x}<br>%{y:.0%} dos municípios<extra></extra>")
    fig.update_yaxes(tickformat=".0%")
    col1.plotly_chart(estilo(fig), use_container_width=True)
    fig = px.bar(por_safra, x="safra", y="chuva", labels={"safra": "Safra", "chuva": "Chuva (% da média)"},
                 title="Chuva da estação (mediana dos municípios, % da média)")
    fig.add_hline(y=100, line_dash="dot", line_color=CINZA_TEXTO, annotation_text="média histórica", annotation_position="top left")
    fig.update_traces(marker_color=AZUL, hovertemplate="Safra %{x}<br>%{y:.0f}% da média<extra></extra>")
    col2.plotly_chart(estilo(fig), use_container_width=True)
    st.caption("Anos de seca (barras baixas à direita) coincidem com os anos de muitos municípios com benefício "
               "(barras altas à esquerda) — é essa relação que o modelo explora.")

    with st.expander("Qualidade e origem dos dados"):
        st.json(d["dados"])
        st.write(f"Versão do modelo: `{meta['versao']}` · commit `{meta.get('git_commit')}` · "
                 f"modelo: **{meta['modelo']}** (corte em {meta['mes_corte']})")

# ---------------------------------------------------------------- pergunta 1
with aba_p1:
    r1 = d["respostas"]["pergunta_1"]
    st.subheader(config.PERGUNTA_1)
    st.caption("Escopo: Semiárido (área da Sudene), lavouras de sequeiro do programa (feijão, milho, arroz, "
               "mandioca e algodão), uma safra por ano. A previsão é feita dentro do ciclo, no máximo 6 meses antes do fim da colheita.")
    c = st.columns(3)
    c[0].metric("Previsão possível a partir do fim de", r1["mes_corte_recomendado"])
    c[1].metric("Antes do fim da colheita", f"{r1.get('meses_antes_da_colheita', '-')} meses")
    c[2].metric("ROC-AUC nesse mês", f"{r1['roc_auc']:.2f}",
                delta=f"{r1['roc_auc'] - r1['roc_auc_baseline_historico']:+.2f} vs. só histórico")

    ant = d["antecedencia"].copy()
    ant["mes"] = pd.Categorical(ant["mes"], ["dez", "jan", "fev", "mar", "abr", "mai", "jun"], ordered=True)
    fig = px.line(ant.sort_values("mes"), x="mes", y="pr_auc", color="atributos", markers=True,
                  color_discrete_sequence=[AZUL, LARANJA],
                  labels={"mes": "Mês em que a previsão é feita", "pr_auc": "PR-AUC (validação por safra)"},
                  title="A precisão melhora até junho, mas já em janeiro supera o acaso",
                  custom_data=["roc_auc", "meses_ate_pagamento"])
    fig.update_traces(line_width=2, marker_size=8, hovertemplate="%{x}: PR-AUC %{y:.2f} · ROC-AUC "
                      "%{customdata[0]:.2f}<br>~%{customdata[1]:.0f} meses antes do pagamento<extra></extra>")
    col1, col2 = st.columns([3, 2])
    col1.plotly_chart(estilo(fig), use_container_width=True)

    imp = d["importancia"].head(8).iloc[::-1]
    fig = px.bar(imp, x="importancia", y="descricao", orientation="h", title="O que mais pesa na previsão",
                 labels={"importancia": "Importância (queda no PR-AUC ao embaralhar)", "descricao": ""})
    fig.update_traces(marker_color=AZUL, hovertemplate="%{y}<br>%{x:.3f}<extra></extra>")
    col2.plotly_chart(estilo(fig), use_container_width=True)

    # relação direta chuva x benefício
    faixas = pd.cut(hist["chuva_pct_normal"], [0, 50, 70, 85, 100, 115, 1000],
                    labels=["< 50%", "50–70%", "70–85%", "85–100%", "100–115%", "> 115%"])
    rel = hist.groupby(faixas, observed=True)["acionou"].agg(["mean", "size"]).reset_index()
    fig = px.bar(rel, x="chuva_pct_normal", y="mean", title="Chance de perder a safra conforme a chuva da estação",
                 labels={"chuva_pct_normal": f"Chuva até {meta['mes_corte']} (% da média do município)",
                         "mean": "Municípios-safra com benefício"}, custom_data=["size"])
    fig.update_traces(marker_color=AZUL, hovertemplate="%{x}: %{y:.0%} (n=%{customdata[0]})<extra></extra>")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(estilo(fig, 340), use_container_width=True)

    st.markdown("**Comparação de modelos** (validação deixando uma safra inteira de fora)")
    st.dataframe(d["comparacao"].style.format({"roc_auc": "{:.3f}", "pr_auc": "{:.3f}", "brier": "{:.3f}",
                                                "f1": "{:.3f}"}, na_rep="-"), hide_index=True,
                 use_container_width=True)
    st.markdown("**Desempenho em cada safra** (modelo de produção)")
    st.dataframe(d["por_safra"].style.format({"roc_auc": "{:.2f}", "pr_auc": "{:.2f}", "brier": "{:.3f}",
                                               "f1": "{:.2f}"}, na_rep="-"), hide_index=True,
                 use_container_width=True)

# ---------------------------------------------------------------- pergunta 2
with aba_p2:
    r2 = d["respostas"]["pergunta_2"]
    st.subheader(config.PERGUNTA_2)
    rec = perfil[perfil["recorrente"]]
    c = st.columns(3)
    c[0].metric("Municípios com perda recorrente", f"{len(rec)} de {len(perfil)}")
    c[1].metric("Parcela do valor pago", f"{100 * rec['valor_total_pago'].sum() / max(perfil['valor_total_pago'].sum(), 1):.0f}%")
    c[2].metric("Critério: benefício em", f"≥ {LIMIAR_RECORRENTE:.0%} das safras")

    ordem = [s for s in ORDINAL if s in set(perfil["segmento"])]
    fig = px.scatter_map(perfil, lat="latitude", lon="longitude", color="segmento",
                         category_orders={"segmento": ordem}, color_discrete_map=ORDINAL, zoom=4.3,
                         center={"lat": -9.0, "lon": -40.0}, map_style=MAP_STYLE,
                         hover_name="municipio",
                         hover_data={"uf": True, "freq_acionamento": ":.0%", "chuva_normal_mm": ":.0f",
                                     "latitude": False, "longitude": False, "segmento": True},
                         title="Segmentos de municípios (K-Means)")
    fig.update_traces(marker_size=9)
    col1, col2 = st.columns([3, 2])
    estilo(fig, 560).update_layout(legend=dict(orientation="h", y=-0.01, yanchor="top", x=0))
    col1.plotly_chart(fig, use_container_width=True)

    seg = perfil.groupby("segmento", as_index=False).agg(
        municipios=("codigo_siafi", "size"), freq=("freq_acionamento", "mean"),
        chuva=("chuva_normal_mm", "mean"), valor=("valor_total_pago", "sum"))
    seg["pct_valor"] = seg["valor"] / seg["valor"].sum()
    seg["segmento"] = pd.Categorical(seg["segmento"], ordem, ordered=True)
    seg = seg.sort_values("segmento")
    fig = px.bar(seg, x="segmento", y="freq", color="segmento", color_discrete_map=ORDINAL,
                 title="Frequência média de perda por segmento",
                 labels={"segmento": "", "freq": "Safras com benefício"}, custom_data=["municipios", "pct_valor"])
    fig.update_traces(hovertemplate="%{x}<br>%{y:.0%} das safras · %{customdata[0]} municípios<br>"
                      "%{customdata[1]:.0%} do valor pago<extra></extra>", showlegend=False)
    fig.update_yaxes(tickformat=".0%")
    col2.plotly_chart(estilo(fig, 280), use_container_width=True)
    col2.dataframe(seg.rename(columns={"municipios": "municípios", "freq": "freq. perda", "chuva": "chuva normal (mm)",
                                       "pct_valor": "% do valor"})[["segmento", "municípios", "freq. perda",
                                                                     "chuva normal (mm)", "% do valor"]]
                   .style.format({"freq. perda": "{:.0%}", "chuva normal (mm)": "{:.0f}", "% do valor": "{:.0%}"}),
                   hide_index=True, use_container_width=True)

    st.markdown("**Municípios onde a perda é a regra** — candidatos a políticas permanentes de convivência com a "
                "seca (cisternas, captação de água, sementes adaptadas, assistência técnica)")
    tabela = rec.sort_values(["freq_acionamento", "valor_total_pago"], ascending=False)[
        ["municipio", "uf", "segmento", "safras_acionadas", "safras_observadas", "freq_acionamento",
         "valor_total_pago", "chuva_normal_mm"] + (["prob_acionar"] if "prob_acionar" in rec else [])]
    st.dataframe(tabela.style.format({"freq_acionamento": "{:.0%}", "valor_total_pago": "R$ {:,.0f}",
                                      "chuva_normal_mm": "{:.0f}", "prob_acionar": "{:.0%}"}, na_rep="-"),
                 hide_index=True, use_container_width=True, height=380)
    with st.expander("Como o número de segmentos foi escolhido"):
        st.dataframe(d["silhueta"], hide_index=True)
        st.caption(f"Usamos k = {config.N_CLUSTERS} para ter níveis de risco interpretáveis; a silhueta mostra a "
                   "separação dos grupos para cada k.")

# ---------------------------------------------------------------- safra atual
with aba_atual:
    if prev is None or prev.empty:
        st.info("Ainda não há chuva suficiente para prever a safra atual.")
    else:
        st.subheader(f"Previsão para a safra {meta['safra_atual'] - 1}/{meta['safra_atual']} "
                     f"(chuva até o fim de {meta['mes_corte']})")
        st.caption("O resultado oficial (portaria de pagamento) ainda não saiu: este é o alerta antecipado.")
        c = st.columns(3)
        c[0].metric("Municípios com risco alto (≥ 50%)", int((prev["prob_acionar"] >= 0.5).sum()))
        c[1].metric("Risco moderado (25–50%)",
                    int(((prev["prob_acionar"] >= 0.25) & (prev["prob_acionar"] < 0.5)).sum()))
        c[2].metric("Chuva mediana da estação", f"{prev['chuva_pct_normal'].median():.0f}% da média")
        col1, col2 = st.columns([3, 2])
        fig = px.scatter_map(prev, lat="latitude", lon="longitude", color="prob_acionar",
                             color_continuous_scale=SEQUENCIAL, range_color=(0, 1), zoom=4.3,
                             center={"lat": -9.0, "lon": -40.0}, map_style=MAP_STYLE, hover_name="municipio",
                             hover_data={"uf": True, "prob_acionar": ":.0%", "chuva_pct_normal": ":.0f",
                                         "latitude": False, "longitude": False},
                             labels={"prob_acionar": "Probabilidade", "chuva_pct_normal": "Chuva (% média)"},
                             title="Probabilidade de precisar do Garantia-Safra")
        fig.update_traces(marker_size=9)
        fig.update_coloraxes(colorbar_tickformat=".0%")
        col1.plotly_chart(estilo(fig, 560), use_container_width=True)
        col2.dataframe(prev.sort_values("prob_acionar", ascending=False)[
            ["municipio", "uf", "prob_acionar", "chuva_pct_normal", "max_dias_secos_seguidos"]]
            .rename(columns={"prob_acionar": "probabilidade", "chuva_pct_normal": "chuva (% média)",
                             "max_dias_secos_seguidos": "maior veranico (dias)"})
            .style.format({"probabilidade": "{:.0%}", "chuva (% média)": "{:.0f}"}),
            hide_index=True, use_container_width=True, height=560)

# ---------------------------------------------------------------- município
with aba_mun:
    opcoes = perfil.sort_values(["uf", "municipio"])
    rotulos = (opcoes["municipio"] + " (" + opcoes["uf"] + ")").tolist()
    escolha = st.selectbox("Município", rotulos, index=0 if rotulos else None)
    if escolha:
        linha = opcoes.iloc[rotulos.index(escolha)]
        h = hist[hist["codigo_siafi"] == linha["codigo_siafi"]].sort_values("safra")
        c = st.columns(4)
        c[0].metric("Segmento", linha["segmento"])
        c[1].metric("Safras com benefício", f"{int(linha['safras_acionadas'])} de {int(linha['safras_observadas'])}")
        c[2].metric("Valor recebido no período", f"R$ {linha['valor_total_pago']:,.0f}".replace(",", "."))
        if "prob_acionar" in linha and pd.notna(linha.get("prob_acionar")):
            c[3].metric(f"Risco na safra {meta['safra_atual']}", f"{linha['prob_acionar']:.0%}")
        h = h.assign(situacao=h["acionou"].map({1: "Recebeu o benefício", 0: "Sem benefício"}))
        fig = px.bar(h, x="safra", y="chuva_pct_normal", color="situacao",
                     color_discrete_map={"Recebeu o benefício": LARANJA, "Sem benefício": AZUL},
                     labels={"safra": "Safra", "chuva_pct_normal": "Chuva da estação (% da média)", "situacao": ""},
                     title="Chuva de cada safra e se houve perda comprovada", custom_data=["prob_fora_da_amostra"])
        fig.add_hline(y=100, line_dash="dot", line_color=CINZA_TEXTO)
        fig.update_traces(hovertemplate="Safra %{x}: %{y:.0f}% da média<br>Previsão do modelo: "
                          "%{customdata[0]:.0%}<extra></extra>")
        st.plotly_chart(estilo(fig), use_container_width=True)

# ---------------------------------------------------------------- simulador
with aba_sim:
    st.subheader("E se chovesse assim? Simule o risco de um município")
    st.caption("Usa o endpoint POST /prever da API (ou o modelo local, se a API não estiver no ar).")
    c1, c2, c3 = st.columns(3)
    pct = c1.slider("Chuva da estação (% da média)", 10, 200, 70, 5)
    normal = c1.number_input("Chuva normal da estação no local (mm)", 100, 2000, 600, 50)
    veranico = c2.slider("Maior veranico (dias secos seguidos)", 0, 120, 25)
    dias = c2.slider("Dias com chuva na estação", 0, 150, 40)
    hist_frac = c3.slider("Fração das safras anteriores com benefício", 0.0, 1.0, 0.4, 0.05)
    tri = c3.slider("Chuva dos últimos 3 meses (% da média)", 10, 200, pct, 5)
    entrada = {
        "chuva_total_mm": normal * pct / 100, "chuva_pct_normal": pct, "chuva_anomalia_z": (pct - 100) / 30,
        "dias_com_chuva": dias, "max_dias_secos_seguidos": veranico, "chuva_trimestre_pct_normal": tri,
        "chuva_safra_anterior_pct_normal": 100.0, "historico_acionamento": hist_frac,
        "latitude": -8.0, "longitude": -39.0,
    }
    try:
        r = requests.post(f"{API_URL}/prever", json=entrada, timeout=3)
        r.raise_for_status()
        prob, origem = r.json()["prob_acionar"], "API"
    except Exception:
        pacote = joblib.load(config.MODELS_DIR / "modelo_risco.joblib")
        prob = float(pacote["modelo"].predict_proba(pd.DataFrame([entrada])[pacote["features"]])[:, 1][0])
        origem = "modelo local"
    nivel = "alto" if prob >= 0.5 else "moderado" if prob >= 0.25 else "baixo"
    st.metric(f"Probabilidade de precisar do Garantia-Safra (via {origem})", f"{prob:.0%}", help=f"Risco {nivel}")
    st.progress(min(max(prob, 0.0), 1.0), text=f"Risco {nivel}")

st.divider()
st.caption("Projeto PROEX — Mineração de Dados · Fontes: Portal da Transparência (Garantia-Safra), NASA POWER "
           "(chuva), IBGE/kelvins (municípios).")
