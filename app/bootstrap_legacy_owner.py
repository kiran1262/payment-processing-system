"""One-time local admin command to claim the migrated Legacy demo workspace.

Usage (PowerShell):
  $env:LEGACY_OWNER_NAME = "Workspace Owner"
  $env:LEGACY_OWNER_EMAIL = "owner@example.com"
  $env:LEGACY_OWNER_PASSWORD = "<strong unique password>"
  python -m app.bootstrap_legacy_owner

Run only on a trusted machine with access to the target DATABASE_URL. Never commit
these environment values or run this command from an untrusted/public web process.
"""
import os

from .auth import bootstrap_legacy_owner
from .database import SessionLocal


def main() -> None:
    name = os.environ.get("LEGACY_OWNER_NAME", "").strip()
    email = os.environ.get("LEGACY_OWNER_EMAIL", "").strip()
    password = os.environ.get("LEGACY_OWNER_PASSWORD", "")
    if not name or not email or len(password) < 12:
        raise SystemExit(
            "Set LEGACY_OWNER_NAME, LEGACY_OWNER_EMAIL, and a LEGACY_OWNER_PASSWORD "
            "of at least 12 characters."
        )

    db = SessionLocal()
    try:
        user = bootstrap_legacy_owner(db, name, email, password)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        db.close()

    print(f"Legacy workspace owner created for {user.email}. Sign in through the dashboard.")


if __name__ == "__main__":
    main()
