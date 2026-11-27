// Dashboard estático do projeto (dados em web/dados/, gerados por scripts/exportar_web.py)
const AZUL = "#257de0", LARANJA = "#f47230", CINZA = "#666666", GRADE = "#e6e6e6";
const ORDINAL = { "Perda estrutural": "#0e3d7e", "Perda frequente": "#1b64be", "Perda ocasional": "#519ced",
  "Baixo risco": "#84b9f3", "Risco muito baixo": "#b6d5f8", "Risco mínimo": "#cce3fd" };
const SEQUENCIAL = [[0, "#cce3fd"], [0.17, "#9dc8f7"], [0.33, "#6aabf1"], [0.5, "#338ced"], [0.67, "#2370cd"],
  [0.83, "#1757ac"], [1, "#0e3d7e"]];
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun"];
const CFG = { displayModeBar: false, responsive: true };

const pct = (x, d = 0) => x == null ? "–" : (100 * x).toLocaleString("pt-BR", { maximumFractionDigits: d }) + "%";
const num = (x, d = 0) => x == null ? "–" : Number(x).toLocaleString("pt-BR", { maximumFractionDigits: d, minimumFractionDigits: d });
const reais = x => x >= 1e9 ? `R$ ${num(x / 1e9, 2)} bi` : x >= 1e6 ? `R$ ${num(x / 1e6, 1)} mi` : `R$ ${num(x)}`;
const el = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function layout(titulo, extra = {}) {
  return Object.assign({
    title: { text: titulo, font: { size: 15 }, x: 0.02 }, margin: { l: 56, r: 16, t: 56, b: 88 },
    paper_bgcolor: "#fff", plot_bgcolor: "#fff", font: { color: "#191919", size: 12 },
    legend: { orientation: "h", y: -0.15, yanchor: "top", x: 0 }, hoverlabel: { bgcolor: "#fff" },
    xaxis: { showgrid: false, linecolor: GRADE, tickfont: { color: CINZA } },
    yaxis: { gridcolor: GRADE, zeroline: false, tickfont: { color: CINZA } },
  }, extra);
}

function kpis(id, itens) {
  el(id).innerHTML = itens.map(([rot, val, det]) =>
    `<div class="kpi"><div class="rot">${esc(rot)}</div><div class="val">${esc(val)}</div>${det ? `<div class="det">${esc(det)}</div>` : ""}</div>`).join("");
}

function tabela(id, colunas, linhas) {
  const cab = colunas.map(c => `<th class="${c.n ? "n" : ""}">${esc(c.t)}</th>`).join("");
  const corpo = linhas.map(l => "<tr>" + colunas.map(c => `<td class="${c.n ? "n" : ""}">${esc(c.f ? c.f(l) : l[c.k])}</td>`).join("") + "</tr>").join("");
  el(id).innerHTML = `<table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody></table>`;
}

function mapa(id, pontos, cor, opcoes) {
  Plotly.react(id, [Object.assign({
    type: "scattermap", lat: pontos.map(p => p.lat), lon: pontos.map(p => p.lon), mode: "markers",
    marker: Object.assign({ size: 8 }, cor), text: pontos.map(opcoes.texto), hoverinfo: "text",
  }, opcoes.trace || {})].concat(opcoes.mais || []), {
    title: { text: opcoes.titulo, font: { size: 15 }, x: 0.02 }, margin: { l: 0, r: 0, t: 48, b: 0 },
    // OpenStreetMap: fundo aberto, sem chave de API (o raster da CARTO passou a exigir chave)
    map: { style: "open-street-map", center: { lat: -9, lon: -40 }, zoom: 4.2 }, paper_bgcolor: "#fff",
    legend: { orientation: "h", y: 0, x: 0, bgcolor: "rgba(255,255,255,.85)" }, showlegend: !!opcoes.legenda,
  }, CFG);
}

let D = {}, UF = "";

