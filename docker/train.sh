#!/bin/sh
# Baixa os dados públicos e treina. Se já houver modelo, só treina de novo com PROEX_RETRAIN=1.
set -e
if [ -f models/metadata.json ] && [ "${PROEX_RETRAIN:-0}" != "1" ]; then
  echo "Modelo já treinado (models/metadata.json). Use PROEX_RETRAIN=1 para refazer."
  exit 0
fi
if [ "${PROEX_SYNTHETIC:-0}" = "1" ]; then
  python -m src.pipeline --synthetic
else
  python -m src.pipeline --download
fi
