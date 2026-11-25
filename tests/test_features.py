import numpy as np
import pandas as pd

from src.data.download import celula_grade
from src.features import build


def test_maior_sequencia_de_dias_secos():
    assert build._max_seguidos(np.array([1, 1, 0, 1, 1, 1, 0])) == 3
    assert build._max_seguidos(np.array([0, 0])) == 0


def test_janela_da_estacao():
    ini, fim = build._janela(2024, 4)
    assert ini == pd.Timestamp(2023, 10, 1)
    assert fim == pd.Timestamp(2024, 4, 30)


def test_historico_usa_so_safras_anteriores():
    base = pd.DataFrame({"codigo_siafi": [1, 1, 1, 1], "safra": [2020, 2021, 2022, 2023],
                         "acionou": [1, 0, 1, np.nan]})
    h = build.adicionar_historico(base)["historico_acionamento"].tolist()
    assert np.isnan(h[0])            # sem passado
    assert h[1:] == [1.0, 0.5, 2 / 3]  # a safra atual (sem alvo) usa as 3 anteriores


def test_features_de_chuva_respondem_a_seca():
    dias = pd.date_range("2019-10-01", "2021-06-30")
    mm = np.where(dias < pd.Timestamp("2020-10-01"), 5.0, 1.5)  # safra 2021 bem mais seca
    chuva = pd.DataFrame({"lat": -7.0, "lon": -39.375, "data": dias, "chuva_mm": mm})
    f = build.features_chuva_por_celula(chuva, [2020, 2021], mes_corte=4).set_index("safra")
    assert f.loc[2021, "chuva_pct_normal"] < 100 < f.loc[2020, "chuva_pct_normal"]
    assert f.loc[2021, "chuva_total_mm"] < f.loc[2020, "chuva_total_mm"]


def test_celula_da_grade_nasa_power():
    assert celula_grade(-7.12, -39.31) == (-7.0, -39.375)
