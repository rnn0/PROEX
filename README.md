# Garantia-Safra: quem vai perder a safra no Semiárido?

**Dashboard online:** https://proex-web.vercel.app

[![CI](https://github.com/rnn0/PROEX/actions/workflows/ci.yml/badge.svg)](https://github.com/rnn0/PROEX/actions)

Projeto da disciplina **PROEX: Projeto de Mineração de Dados** (metodologia CRISP-DM).
Usa dados públicos para **prever quais municípios do Semiárido vão perder a safra** e precisar do
Garantia-Safra, e para **identificar onde a perda é recorrente** e pede políticas permanentes de convivência
com a seca.

**ODS:** 2 (Fome Zero e Agricultura Sustentável), 13 (Ação Contra a Mudança do Clima) e
1 (Erradicação da Pobreza).

## Perguntas

1. **Dá para saber pela chuva, antes da colheita, quais municípios vão perder a safra?**
2. **Em quais municípios a perda de safra se repete quase todo ano?**

Escopo: 1.317 municípios de 11 estados (BA, PI, PB, CE, RN, MG, PE, AL, MA, SE e AM), safras 2018 a 2025, no
Semiárido (área da Sudene) e as lavouras de sequeiro cobertas pelo programa (feijão, milho, arroz,
mandioca e algodão), com uma safra por ano.

As respostas são calculadas pelo pipeline e ficam em `reports/respostas.md` e no dashboard. Os resultados com os
dados reais estão em [`demo/reports/respostas.md`](demo/reports/respostas.md).

## Dados

| Fonte | O que é |
|---|---|
| [Portal da Transparência — Garantia-Safra](https://portaldatransparencia.gov.br/download-de-dados/garantia-safra) | pagamentos mensais do benefício, por agricultor e município |
| [NASA POWER](https://power.larc.nasa.gov/) | chuva diária por ponto (reanálise, sem falhas) |
| [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros) | códigos IBGE/SIAFI e coordenadas |

Tudo é baixado automaticamente (com cache em `data/raw/`). Sem internet, o pipeline usa um **dataset
sintético** no mesmo formato, só para validar o fluxo (o dashboard avisa quando é o caso).

## Como funciona

```
Portal da Transparência ──► pagamentos por município e mês ──► episódios ──► alvo: recebeu na safra?
NASA POWER ──────────────► chuva diária por célula ─────────► atributos da estação (out → mês de corte)
                                                         │
                       Classificação (validação deixando uma safra inteira de fora)
                       Previsão dentro do ciclo (corte de dez a jun)            ──► Pergunta 1
                       K-Means (frequência de perda, chuva normal, variabilidade) ──► Pergunta 2
                                                         │
                                  API FastAPI  +  Dashboard Streamlit
```

Detalhes, decisões e limitações em [`docs/CRISP-DM.md`](docs/CRISP-DM.md).

## Como executar

### Com Docker (recomendado)

```bash
docker compose up --build
```

- Na primeira subida o serviço `pipeline` baixa os dados públicos e treina os modelos
  (pode levar de 20 a 40 minutos; as próximas subidas reaproveitam o cache).
- **Dashboard:** http://localhost:8501
- **API (Swagger):** http://localhost:8000/docs

Para treinar de novo (ex.: depois de novos meses de pagamento): `PROEX_RETRAIN=1 docker compose up pipeline`.
Para testar rápido sem baixar nada: `PROEX_SYNTHETIC=1 PROEX_RETRAIN=1 docker compose up`.

### Dashboard online (Vercel)

A pasta `web/` é uma versão estática do dashboard (HTML + JavaScript, sem Python), com os resultados reais já
exportados em `web/dados/`. Na Vercel: *Add New → Project*, importe este repositório e, em **Root Directory**,
escolha `web` (Framework Preset: *Other*, sem comando de build). Para atualizar os dados depois de treinar de
novo: `python scripts/exportar_web.py`.

### Dashboard online (Streamlit Community Cloud)

O dashboard roda direto do repositório usando os resultados reais de `demo/`: em
[share.streamlit.io](https://share.streamlit.io), crie um app apontando para este repositório, branch `main`,
arquivo `dashboard/app.py`, e escolha Python 3.12 em *Advanced settings*.

### Sem Docker

```bash
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

python -m src.pipeline --download      # baixa os dados e treina (gera data/processed, models/ e reports/)
uvicorn api.main:app --port 8000       # API
streamlit run dashboard/app.py         # dashboard (http://localhost:8501)
```

Se o Portal da Transparência bloquear o download automático, baixe os arquivos mensais do Garantia-Safra
manualmente e coloque os `.zip` em `data/raw/garantia_safra/` antes de rodar `python -m src.pipeline`.

### Testes e lint

```bash
pytest       # unitários + teste ponta a ponta (pipeline sintético + API)
ruff check .
```

## Estrutura

```
src/
  config.py                 caminhos, período, parâmetros
  data/download.py          download das fontes (com cache)
  data/garantia_safra.py    leitura do Portal, episódios de pagamento, painel município x safra
  data/chuva.py             séries diárias da NASA POWER
  data/synthetic.py         dados sintéticos no mesmo formato (testes/CI)
  features/build.py         atributos de chuva por mês de corte + histórico
  models/classifier.py      modelos, validação por safra, métricas
  models/segment.py         K-Means e perfil dos municípios
  pipeline.py               orquestra tudo e escreve os artefatos
api/                        API FastAPI
dashboard/app.py            dashboard Streamlit
docs/CRISP-DM.md            documentação do projeto
tests/                      testes
```

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/health` | versão do modelo e origem dos dados |
| GET | `/respostas` | respostas às duas perguntas |
| GET | `/municipios?uf=CE&recorrente=true` | perfil e segmento dos municípios |
| GET | `/municipios/{codigo_ibge}` | histórico safra a safra de um município |
| GET | `/risco/safra-atual?uf=PB&min_prob=0.5` | ranking de risco da safra em andamento |
| GET | `/segmentos` | resumo dos segmentos do K-Means |
| POST | `/prever` | simulador: probabilidade para um cenário de chuva |
