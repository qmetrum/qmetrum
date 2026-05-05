Archived backend files that are currently not referenced by the active runtime.

Moved on: 2026-02-19

Included:
- `services/forecasting_service_py/app/utils/data_layer/*.py` (legacy data-layer snapshot assembler path)
- `services/risk_service_r/app/r_client.py` (legacy metrics adapter)
- `orchestration/db/run_nightly_pipeline.py` (stale nightly job script)
- `orchestration/db/models.py` (stale duplicate schema)
- `orchestration/db/database.py` (stale duplicate DB helper)

Notes:
- `services/forecasting_service_py/app/archive/core/*` was already in an archive namespace and was left in place.
- Active fetch path remains `services/forecasting_service_py/app/utils/data_fetcher.py` via `services/forecasting_service_py/app/services/market_store.py`.
