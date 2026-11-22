FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends libreoffice-calc poppler-utils fonts-liberation fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

ARG INSTALL_DEV=false
COPY requirements.lock requirements-dev.lock ./
RUN if [ "$INSTALL_DEV" = "true" ]; then \
      pip install --no-cache-dir -r requirements-dev.lock; \
    else \
      pip install --no-cache-dir -r requirements.lock; \
    fi \
    && useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser scripts ./scripts
COPY --chown=appuser:appuser migrations ./migrations
COPY --chown=appuser:appuser docs/forms ./docs/forms
COPY --chown=appuser:appuser alembic.ini ./alembic.ini

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
