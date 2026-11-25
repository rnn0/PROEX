.PHONY: install dados treinar sintetico api dashboard testes lint docker
install:   ; pip install -r requirements-dev.txt
dados:     ; python -m src.data.download
treinar:   ; python -m src.pipeline
sintetico: ; python -m src.pipeline --synthetic
api:       ; uvicorn api.main:app --reload --port 8000
dashboard: ; streamlit run dashboard/app.py
testes:    ; pytest -q
lint:      ; ruff check .
docker:    ; docker compose up --build
