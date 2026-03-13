FROM python:3.11-slim

WORKDIR /app

# Instalar utilidades necesarias:
# - docker.io para poder lanzar whisper-local desde la API
# - git para git add / commit / push
# - openssh-client para autenticación SSH con GitHub
RUN apt-get update && apt-get install -y \
    docker.io \
    git \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar dependencias Python
COPY api/requirements.txt /app/api/requirements.txt

# Instalar dependencias Python
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copiar el proyecto completo
COPY . /app

# Configuración de git dentro del contenedor
RUN git config --global --add safe.directory /app
RUN git config --global user.name "nati"
RUN git config --global user.email "natiglacarcel-sketch@users.noreply.github.com"

# Arranque de FastAPI
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
