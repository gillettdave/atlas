"""Ensure settings can load when importing `app` (PostgreSQL-only)."""

from __future__ import annotations

import os

# Default dev URL so `get_settings()` passes assert_postgres in unit tests.
os.environ.setdefault(
    "ATLAS_DATABASE_URL",
    "postgresql+psycopg://atlas:atlas@localhost:5432/atlas",
)
os.environ.setdefault("ATLAS_JWT_SECRET", "x" * 32)
os.environ.setdefault("ATLAS_AUTH_ALLOW_SEEDED_WITHOUT_BEARER", "true")
