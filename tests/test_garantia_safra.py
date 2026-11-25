import io
import zipfile

import pandas as pd

from src.data import garantia_safra as gs


def test_identifica_colunas_com_acentos_e_variacoes():
    mapa = gs._identificar_colunas(["MÊS REFERÊNCIA", "UF", "CÓDIGO MUNICÍPIO SIAFI", "NOME MUNICÍPIO",
                                    "NIS FAVORECIDO", "NOME FAVORECIDO", "VALOR PARCELA"])
    assert mapa["codigo_siafi"] == "CÓDIGO MUNICÍPIO SIAFI"
    assert mapa["valor"] == "VALOR PARCELA"
    assert mapa["nis"] == "NIS FAVORECIDO"
    assert mapa["nome_municipio"] == "NOME MUNICÍPIO"


def test_valor_em_formato_brasileiro():
    s = gs._valor_para_float(pd.Series(["1.200,00", "850,00", "170,5"]))
    assert s.tolist() == [1200.0, 850.0, 170.5]


def test_agrega_arquivo_zip_do_portal(tmp_path):
    csv = ("MÊS REFERÊNCIA;UF;CÓDIGO MUNICÍPIO SIAFI;NOME MUNICÍPIO;NIS FAVORECIDO;NOME FAVORECIDO;VALOR PARCELA\n"
           "202403;CE;1389;QUIXADÁ;111;A;1.200,00\n"
           "202403;CE;1389;QUIXADÁ;222;B;1.200,00\n"
           "202403;PB;2051;SOUSA;333;C;1.200,00\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("202403_GarantiaSafra.csv", csv.encode("latin-1"))
    arq = tmp_path / "202403_GarantiaSafra.zip"
    arq.write_bytes(buf.getvalue())
    agg = gs.agregar_arquivo(arq).set_index("codigo_siafi")
    assert agg.loc[1389, "beneficiarios"] == 2
    assert agg.loc[1389, "valor"] == 2400.0
    assert agg.loc[2051, "mes"] == "202403"


def test_mes_do_pagamento_define_a_safra():
    # folhas de dez/2021 e jan/2022 pagaram a safra 2020/2021; mar/2024 pagou a 2022/2023
    assert gs.safra_do_mes(2021, 12) == 2021
    assert gs.safra_do_mes(2022, 1) == 2021
    assert gs.safra_do_mes(2024, 3) == 2023


def _mensal(linhas):
    return pd.DataFrame(linhas, columns=["codigo_siafi", "mes", "beneficiarios", "parcelas", "valor"])


def test_episodios_juntam_parcelas_e_residuos():
    mensal = _mensal([
        (1, "202112", 1000, 1000, 850_000.0), (1, "202201", 1000, 1000, 850_000.0),  # safra 2021 em 2 folhas
        (1, "202205", 20, 20, 17_000.0),       # resíduo (desbloqueio) -> continua safra 2021
        (1, "202403", 1100, 1100, 1_320_000.0),  # safra 2023
    ])
    ep = gs.construir_episodios(mensal)
    assert sorted(ep["safra"]) == [2021, 2023]
    assert ep.loc[ep["safra"] == 2021, "valor"].item() == 1_717_000.0
