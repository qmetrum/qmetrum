import logging
import os
import signal
import time
from threading import Event

from app.db.database import init_db
from app.main import (
    FORECAST_JOB_DISPATCH_MODE,
    FORECAST_JOB_WORKER_POLL_SECONDS,
    _ensure_default_user,
    process_next_portfolio_forecast_job,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_stop_event = Event()


def _handle_signal(signum, _frame):
    logger.info("Forecast jobs worker received signal %s, stopping...", signum)
    _stop_event.set()


def run_worker_loop() -> None:
    init_db()
    _ensure_default_user()

    poll_seconds = max(0.1, float(os.getenv("FORECAST_JOB_WORKER_POLL_SECONDS", str(FORECAST_JOB_WORKER_POLL_SECONDS))))
    idle_log_every = max(1, int(os.getenv("FORECAST_JOB_WORKER_IDLE_LOG_EVERY", "60")))
    run_once = os.getenv("FORECAST_JOB_WORKER_ONCE", "false").strip().lower() in {"1", "true", "yes", "on"}

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info(
        "Forecast jobs worker started (dispatch_mode=%s, poll=%.2fs, run_once=%s)",
        FORECAST_JOB_DISPATCH_MODE,
        poll_seconds,
        run_once,
    )
    if FORECAST_JOB_DISPATCH_MODE == "threadpool":
        logger.warning(
            "FORECAST_JOB_DISPATCH_MODE=threadpool: API may execute jobs itself. "
            "Set FORECAST_JOB_DISPATCH_MODE=external_worker to use this worker as the dispatcher."
        )

    idle_cycles = 0
    while not _stop_event.is_set():
        job_id = process_next_portfolio_forecast_job()
        if job_id:
            idle_cycles = 0
            logger.info("Processed forecast job %s", job_id)
            if run_once:
                break
            continue

        idle_cycles += 1
        if idle_cycles % idle_log_every == 0:
            logger.info("Forecast jobs worker idle (no queued jobs).")
        if run_once:
            break
        _stop_event.wait(poll_seconds)

    logger.info("Forecast jobs worker stopped.")


if __name__ == "__main__":
    run_worker_loop()

