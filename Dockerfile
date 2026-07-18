FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY corvus_cronos/ corvus_cronos/
COPY corvus/ corvus/
COPY cronos/ cronos/
COPY scripts/ scripts/
COPY web/ web/
COPY api_server.py .

# Persistent volume for the CRONOS chain + CORVUS memory + nightly reports
VOLUME /data
ENV BRIDGE_DB_PATH=/data/negotiation.db \
    BRIDGE_MEMORY_DB_PATH=/data/corvus_memory.db

EXPOSE 8022
CMD ["uvicorn", "api_server:app", "--host", "0.0.0.0", "--port", "8022"]
