FROM python:3.11-slim

WORKDIR /app

# Copiar requirements
COPY api/requirements.txt /app/api/requirements.txt

# Instalar dependencias
RUN pip install --no-cache-dir -r /app/api/requirements.txt

# Copiar todo el proyecto
COPY . /app

# Arrancar la API
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
