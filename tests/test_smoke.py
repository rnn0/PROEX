"""Smoke test ponta a ponta: pipeline com dados sintéticos + API, num diretório temporário."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

SCRIPT = textwrap.dedent("""
    from fastapi.testclient import TestClient
    from src import pipeline
    meta = pipeline.run(sintetico=True)
    assert meta["modo_dados"] == "sintetico"
    assert meta["metricas_validacao"]["roc_auc"] > 0.6, meta

    from api.main import app
    c = TestClient(app)
    assert c.get("/health").json()["status"] == "ok"
    r = c.get("/respostas").json()
    assert "pergunta_1" in r and "pergunta_2" in r
    mun = c.get("/municipios").json()
    assert len(mun) > 0
    det = c.get(f"/municipios/{mun[0]['codigo_ibge']}").json()
    assert det["historico"]
    assert c.get("/municipios/1").status_code == 404
    risco = c.get("/risco/safra-atual?limite=5").json()
    assert len(risco["municipios"]) <= 5
    seca = c.post("/prever", json={"chuva_total_mm": 150, "chuva_pct_normal": 30, "dias_com_chuva": 10,
                                   "max_dias_secos_seguidos": 70, "chuva_trimestre_pct_normal": 25,
                                   "historico_acionamento": 0.6}).json()
    chuvoso = c.post("/prever", json={"chuva_total_mm": 900, "chuva_pct_normal": 150, "dias_com_chuva": 80,
                                      "max_dias_secos_seguidos": 8, "chuva_trimestre_pct_normal": 150,
                                      "historico_acionamento": 0.6}).json()
    assert seca["prob_acionar"] > chuvoso["prob_acionar"], (seca, chuvoso)
    print("OK")
""")


def test_pipeline_e_api_ponta_a_ponta(tmp_path):
    env = {**os.environ, "PROEX_ROOT": str(tmp_path), "PROEX_SYNTH_N": "50",
           "PROEX_SAFRA_INICIAL": "2017", "PYTHONPATH": str(RAIZ)}
    r = subprocess.run([sys.executable, "-c", SCRIPT], cwd=RAIZ, env=env, capture_output=True, text=True,
                       timeout=900)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-3000:]
    assert (tmp_path / "reports" / "respostas.md").exists()
    assert (tmp_path / "models" / "modelo_risco.joblib").exists()