async function carregar() {
  const nomes = ["resumo", "municipios", "antecedencia", "comparacao", "por_safra_metricas", "segmentos", "importancia", "simulador"];
  const res = await Promise.all(nomes.map(n => fetch(`dados/${n}.json`).then(r => r.json())));
  nomes.forEach((n, i) => D[n] = res[i]);
  const ufs = [...new Set(D.municipios.map(m => m.uf))].sort();
  el("uf").insertAdjacentHTML("beforeend", ufs.map(u => `<option>${u}</option>`).join(""));
  el("uf").addEventListener("change", e => { UF = e.target.value; desenhar(); });
  el("busca").addEventListener("change", municipio);
  ["s-pct", "s-ver", "s-hist"].forEach(id => el(id).addEventListener("input", simulador));
  document.querySelectorAll("#abas button").forEach(b => b.addEventListener("click", () => abrir(b.dataset.aba)));
  const r = D.resumo;
  el("titulo-p1").textContent = r.perguntas[0];
  el("titulo-p2").textContent = r.perguntas[1];
  if (r.safraAtual) el("aba-atual").textContent = `Risco da safra ${r.safraAtual}`;
  el("versao").textContent = `modelo ${r.modelo}, versão ${r.versao}`;
  el("dados-qualidade").textContent = JSON.stringify(r.dados, null, 2);
  desenhar();
  simulador();
}

function abrir(aba) {
  document.querySelectorAll("#abas button").forEach(b => b.setAttribute("aria-selected", b.dataset.aba === aba));
  document.querySelectorAll(".aba").forEach(s => s.classList.toggle("ativa", s.id === aba));
  window.dispatchEvent(new Event("resize"));
}

function filtrados() { return UF ? D.municipios.filter(m => m.uf === UF) : D.municipios; }

