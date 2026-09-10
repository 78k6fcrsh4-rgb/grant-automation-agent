"""Grant Award Management Application"""
from pathlib import Path

from dotenv import load_dotenv

# Loaded HERE, in the package __init__, and not in main.py.
#
# Several modules read their configuration at import time — db.py builds the
# engine from DATABASE_URL, grant_repository resolves GMA_PERSISTENCE and
# GRANT_TTL_MINUTES — and main.py's own load_dotenv() ran *after* its
# `from app.db import ...` line. So .env was invisible to every one of them
# and the fallbacks silently won. That was survivable while the fallback was
# a SQLite file; with PostgreSQL required it surfaces as
# `role "postgres" does not exist` on startup.
#
# An explicit path rather than the default upward search, so it does not
# depend on which directory uvicorn was started from.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

__version__ = "2.8.0"
