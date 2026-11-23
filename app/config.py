import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{(BASE_DIR / 'payment.db').as_posix()}",
)
APP_NAME = "Payment"


# Used only to pseudonymize rate-limit identities before persistence.
# Production deployments must provide a high-entropy secret through the secret manager.
APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
_configured_rate_limit_secret = os.environ.get("RATE_LIMIT_HASH_SECRET", "").strip()
if APP_ENV == "production" and not _configured_rate_limit_secret:
    raise RuntimeError("RATE_LIMIT_HASH_SECRET must be configured in production.")
RATE_LIMIT_HASH_SECRET = _configured_rate_limit_secret or "local-development-only-change-me"