function desenhar() {
  const ms = filtrados(), r = D.resumo, S = r.safras;
  // ------------------------------------------------ visão geral
  const valor = ms.reduce((s, m) => s + m.valor, 0);
  let tot = 0, ac = 0;
  ms.forEach(m => m.hAcion.forEach(a => { if (a != null) { tot++; ac += a; } }));
  kpis("kpis-geral", [["Municípios analisados", num(ms.length)], ["Safras", `${S[0]}–${S[S.length - 1]}`],
    ["Municípios-safra com benefício", pct(ac / tot)], ["Valor pago no período", reais(valor)]]);
  const porAno = S.map((s, i) => {
    const v = ms.map(m => m.hAcion[i]).filter(x => x != null), c = ms.map(m => m.hChuva[i]).filter(x => x != null).sort((a, b) => a - b);
    return { s, pct: v.reduce((a, b) => a + b, 0) / v.length, chuva: c[Math.floor(c.length / 2)] };
  });
  Plotly.react("g-perda-ano", [{ type: "bar", x: porAno.map(p => p.s), y: porAno.map(p => p.pct), marker: { color: AZUL },
    hovertemplate: "Safra %{x}<br>%{y:.0%} dos municípios<extra></extra>" }],
    layout("Em quantos municípios a safra foi perdida, por ano", { yaxis: { tickformat: ".0%", gridcolor: GRADE } }), CFG);
  Plotly.react("g-chuva-ano", [{ type: "bar", x: porAno.map(p => p.s), y: porAno.map(p => p.chuva), marker: { color: AZUL },
    hovertemplate: "Safra %{x}<br>%{y:.0f}% da média<extra></extra>" }],
    layout("Chuva da estação (mediana dos municípios, % da média)", {
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 100, y1: 100, line: { dash: "dot", color: CINZA } }] }), CFG);

  // ------------------------------------------------ pergunta 1
  const p1 = r.respostas.pergunta_1;
  kpis("kpis-p1", [["Previsão possível a partir do fim de", p1.mes_corte_recomendado],
    ["Antecedência até o início do pagamento", `${num(p1.meses_de_antecedencia)} meses`, "mediana; a perda acontece na colheita"],
    ["ROC-AUC nesse mês", num(p1.roc_auc, 2), `acaso = 0,50 · só histórico = ${num(p1.roc_auc_baseline_historico, 2)}`]]);
  const ant = D.antecedencia, series = ["só chuva", "chuva + histórico"];
  Plotly.react("g-antecedencia", series.map((s, i) => {
    const a = ant.filter(x => x.atributos === s).sort((x, y) => x.mes_corte - y.mes_corte);
    return { type: "scatter", mode: "lines+markers", name: s, x: a.map(x => x.mes), y: a.map(x => x.roc_auc),
      line: { color: [AZUL, LARANJA][i], width: 2 }, marker: { size: 8 },
      customdata: a.map(x => x.meses_ate_pagamento),
      hovertemplate: "%{x}: ROC-AUC %{y:.2f}<br>~%{customdata:.0f} meses antes do pagamento<extra>" + s + "</extra>" };
  }), layout("Precisão conforme o mês em que a previsão é feita (ROC-AUC)", {
    xaxis: { title: { text: "Mês em que a previsão é feita" }, showgrid: false }, yaxis: { gridcolor: GRADE, title: { text: "ROC-AUC" } },
    margin: { l: 56, r: 16, t: 56, b: 96 }, legend: { orientation: "h", y: -0.28, yanchor: "top", x: 0 } }), CFG);
  const imp = D.importancia.slice(0, 8).reverse();
  Plotly.react("g-importancia", [{ type: "bar", orientation: "h", x: imp.map(i => i.importancia), y: imp.map(i => i.descricao),
    marker: { color: AZUL }, hovertemplate: "%{y}<br>%{x:.3f}<extra></extra>" }],
    layout("O que mais pesa na previsão", { margin: { l: 320, r: 16, t: 56, b: 40 }, yaxis: { automargin: true } }), CFG);
  const faixas = [[0, 50, "< 50%"], [50, 70, "50–70%"], [70, 85, "70–85%"], [85, 100, "85–100%"], [100, 115, "100–115%"], [115, 1e9, "> 115%"]];
  const rel = faixas.map(([a, b, rot]) => {
    let n = 0, k = 0;
    ms.forEach(m => m.hChuva.forEach((c, i) => { if (c != null && c >= a && c < b && m.hAcion[i] != null) { n++; k += m.hAcion[i]; } }));
    return { rot, taxa: n ? k / n : null, n };
  });
  Plotly.react("g-chuva-perda", [{ type: "bar", x: rel.map(x => x.rot), y: rel.map(x => x.taxa), marker: { color: AZUL },
    customdata: rel.map(x => x.n), hovertemplate: "%{x}: %{y:.0%} (n=%{customdata})<extra></extra>" }],
    layout(`Chance de perder a safra conforme a chuva até ${r.mesCorte} (% da média do município)`, {
      yaxis: { tickformat: ".0%", gridcolor: GRADE } }), CFG);
  const f3 = k => l => num(l[k], 3);
  tabela("t-comparacao", [{ t: "Modelo", k: "modelo" }, { t: "Atributos", k: "atributos" },
    { t: "ROC-AUC", f: f3("roc_auc"), n: 1 }, { t: "PR-AUC", f: f3("pr_auc"), n: 1 }, { t: "Brier", f: f3("brier"), n: 1 },
    { t: "F1", f: f3("f1"), n: 1 }], D.comparacao);
  tabela("t-por-safra", [{ t: "Safra", k: "safra" }, { t: "Municípios", k: "municipios", n: 1 },
    { t: "Receberam", k: "acionaram", n: 1 }, { t: "Previstos com risco alto", k: "previstos_risco_alto", n: 1 },
    { t: "ROC-AUC", f: f3("roc_auc"), n: 1 }, { t: "PR-AUC", f: f3("pr_auc"), n: 1 }], D.por_safra_metricas);

  // ------------------------------------------------ pergunta 2
  const rec = ms.filter(m => m.freq >= 0.5), rec75 = ms.filter(m => m.freq >= 0.75), todas = ms.filter(m => m.freq === 1);
  kpis("kpis-p2", [["Receberam em ≥ metade das safras", `${num(rec.length)} de ${num(ms.length)}`],
    ["Receberam em ≥ 75% das safras", num(rec75.length), `${pct(rec75.reduce((s, m) => s + m.valor, 0) / valor)} do valor pago`],
    ["Perderam a safra em todos os anos", num(todas.length)]]);
  const ordem = Object.keys(ORDINAL).filter(s => ms.some(m => m.seg === s));
  mapa("m-segmentos", [], {}, { titulo: "Segmentos de municípios (K-Means)", legenda: true, texto: () => "",
    trace: { showlegend: false }, mais: ordem.map(s => {
      const g = ms.filter(m => m.seg === s);
      return { type: "scattermap", name: s, lat: g.map(m => m.lat), lon: g.map(m => m.lon), mode: "markers",
        marker: { size: 8, color: ORDINAL[s] }, hoverinfo: "text",
        text: g.map(m => `<b>${esc(m.nome)}</b> (${m.uf})<br>${s}<br>benefício em ${m.acion} de ${m.obs} safras`) };
    }) });
  const seg = ordem.map(s => {
    const g = ms.filter(m => m.seg === s);
    return { s, n: g.length, freq: g.reduce((a, m) => a + m.freq, 0) / g.length, chuva: g.reduce((a, m) => a + (m.chuvaNormal || 0), 0) / g.length,
      valor: g.reduce((a, m) => a + m.valor, 0) / valor };
  });
  Plotly.react("g-segmentos", [{ type: "bar", x: seg.map(x => x.s), y: seg.map(x => x.freq), marker: { color: seg.map(x => ORDINAL[x.s]) },
    customdata: seg.map(x => [x.n, x.valor]),
    hovertemplate: "%{x}<br>%{y:.0%} das safras · %{customdata[0]} municípios<br>%{customdata[1]:.0%} do valor pago<extra></extra>" }],
    layout("Frequência média de perda por segmento", { yaxis: { tickformat: ".0%", gridcolor: GRADE } }), CFG);
  tabela("t-segmentos", [{ t: "Segmento", k: "s" }, { t: "Municípios", k: "n", n: 1 }, { t: "Freq. de perda", f: l => pct(l.freq), n: 1 },
    { t: "Chuva normal (mm)", f: l => num(l.chuva), n: 1 }, { t: "% do valor", f: l => pct(l.valor), n: 1 }], seg);
  tabela("t-recorrentes", [{ t: "Município", k: "nome" }, { t: "UF", k: "uf" }, { t: "Segmento", k: "seg" },
    { t: "Safras com benefício", f: l => `${l.acion} de ${l.obs}`, n: 1 }, { t: "Frequência", f: l => pct(l.freq), n: 1 },
    { t: "Valor recebido", f: l => reais(l.valor), n: 1 }, { t: "Chuva normal (mm)", f: l => num(l.chuvaNormal), n: 1 },
    { t: `Risco ${r.safraAtual || ""}`, f: l => pct(l.prob), n: 1 }],
    rec.slice().sort((a, b) => b.freq - a.freq || b.valor - a.valor));

  // ------------------------------------------------ safra atual
  const at = ms.filter(m => m.prob != null);
  el("titulo-atual").textContent = r.safraAtual ? `Previsão para a safra ${r.safraAtual - 1}/${r.safraAtual} (chuva até o fim de ${r.mesCorte})` : "Sem previsão para a safra atual";
  kpis("kpis-atual", [["Risco alto (≥ 50%)", num(at.filter(m => m.prob >= 0.5).length)],
    ["Risco moderado (25–50%)", num(at.filter(m => m.prob >= 0.25 && m.prob < 0.5).length)],
    ["Chuva mediana da estação", `${num(at.map(m => m.chuvaAtual).sort((a, b) => a - b)[Math.floor(at.length / 2)])}% da média`]]);
  mapa("m-atual", at, { color: at.map(m => m.prob), cmin: 0, cmax: 1, colorscale: SEQUENCIAL,
    colorbar: { title: { text: "Probabilidade" }, tickformat: ".0%" } }, { titulo: "Probabilidade de precisar do Garantia-Safra",
    texto: m => `<b>${esc(m.nome)}</b> (${m.uf})<br>probabilidade ${pct(m.prob)}<br>chuva ${num(m.chuvaAtual)}% da média` });
  tabela("t-atual", [{ t: "Município", k: "nome" }, { t: "UF", k: "uf" }, { t: "Probabilidade", f: l => pct(l.prob), n: 1 },
    { t: "Chuva (% da média)", f: l => num(l.chuvaAtual), n: 1 }, { t: "Maior veranico (dias)", k: "veranicoAtual", n: 1 }],
    at.slice().sort((a, b) => b.prob - a.prob));
  const atual = el("busca").value;
  el("busca").innerHTML = ms.map(m => `<option value="${m.id}">${esc(m.nome)} (${m.uf})</option>`).join("");
  el("busca").value = ms.some(m => String(m.id) === atual) ? atual : String(ms.slice().sort((a, b) => b.freq - a.freq)[0].id);
  municipio();
}

