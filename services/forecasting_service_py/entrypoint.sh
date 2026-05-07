#!/usr/bin/env bash
# Container entrypoint: run alembic migrations, then exec the main command.
#
# - `alembic upgrade head` is idempotent — safe to run on every container
#   start. It catches up a fresh RDS instance and is a no-op once schema is
#   current.
# - We bail loudly if migrations fail so App Runner marks the deploy bad
#   (instead of starting a service against a stale schema).
# - `exec` replaces the shell with uvicorn so signals (SIGTERM from
#   App Runner during scale-in) reach the Python process directly.

set -euo pipefail

echo "[entrypoint] running alembic migrations…"
alembic upgrade head
echo "[entrypoint] migrations complete."

echo "[entrypoint] starting: $*"
exec "$@"
