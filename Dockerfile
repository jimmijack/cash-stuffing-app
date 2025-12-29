FROM python:3.9-slim

WORKDIR /app

# NEU: curl installieren für den Healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Datenverzeichnis
RUN mkdir -p /data

EXPOSE 8501

# Healthcheck (benötigt curl)
HEALTHCHECK CMD curl --fail http://localhost:8501/_stcore/health

ENTRYPOINT ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