function municipio() {
  const m = D.municipios.find(x => String(x.id) === el("busca").value);
  if (!m) return;
  kpis("kpis-mun", [["Segmento", m.seg], ["Safras com benefício", `${m.acion} de ${m.obs}`], ["Valor recebido no período", reais(m.valor)],
    [`Risco na safra ${D.resumo.safraAtual || ""}`, pct(m.prob)]]);
  const S = D.resumo.safras, grupos = [[1, "Recebeu o benefício", LARANJA], [0, "Sem benefício", AZUL]];
  Plotly.react("g-mun", grupos.map(([a, nome, cor]) => {
    const idx = S.map((_, i) => i).filter(i => m.hAcion[i] === a);
    return { type: "bar", name: nome, x: idx.map(i => S[i]), y: idx.map(i => m.hChuva[i]), marker: { color: cor },
      customdata: idx.map(i => m.hProb[i]), hovertemplate: "Safra %{x}: %{y:.0f}% da média<br>Previsão do modelo: %{customdata:.0%}<extra></extra>" };
  }), layout(`${m.nome} (${m.uf}): chuva de cada safra e se houve perda comprovada`, {
    xaxis: { dtick: 1, showgrid: false }, yaxis: { title: { text: "Chuva da estação (% da média)" }, gridcolor: GRADE }, showlegend: true,
    shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: 100, y1: 100, line: { dash: "dot", color: CINZA } }] }), CFG);
}

function simulador() {
  const g = D.simulador; if (!g) return;
  const p = +el("s-pct").value, v = +el("s-ver").value, h = +el("s-hist").value / 8;
  el("v-pct").textContent = `${p}%`; el("v-ver").textContent = v; el("v-hist").textContent = `${el("s-hist").value} de 8`;
  const i = g.pct.indexOf(p), j = g.veranico.indexOf(v), k = g.hist.findIndex(x => Math.abs(x - h) < 1e-9);
  const prob = g.prob[(i * g.veranico.length + j) * g.hist.length + k];
  const nivel = prob >= 0.5 ? "risco alto" : prob >= 0.25 ? "risco moderado" : "risco baixo";
  el("r-prob").textContent = pct(prob); el("r-nivel").textContent = `de precisar do Garantia-Safra · ${nivel}`;
  el("r-barra").style.width = `${Math.round(prob * 100)}%`;
}

window.addEventListener("load", () => carregar().catch(e => {
  document.querySelector("main").innerHTML = `<p>Não foi possível carregar os dados (${esc(e.message)}).</p>`;
}));
