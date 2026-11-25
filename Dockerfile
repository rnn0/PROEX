FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src ./src
COPY api ./api
COPY dashboard ./dashboard
COPY .streamlit ./.streamlit
COPY docker ./docker
RUN chmod +x docker/*.sh

# data/, models/ e reports/ são volumes: os dados são baixados e o modelo é treinado na primeira subida
EXPOSE 8000 8501
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
