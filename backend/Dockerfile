FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    APP_PROCESS=api \
    LOG_FORMAT=json \
    PIPELINE_WORKER_MODE=external

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml /app/backend/pyproject.toml
RUN python -m pip install --upgrade pip \
    && python -m pip install /app/backend

COPY backend /app/backend

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "if [ \"${APP_PROCESS:-api}\" = \"worker\" ]; then exec python -m backend.worker; else exec uvicorn backend.main:app --host 0.0.0.0 --port \"${PORT:-8080}\"; fi"]
