"""Vercel FastAPI entrypoint; all routes are served by the existing ASGI app."""

from app.main import app

__all__ = ["app"]
