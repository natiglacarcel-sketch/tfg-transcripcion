#!/bin/bash

set -e

BASE_DIR="/home/nati/tfg-transcripcion"
INPUT_DIR="$BASE_DIR/data/input"
OUTPUT_DIR="$BASE_DIR/data/output"

cd "$BASE_DIR"

echo "==> Sincronizando con GitHub..."
git pull

echo "==> Buscando audios en data/input..."

for audio in "$INPUT_DIR"/*; do
  [ -f "$audio" ] || continue

  nombre=$(basename "$audio")
  nombre_sin_ext="${nombre%.*}"
  salida="$OUTPUT_DIR/${nombre_sin_ext}.txt"

  if [ -f "$salida" ]; then
    echo "Ya existe transcripción para $nombre, se omite."
    continue
  fi

  echo "Transcribiendo $nombre ..."

  docker run --rm \
    -v "$BASE_DIR:/srv/files:Z" \
    whisper-local \
    "/srv/files/data/input/$nombre" \
    --output_dir /srv/files/data/output \
    --language es \
    --model small \
    --compute_type int8
done

echo "==> Subiendo resultados a GitHub..."
git add data/output
git commit -m "Añadidas nuevas transcripciones" || true
git push

echo "==> Proceso terminado."
