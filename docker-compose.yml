FROM python:3.11-slim

WORKDIR /app

# Instalar cliente Docker
RUN apt-get update && apt-get install -y docker.io && rm -rf /var/lib/apt/lists/*

# Copiar requirements
COPY api/requirements.txt /app/api/requirements.txt

# Instalar dependencias Python
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copiar el proyecto completo
COPY . /app

# Arrancar la API
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
