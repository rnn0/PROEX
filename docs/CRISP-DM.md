# Documentação CRISP-DM

Projeto da disciplina **PROEX: Projeto de Mineração de Dados**.
Tema: **risco de perda de safra da agricultura familiar no Semiárido**, a partir dos pagamentos do
Garantia-Safra e da chuva.

> Os números das seções 4 e 5 são gerados pelo pipeline em `reports/` (`respostas.md`, `antecedencia.csv`,
> `comparacao_modelos.csv`, `segmentos.csv`). Depois de rodar com os dados reais, copie os valores para cá.

## 1. Entendimento do negócio

**Contexto.** O [Garantia-Safra](https://www.gov.br/mda/pt-br/acesso-a-informacao/acoes-e-programas/garantia-safra)
é um benefício pago a agricultores familiares de baixa renda (até 1,5 salário mínimo) da área da Sudene quando o
município comprova perda de pelo menos 50% da produção por seca ou excesso de chuva. Hoje o benefício é de
R$ 1.200 por agricultor, pago em parcela única.
O pagamento chega muitos meses depois da perda: por exemplo, a safra 2022/2023 só foi paga em março de 2024.

**ODS atendidos.**

| ODS | Como o projeto contribui |
|---|---|
| 2 — Fome Zero e Agricultura Sustentável (meta 2.4) | antecipar a perda protege a segurança alimentar de quem vive da roça |
| 13 — Ação Contra a Mudança do Clima (meta 13.1) | aumenta a capacidade de adaptação a secas, um risco climático |
| 1 — Erradicação da Pobreza (meta 1.5) | reduz a vulnerabilidade dos mais pobres a choques climáticos |

**Perguntas do trabalho.**

1. **Com quantos meses de antecedência os dados de chuva permitem prever que um município vai precisar do
   Garantia-Safra?** Se a resposta for "vários meses antes do pagamento", estados e municípios podem se preparar
   (distribuição de água, sementes, cestas, frentes de trabalho) antes de a portaria sair.
2. **Quais municípios têm perda recorrente e precisariam de políticas permanentes de convivência com a seca?**
   Onde a perda é a regra e não a exceção, um seguro emergencial anual não resolve: são candidatos prioritários
   a cisternas, tecnologias de captação de água, sementes adaptadas e assistência técnica.

**Critério de sucesso.** Um modelo avaliado em safras que ele nunca viu deve superar com folga os baselines
(taxa média e histórico do município), medido por ROC-AUC e PR-AUC.

## 2. Entendimento dos dados

| Fonte | Conteúdo | Uso |
|---|---|---|
| [Portal da Transparência — Garantia-Safra](https://portaldatransparencia.gov.br/download-de-dados/garantia-safra) | uma linha por parcela paga: mês, UF, código SIAFI e nome do município, NIS e nome do agricultor, valor | alvo (o município recebeu o benefício naquela safra?) |
| [NASA POWER](https://power.larc.nasa.gov/) (API diária, `PRECTOTCORR`) | chuva diária corrigida (mm/dia), grade de 0,5° × 0,625° | atributos de chuva |
| [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros) | código IBGE, código SIAFI, latitude e longitude | ligação SIAFI → IBGE e coordenadas |

Observações:
- O Portal identifica o município pelo **código SIAFI**, não pelo IBGE; a tabela de municípios faz a ponte.
- Os arquivos do Portal são mensais (folha de pagamento). Um mesmo pagamento pode vir em várias folhas: em
  parcelas (até 2021 eram 5 × R$ 170) ou em lotes de municípios autorizados em portarias diferentes.
- A NASA POWER é uma reanálise por satélite/modelo: cobre todos os municípios sem falhas, ao contrário das
  estações do INMET, que são esparsas no Semiárido. Vários municípios caem na mesma célula, então baixamos
  uma série por célula.

## 3. Preparação dos dados

1. **Agregação mensal** (`src/data/garantia_safra.py`): cada arquivo vira uma tabela município × mês com
   parcelas, beneficiários únicos (NIS) e valor. Colunas são identificadas pelo nome (com ou sem acento).
2. **Episódios de pagamento**: meses de pagamento a até 2 meses de distância formam um episódio. O mês de início
   define a safra: **pagamento iniciado entre julho de Y e junho de Y+1 → safra Y** (safra (Y-1)/Y).
   Isso foi conferido com as portarias publicadas (folhas de dez/2021 e jan/2022 → safra 2020/2021;
   mar/2024 → safra 2022/2023). Episódios muito pequenos (< 10% do típico do município) até 12 meses depois de
   outro são tratados como resíduos (desbloqueios) e somados ao anterior.
3. **Painel município × safra**: todos os municípios que já receberam o benefício, em todas as safras do período.
   Alvo `acionou` = 1 se houve pagamento naquela safra.
4. **Atributos de chuva** (`src/features/build.py`), da estação de outubro de Y-1 até o **mês de corte** em Y:

| Atributo | Descrição |
|---|---|
| `chuva_total_mm` | chuva acumulada na estação |
| `chuva_pct_normal` | chuva da estação em % da média do próprio local |
| `chuva_anomalia_z` | desvio em desvios-padrão |
| `dias_com_chuva` | dias com ≥ 1 mm |
| `max_dias_secos_seguidos` | maior veranico de janeiro até o corte |
| `chuva_trimestre_pct_normal` | chuva dos 3 meses antes do corte, em % da média |
| `chuva_safra_anterior_pct_normal` | estação anterior inteira, em % da média |
| `historico_acionamento` | fração das safras **anteriores** em que o município recebeu (sem vazamento) |

5. **Qualidade**: relatório em `reports/relatorio_dados.json` (arquivos lidos, episódios, municípios sem
   coordenada descartados, dias de chuva ausentes, taxa de acionamento).

## 4. Modelagem

**Classificação** (`src/models/classifier.py`): regressão logística, Random Forest e Gradient Boosting
(HistGradientBoosting), cada um com dois conjuntos de atributos (só chuva; chuva + histórico), contra dois
baselines (taxa média; histórico do município). Classes balanceadas por peso.

**Validação: deixa uma safra inteira de fora.** Cada safra é prevista por um modelo treinado com as demais.
Um split aleatório seria enganoso: a seca atinge centenas de municípios no mesmo ano, e misturar o mesmo ano em
treino e teste inflaria as métricas.

**Experimento de antecedência (pergunta 1).** O mesmo modelo é treinado com a chuva cortada no fim de janeiro,
fevereiro, ..., junho. Para cada corte medimos o desempenho e a mediana de meses até o início do pagamento.
O "mês recomendado" é o primeiro que alcança 95% do melhor PR-AUC.

**Segmentação (pergunta 2)** (`src/models/segment.py`): K-Means (k = 4, silhueta reportada para k = 2..6)
sobre frequência de acionamento, chuva normal, variabilidade da chuva e frequência de estações secas
(< 70% da média). Os grupos são rotulados pela frequência média de perda: perda estrutural, frequente,
ocasional e baixo risco. Também usamos um critério direto: **recorrente = recebeu em ≥ 50% das safras**.

## 5. Avaliação

Preencher com os números de `reports/` depois de rodar com os dados reais:

- Comparação de modelos (`comparacao_modelos.csv`): ROC-AUC / PR-AUC de cada modelo e dos baselines.
- Antecedência (`antecedencia.csv`): desempenho por mês de corte → **resposta à pergunta 1**.
- Importância por permutação (`importancia_atributos.csv`): o que mais pesa na previsão.
- Segmentos (`segmentos.csv`) e lista de municípios recorrentes → **resposta à pergunta 2**.
- Desempenho por safra (`metricas_por_safra.csv`): em quais anos o modelo erra mais.

**Limitações.**
1. O Portal mostra quem **recebeu**, não quem **aderiu**. Um município sem pagamento numa safra pode não ter
   aderido naquele ano (e não necessariamente ter tido boa colheita). Tratamos o universo como "municípios que
   já receberam alguma vez".
2. O benefício depende também de etapas administrativas (aporte do município, laudos). Parte dos "erros" do
   modelo pode ser burocracia, não clima.
3. O programa também cobre perda por **excesso** de chuva, que os atributos capturam pior.
4. A NASA POWER tem resolução grossa (~55 km); chuvas locais podem escapar.
5. A normal climatológica é calculada com todas as safras do período (pequeno vazamento de escala, não de alvo).

## 6. Implantação

- **Pipeline reprodutível**: `python -m src.pipeline --download` baixa as fontes (com cache) e gera tudo.
  Cada execução grava `models/metadata.json` (versão, commit, modo de dados, métricas) e uma linha em
  `models/registry.jsonl`.
- **API FastAPI**: `/health`, `/respostas`, `/segmentos`, `/municipios`, `/municipios/{codigo_ibge}`,
  `/risco/safra-atual` e `POST /prever` (simulador).
- **Dashboard Streamlit**: visão geral, uma aba por pergunta, mapa de risco da safra atual, ficha do
  município e simulador (consome a API).
- **Docker Compose**: serviço `pipeline` (baixa e treina na primeira subida), `api` e `dashboard`.
- **Qualidade**: testes unitários + teste ponta a ponta com dados sintéticos, `ruff`, CI no GitHub Actions
  (lint, testes e build da imagem).

**Uso social / extensão.** O dashboard pode ser apresentado a secretarias de agricultura, ao escritório
local da Emater/ATER ou a sindicatos de trabalhadores rurais como ferramenta de **alerta antecipado**
(aba "Risco da safra") e de **priorização de investimentos permanentes** (aba "Perda recorrente").
