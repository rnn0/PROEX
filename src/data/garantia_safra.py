"""
Leitura e preparação dos pagamentos do Garantia-Safra (Portal da Transparência).

Cada arquivo mensal tem uma linha por parcela paga a um agricultor. O que interessa ao projeto é o
município: em quais safras ele teve perda comprovada (>= 50%) e recebeu o benefício.

Etapas:
1. arquivo mensal -> agregado por município (parcelas, beneficiários, valor), com cache em data/interim/gs/
2. meses consecutivos de pagamento -> "episódios"; o mês de início do episódio define a safra
3. painel município x safra com o alvo `acionou` (1 = recebeu o benefício naquela safra)
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
import zipfile
from pathlib import Path

import pandas as pd

from src import config

log = logging.getLogger(__name__)

CHUNK = 500_000


def _normalizar(nome: str) -> str:
    nome = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", nome).strip().upper()


def _identificar_colunas(colunas: list[str]) -> dict[str, str]:
    """Acha as colunas pelo nome, tolerando acentos e pequenas variações entre anos."""
    norm = {c: _normalizar(c) for c in colunas}
    achar = lambda pred: next((c for c, n in norm.items() if pred(n)), None)  # noqa: E731
    mapa = {
        "codigo_siafi": achar(lambda n: "SIAFI" in n),
        "uf": achar(lambda n: n == "UF" or n.startswith("UF ")),
        "nome_municipio": achar(lambda n: "NOME" in n and "MUNIC" in n),
        "valor": achar(lambda n: "VALOR" in n),
        "nis": achar(lambda n: "NIS" in n),
    }
    faltando = [k for k in ("codigo_siafi", "valor") if mapa[k] is None]
    if faltando:
        raise ValueError(f"Colunas obrigatórias não encontradas ({faltando}) em: {colunas}")
    return {k: v for k, v in mapa.items() if v is not None}


def _valor_para_float(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip().str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _abrir_csv(caminho: Path):
    if caminho.suffix.lower() == ".zip":
        with zipfile.ZipFile(caminho) as z:
            nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not nomes:
                raise ValueError(f"Zip sem CSV: {caminho}")
            return io.BytesIO(z.read(nomes[0]))
    return caminho


def agregar_arquivo(caminho: Path) -> pd.DataFrame:
    """Agrega um arquivo mensal por município."""
    yyyymm = re.search(r"(20\d{2})(0[1-9]|1[0-2])", caminho.name)
    if not yyyymm:
        raise ValueError(f"Não achei AAAAMM no nome do arquivo: {caminho.name}")
    mes = yyyymm.group(0)

    partes, nis_unicos, mapa = [], [], None
    leitor = pd.read_csv(_abrir_csv(caminho), sep=";", encoding="latin-1", dtype=str, chunksize=CHUNK)
    for chunk in leitor:
        if mapa is None:
            mapa = _identificar_colunas(list(chunk.columns))
        df = pd.DataFrame({k: chunk[v] for k, v in mapa.items()})
        df["valor"] = _valor_para_float(df["valor"])
        df["codigo_siafi"] = pd.to_numeric(df["codigo_siafi"], errors="coerce")
        df = df.dropna(subset=["codigo_siafi"])
        df["codigo_siafi"] = df["codigo_siafi"].astype(int)
        chaves = ["codigo_siafi"] + [c for c in ("uf", "nome_municipio") if c in df]
        partes.append(df.groupby(chaves, as_index=False).agg(parcelas=("valor", "size"), valor=("valor", "sum")))
        if "nis" in df:
            nis_unicos.append(df[["codigo_siafi", "nis"]].drop_duplicates())

    if not partes:
        return pd.DataFrame(columns=["codigo_siafi", "mes", "parcelas", "valor", "beneficiarios"])
    agg = pd.concat(partes)
    chaves = [c for c in ("codigo_siafi", "uf", "nome_municipio") if c in agg]
    agg = agg.groupby(chaves, as_index=False)[["parcelas", "valor"]].sum()
    if nis_unicos:
        benef = pd.concat(nis_unicos).drop_duplicates().groupby("codigo_siafi").size().rename("beneficiarios")
        agg = agg.merge(benef, on="codigo_siafi", how="left")
    else:
        agg["beneficiarios"] = agg["parcelas"]
    agg["mes"] = mes
    return agg


def carregar_pagamentos_mensais(raw_dir: Path | None = None) -> pd.DataFrame:
    """Lê todos os arquivos (com cache por arquivo) e devolve o painel município x mês."""
    raw_dir = raw_dir or config.GS_RAW_DIR
    cache_dir = config.INTERIM_DIR / "gs"
    cache_dir.mkdir(parents=True, exist_ok=True)
    arquivos = sorted(list(raw_dir.glob("*.zip")) + list(raw_dir.glob("*.csv")))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo do Garantia-Safra em {raw_dir}")

    tabelas = []
    for arq in arquivos:
        cache = cache_dir / f"{arq.stem}.parquet"
        if cache.exists() and cache.stat().st_mtime >= arq.stat().st_mtime:
            tabelas.append(pd.read_parquet(cache))
            continue
        try:
            t = agregar_arquivo(arq)
        except Exception as exc:  # arquivo corrompido não derruba o pipeline
            log.warning("Ignorando %s: %s", arq.name, exc)
            continue
        t.to_parquet(cache, index=False)
        tabelas.append(t)
    mensal = pd.concat(tabelas, ignore_index=True)
    mensal = mensal[mensal["parcelas"] > 0]
    return mensal.groupby(["codigo_siafi", "mes"], as_index=False).agg(
        parcelas=("parcelas", "sum"), valor=("valor", "sum"), beneficiarios=("beneficiarios", "sum"),
        **({"uf": ("uf", "first")} if "uf" in mensal else {}),
        **({"nome_municipio": ("nome_municipio", "first")} if "nome_municipio" in mensal else {}),
    )


def safra_do_mes(ano: int, mes: int) -> int:
    """Pagamento iniciado entre jul/Y e jun/Y+1 -> safra Y."""
    return ano if mes >= config.MES_INICIO_JANELA_PAGAMENTO else ano - 1


def construir_episodios(mensal: pd.DataFrame, gap_meses: int = 2, residual_frac: float = 0.10) -> pd.DataFrame:
    """
    Agrupa meses de pagamento próximos (intervalo <= gap_meses) em episódios e atribui cada um a uma safra.
    Episódios pequenos (< residual_frac do episódio típico do município) até 12 meses depois de outro são
    tratados como pagamentos residuais (ex.: desbloqueios) e somados ao episódio anterior.
    """
    df = mensal.copy()
    df["data"] = pd.to_datetime(df["mes"], format="%Y%m")
    df["idx_mes"] = df["data"].dt.year * 12 + df["data"].dt.month - 1
    df = df.sort_values(["codigo_siafi", "idx_mes"])
    novo = df.groupby("codigo_siafi")["idx_mes"].diff().fillna(999) > gap_meses
    df["episodio"] = novo.groupby(df["codigo_siafi"]).cumsum()

    ep = df.groupby(["codigo_siafi", "episodio"], as_index=False).agg(
        inicio=("idx_mes", "min"), fim=("idx_mes", "max"), meses=("idx_mes", "size"),
        beneficiarios=("beneficiarios", "max"), parcelas=("parcelas", "sum"), valor=("valor", "sum"),
    )
    mediana = ep.groupby("codigo_siafi")["beneficiarios"].transform("median")
    anterior_fim = ep.groupby("codigo_siafi")["fim"].shift()
    residual = (ep["beneficiarios"] < residual_frac * mediana) & ((ep["inicio"] - anterior_fim) <= 12)
    ep["residual"] = residual
    # residual herda o episódio anterior
    ep["grupo"] = (~ep["residual"]).groupby(ep["codigo_siafi"]).cumsum()
    ep = ep.groupby(["codigo_siafi", "grupo"], as_index=False).agg(
        inicio=("inicio", "min"), fim=("fim", "max"), meses=("meses", "sum"),
        beneficiarios=("beneficiarios", "max"), parcelas=("parcelas", "sum"), valor=("valor", "sum"),
    )
    ano, mes = ep["inicio"] // 12, ep["inicio"] % 12 + 1
    ep["safra"] = [safra_do_mes(a, m) for a, m in zip(ano, mes)]
    ep["mes_inicio_pagamento"] = [f"{a}-{m:02d}" for a, m in zip(ano, mes)]
    return ep.drop(columns=["grupo"])


def construir_painel_safras(mensal: pd.DataFrame, municipios: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Painel município x safra (SAFRA_INICIAL..SAFRA_FINAL) com o alvo `acionou`."""
    ep = construir_episodios(mensal)
    por_safra = ep.groupby(["codigo_siafi", "safra"], as_index=False).agg(
        beneficiarios=("beneficiarios", "max"), valor_pago=("valor", "sum"),
        mes_inicio_pagamento=("mes_inicio_pagamento", "min"),
    )
    safras = list(range(config.SAFRA_INICIAL, config.SAFRA_FINAL + 1))
    universo = sorted(mensal["codigo_siafi"].unique())

    mun = municipios.rename(columns={"siafi_id": "codigo_siafi", "nome": "municipio"})
    mun = mun[["codigo_siafi", "codigo_ibge", "municipio", "codigo_uf", "latitude", "longitude"]]
    sem_coord = sorted(set(universo) - set(mun["codigo_siafi"]))

    painel = pd.MultiIndex.from_product([universo, safras], names=["codigo_siafi", "safra"]).to_frame(index=False)
    painel = painel.merge(por_safra, on=["codigo_siafi", "safra"], how="left")
    painel["acionou"] = painel["beneficiarios"].notna().astype(int)
    painel[["beneficiarios", "valor_pago"]] = painel[["beneficiarios", "valor_pago"]].fillna(0)
    painel = painel.merge(mun, on="codigo_siafi", how="inner")
    painel["uf"] = painel["codigo_uf"].map(UF_SIGLA)

    relatorio = {
        "arquivos_mensais_com_pagamento": int(mensal["mes"].nunique()),
        "linhas_municipio_mes": int(len(mensal)),
        "episodios_de_pagamento": int(len(ep)),
        "episodios_fora_do_periodo": int((~ep["safra"].isin(safras)).sum()),
        "municipios_no_programa": int(len(universo)),
        "municipios_sem_coordenadas_descartados": len(sem_coord),
        "safras": [safras[0], safras[-1]],
        "linhas_painel": int(len(painel)),
        "taxa_acionamento": round(float(painel["acionou"].mean()), 4),
    }
    return painel, relatorio


UF_SIGLA = {
    11: "RO", 12: "AC", 13: "AM", 14: "RR", 15: "PA", 16: "AP", 17: "TO", 21: "MA", 22: "PI", 23: "CE",
    24: "RN", 25: "PB", 26: "PE", 27: "AL", 28: "SE", 29: "BA", 31: "MG", 32: "ES", 33: "RJ", 35: "SP",
    41: "PR", 42: "SC", 43: "RS", 50: "MS", 51: "MT", 52: "GO", 53: "DF",
}
