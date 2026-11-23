"""Operational maintenance commands for the demo application."""
from __future__ import annotations

import argparse

from sqlalchemy.orm import Session

from .database import SessionLocal
from .rate_limit import purge_expired_rate_limit_buckets


def main() -> None:
    parser = argparse.ArgumentParser(description="Payment demo maintenance commands")
    commands = parser.add_subparsers(dest="command", required=True)
    purge = commands.add_parser("purge-rate-limits", help="delete expired rate-limit buckets")
    purge.add_argument("--batch-size", type=int, default=1000)
    args = parser.parse_args()

    if args.command == "purge-rate-limits":
        with SessionLocal() as db:
            deleted = purge_expired_rate_limit_buckets(db, batch_size=args.batch_size)
        print(f"Deleted {deleted} expired rate-limit bucket(s).")


if __name__ == "__main__":
    main()
