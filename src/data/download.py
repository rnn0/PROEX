"""
Download das fontes públicas (executado na sua máquina, que tem acesso à internet):

1. Municípios (código IBGE, código SIAFI e coordenadas) — repositório kelvins/municipios-brasileiros.
2. Garantia-Safra — arquivos mensais do Portal da Transparência (um zip por folha de pagamento).
3. Chuva diária — API da NASA POWER (PRECTOTCORR, mm/dia), uma requisição por célula da grade.

Tudo fica em cache em data/raw/: rodar de novo só baixa o que falta.
Se o Portal bloquear o download automático, baixe os zips manualmente em
https://portaldatransparencia.gov.br/download-de-dados/garantia-safra e coloque em data/raw/garantia_safra/.

Uso: python -m src.data.download
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd
import requests

from src import config

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0 (projeto academico PROEX - mineracao de dados)"}


def baixar_municipios(force: bool = False) -> pd.DataFrame:
    if force or not config.MUNICIPIOS_CSV.exists():
        log.info("Baixando tabela de municípios...")
        r = requests.get(config.MUNICIPIOS_URL, headers=HEADERS, timeout=60)
        r.raise_for_status()
        config.MUNICIPIOS_CSV.write_bytes(r.content)
    return pd.read_csv(config.MUNICIPIOS_CSV)


def meses_garantia_safra() -> list[str]:
    """Folhas de pagamento necessárias: de jul/(SAFRA_INICIAL) até o mês atual."""
    hoje = date.today()
    ano, mes = config.SAFRA_INICIAL, config.MES_INICIO_JANELA_PAGAMENTO
    meses = []
    while (ano, mes) <= (hoje.year, hoje.month):
        meses.append(f"{ano}{mes:02d}")
        mes += 1
        if mes == 13:
            ano, mes = ano + 1, 1
    return meses


def _arquivo_local(yyyymm: str):
    for padrao in (f"*{yyyymm}*.zip", f"*{yyyymm}*.csv"):
        achados = sorted(config.GS_RAW_DIR.glob(padrao))
        if achados:
            return achados[0]
    return None


def _baixar_mes(yyyymm: str, mes_atual: str) -> tuple[str, str]:
    if _arquivo_local(yyyymm):
        return yyyymm, "em_cache"
    marcador = config.GS_RAW_DIR / f"{yyyymm}.vazio"
    if marcador.exists():
        return yyyymm, "sem_dados"
    urls = [config.PORTAL_GS_URL.format(yyyymm=yyyymm), config.PORTAL_GS_CDN_URL.format(yyyymm=yyyymm)]
    erro = ""
    for tentativa in range(4):
        url = urls[tentativa % 2]
        try:
            r = requests.get(url, headers=HEADERS, timeout=300, allow_redirects=True)
        except requests.RequestException as exc:
            erro = str(exc)
            time.sleep(3 * (tentativa + 1))
            continue
        eh_zip = r.content[:2] == b"PK"
        if r.status_code == 200 and eh_zip:
            (config.GS_RAW_DIR / f"{yyyymm}_GarantiaSafra.zip").write_bytes(r.content)
            log.info("Garantia-Safra %s: %.1f MB", yyyymm, len(r.content) / 1e6)
            return yyyymm, "baixados"
        if r.status_code in (200, 404) and not eh_zip and url == urls[0]:
            # o Portal responde sem arquivo quando não houve folha naquele mês
            if yyyymm != mes_atual:
                marcador.touch()
            return yyyymm, "sem_dados"
        erro = f"HTTP {r.status_code}"
        time.sleep(2 * (tentativa + 1))
    return yyyymm, f"erro: {erro}"


def baixar_garantia_safra(workers: int = 3) -> dict:
    """Baixa as folhas mensais em paralelo. Meses sem pagamento ganham um marcador .vazio."""
    status = {"baixados": 0, "em_cache": 0, "sem_dados": 0, "erros": []}
    mes_atual = date.today().strftime("%Y%m")
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for yyyymm, res in ex.map(lambda m: _baixar_mes(m, mes_atual), meses_garantia_safra()):
            if res.startswith("erro"):
                status["erros"].append(f"{yyyymm}: {res}")
            else:
                status[res] += 1
    log.info("Garantia-Safra: %s", status)
    if status["baixados"] + status["em_cache"] == 0:
        raise RuntimeError(f"Nenhuma folha do Garantia-Safra foi baixada: {status['erros'][:5]}")
    return status


def celula_grade(lat: float, lon: float) -> tuple[float, float]:
    """Centro da célula da grade MERRA-2 (0,5° x 0,625°) que contém o ponto."""
    return (round(round(lat / config.GRADE_LAT) * config.GRADE_LAT, 4),
            round(round(lon / config.GRADE_LON) * config.GRADE_LON, 4))


def _arquivo_celula(lat: float, lon: float):
    return config.CHUVA_RAW_DIR / f"power_{lat:+.4f}_{lon:+.4f}.json"


def _baixar_celula(lat: float, lon: float, inicio: str, fim: str, tentativas: int = 4) -> str:
    destino = _arquivo_celula(lat, lon)
    url = config.NASA_POWER_URL.format(lat=lat, lon=lon, start=inicio, end=fim)
    for i in range(tentativas):
        try:
            r = requests.get(url, headers=HEADERS, timeout=120)
            if r.status_code == 200:
                serie = r.json()["properties"]["parameter"]["PRECTOTCORR"]
                destino.write_text(json.dumps({"lat": lat, "lon": lon, "inicio": inicio, "fim": fim,
                                               "PRECTOTCORR": serie}))
                return "ok"
            if r.status_code == 429:
                time.sleep(10 * (i + 1))
                continue
        except (requests.RequestException, KeyError, ValueError):
            pass
        time.sleep(2 * (i + 1))
    return "erro"


def baixar_chuva(municipios: pd.DataFrame, workers: int = 8) -> dict:
    """Uma série diária por célula da grade (vários municípios compartilham a mesma célula)."""
    inicio = f"{config.SAFRA_INICIAL - 1}{config.MES_INICIO_ESTACAO:02d}01"
    fim = (date.today() - timedelta(days=7)).strftime("%Y%m%d")
    celulas = {celula_grade(la, lo) for la, lo in zip(municipios["latitude"], municipios["longitude"])}

    pendentes = []
    for lat, lon in celulas:
        arq = _arquivo_celula(lat, lon)
        if arq.exists():
            meta = json.loads(arq.read_text())
            # atualiza se o cache terminou há mais de 30 dias
            if meta.get("inicio") <= inicio and meta.get("fim", "") >= (date.today() - timedelta(days=37)).strftime("%Y%m%d"):
                continue
        pendentes.append((lat, lon))

    log.info("Chuva NASA POWER: %d células (%d a baixar)", len(celulas), len(pendentes))
    resultado = {"celulas": len(celulas), "baixadas": 0, "erros": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = {ex.submit(_baixar_celula, la, lo, inicio, fim): (la, lo) for la, lo in pendentes}
        for n, fut in enumerate(as_completed(futuros), start=1):
            if fut.result() == "ok":
                resultado["baixadas"] += 1
            else:
                resultado["erros"] += 1
            if n % 50 == 0:
                log.info("  %d/%d células", n, len(pendentes))
    log.info("Chuva: %s", resultado)
    return resultado


def baixar_tudo() -> None:
    config.ensure_dirs()
    municipios = baixar_municipios()
    baixar_garantia_safra()
    # chuva só para os municípios que aparecem no Garantia-Safra (área de atuação do programa)
    from src.data.garantia_safra import carregar_pagamentos_mensais

    mensal = carregar_pagamentos_mensais()
    siafi = set(mensal["codigo_siafi"].unique())
    alvo = municipios[municipios["siafi_id"].isin(siafi)]
    if alvo.empty:
        raise RuntimeError("Nenhum município do Garantia-Safra encontrado na tabela de municípios.")
    baixar_chuva(alvo)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    baixar_tudo()
