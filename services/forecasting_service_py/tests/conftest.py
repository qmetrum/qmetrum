"""Pytest setup.

Bind the ORM engine to a throwaway SQLite DB *before* any app module imports
app.db.database (which reads DATABASE_URL at import time), and make sure Cognito
is unconfigured so the local-dev X-User-Id auth path is active.
"""

import os
import tempfile

_TEST_DB = os.path.join(tempfile.gettempdir(), "qsight_var_backtest_test.db")
if os.path.exists(_TEST_DB):
    os.remove(_TEST_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

# Force the local-dev auth path (CognitoAuthMiddleware passes through, handlers
# honor X-User-Id). The app calls load_dotenv() at import, which would re-read
# COGNITO_* from a local .env — but with override=False it won't clobber vars
# already present, so we SET them empty (present-but-falsy) rather than pop them.
# is_cognito_configured() is bool(region and user_pool_id) -> empty => False.
for _k in ("COGNITO_USER_POOL_ID", "COGNITO_REGION", "COGNITO_APP_CLIENT_ID", "AWS_REGION"):
    os.environ[_k] = ""
