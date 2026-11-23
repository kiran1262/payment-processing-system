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
RATE_LIMIT_HASH_SECRET = os.environ.get("RATE_LIMIT_HASH_SECRET", "local-development-only-change-me")
