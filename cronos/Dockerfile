FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .

ENV CRONOS_DB_PATH=/data/cronos/cronos.db
CMD ["python", "main.py"]
