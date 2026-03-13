FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y docker.io git openssh-client && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt /app/api/requirements.txt
RUN pip install --no-cache-dir -r /app/api/requirements.txt

COPY . /app

RUN git config --global --add safe.directory /app
RUN git config --global user.name "nati"
RUN git config --global user.email "natiglacarcel-sketch@users.noreply.github.com"

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
