FROM python:3.11-slim

WORKDIR /app

# Install system deps for psycopg2 and ML libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Single worker: per-user task/plan state lives in an in-process dict
# (core/state.py's StateStore) with no shared cache backing it. Multiple
# worker processes each get their own copy, so a request can land on a
# "cold" worker that has never seen this user and has to redo the full
# pipeline — that's what caused the dashboard to show 0 tasks until a
# reload happened to hit an already-warm worker. Don't raise this without
# first moving that state into Redis/Postgres-backed shared storage.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
