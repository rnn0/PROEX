"""Configurações centrais do projeto (caminhos, períodos e parâmetros)."""
import os
from datetime import date
from pathlib import Path

ROOT = Path(os.environ.get("PROEX_ROOT", Path(__file__).resolve().parents[1]))
# Sem resultados próprios, API e dashboard usam os resultados reais versionados em demo/
# (gerados pelo workflow "Pipeline com dados reais"). Útil para hospedar o dashboard.
_DEMO = ROOT / "demo"
OUT_ROOT = (_DEMO if "PROEX_ROOT" not in os.environ and not (ROOT / "models" / "metadata.json").exists()
            and (_DEMO / "models" / "metadata.json").exists() else ROOT)

PERGUNTA_1 = "Dá para saber pela chuva, antes da colheita, quais municípios vão perder a safra?"
PERGUNTA_2 = "Em quais municípios a perda de safra se repete quase todo ano?"

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = OUT_ROOT / "data" / "processed"
MODELS_DIR = OUT_ROOT / "models"
REPORTS_DIR = OUT_ROOT / "reports"

GS_RAW_DIR = RAW_DIR / "garantia_safra"     # zips/CSVs mensais do Portal da Transparência
CHUVA_RAW_DIR = RAW_DIR / "chuva"           # JSON diário da NASA POWER, um por célula da grade
MUNICIPIOS_CSV = RAW_DIR / "municipios.csv"

# Fontes
PORTAL_GS_URL = "https://portaldatransparencia.gov.br/download-de-dados/garantia-safra/{yyyymm}"
# servidor de arquivos para onde o Portal redireciona (usado quando o Portal recusa a requisição)
PORTAL_GS_CDN_URL = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/garantia-safra/{yyyymm}_GarantiaSafra.zip"
NASA_POWER_URL = (
    "https://power.larc.nasa.gov/api/temporal/daily/point"
    "?parameters=PRECTOTCORR&community=AG&longitude={lon}&latitude={lat}"
    "&start={start}&end={end}&format=JSON"
)
MUNICIPIOS_URL = "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv"

# Pagamentos que começam entre julho de Y e junho de Y+1 são atribuídos à safra Y
# (ex.: folhas de dez/2021 e jan/2022 pagaram a safra 2020/2021; mar/2024 pagou a 2022/2023).
MES_INICIO_JANELA_PAGAMENTO = 7


def _ultima_safra_fechada(hoje: date | None = None) -> int:
    """Última safra cuja janela de pagamento (jul/Y a jun/Y+1) já terminou."""
    hoje = hoje or date.today()
    return hoje.year - 1 if hoje.month >= MES_INICIO_JANELA_PAGAMENTO else hoje.year - 2


# Período analisado. "Safra Y" = safra (Y-1)/Y, plantada no fim de Y-1 e colhida em Y.
SAFRA_INICIAL = int(os.environ.get("PROEX_SAFRA_INICIAL", 2014))
SAFRA_FINAL = int(os.environ.get("PROEX_SAFRA_FINAL", _ultima_safra_fechada()))
# Safra "em andamento", prevista pelo modelo (o resultado oficial ainda não saiu)
SAFRA_ATUAL = SAFRA_FINAL + 1

# Estação chuvosa usada nas features: de outubro de Y-1 até o mês de corte em Y.
MES_INICIO_ESTACAO = 10
# Previsão dentro do ciclo: de dezembro (logo após o plantio) a junho (colheita), horizonte de no máximo 6 meses.
# Lavouras do programa (feijão, milho) fecham o ciclo em ~3 a 4 meses; a colheita termina por volta de junho.
MESES_CORTE = [12, 1, 2, 3, 4, 5, 6]
MES_COLHEITA = 6


def ano_do_corte(safra: int, mes_corte: int) -> int:
    """Cortes de out-dez caem no ano anterior ao da colheita (safra Y-1/Y)."""
    return safra - 1 if mes_corte >= MES_INICIO_ESTACAO else safra
MES_CORTE_PRODUCAO = int(os.environ.get("PROEX_MES_CORTE", 4))  # modelo servido na API/dashboard

DIA_SECO_MM = 1.0  # dia com menos de 1 mm é considerado seco

# Grade da NASA POWER para precipitação (MERRA-2): 0,5° lat x 0,625° lon
GRADE_LAT = 0.5
GRADE_LON = 0.625

RANDOM_STATE = 42
N_CLUSTERS = int(os.environ.get("PROEX_N_CLUSTERS", 4))

# Sem dados reais em data/raw, o pipeline usa dados sintéticos (só para validar o fluxo)
USE_SYNTHETIC = os.environ.get("PROEX_SYNTHETIC", "auto")  # "auto" | "1" | "0"


def ensure_dirs() -> None:
    for d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, MODELS_DIR, REPORTS_DIR, GS_RAW_DIR, CHUVA_RAW_DIR):
        d.mkdir(parents=True, exist_ok=True)
