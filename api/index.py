"""Vercel entry point: Vercel serves the ASGI `app` from this file at /api."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.webhook import app  # noqa: E402,F401
