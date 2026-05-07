# syntax=docker/dockerfile:1.6
# ---------------------------------------------------------------------------
# Qmetrum forecasting backend — production image.
#
# Multistage to keep the final image lean (Python 3.11, system libs only the
# scientific stack actually needs at runtime). The entrypoint runs Alembic
# migrations before starting Uvicorn so a fresh deploy auto-upgrades the DB.
# ---------------------------------------------------------------------------

# ---- builder ---------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Build deps — needed only at install time. Final image won't carry these.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        gfortran \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install into a virtualenv so we can copy the whole tree to the runtime image.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# ---- runtime ---------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

# Minimal runtime libs (libgomp for numpy/sklearn threading; libpq5 for
# psycopg2; ca-certificates for outbound HTTPS).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
        libpq5 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Bring the prepared virtualenv from the builder.
COPY --from=builder /opt/venv /opt/venv

# Non-root user
RUN groupadd --system --gid 1001 qmetrum \
    && useradd --system --uid 1001 --gid qmetrum --shell /bin/bash --create-home qmetrum

WORKDIR /app
COPY --chown=qmetrum:qmetrum . /app

# Ensure /app itself (not just its contents) is writable by the runtime user.
# Required so SQLite local-test mode can create qmetrum.db; harmless in
# production where DATABASE_URL points at managed Postgres.
RUN chown qmetrum:qmetrum /app && chmod +x /app/entrypoint.sh

USER qmetrum

EXPOSE 8000

# Healthcheck targets the cheap /healthz endpoint (App Runner / ALB use this).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status==200 else 1)"

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
