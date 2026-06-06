"""Delete career memory rows for one tenant (no ``psql`` required).

Uses the same stack as the API: SQLAlchemy + psycopg. Run from repo with
backend venv active, or let ``clear-career-memory-tenant.ps1`` invoke this file.

Example::

    .\\.venv\\Scripts\\python.exe scripts\\clear_career_memory_tenant.py --user-id d713ee46-...
    .\\.venv\\Scripts\\python.exe scripts\\clear_career_memory_tenant.py --env-file .env
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BACKEND_ROOT = Path(__file__).resolve().parent.parent

DELETES = [
    "DELETE FROM career_profile_questions WHERE user_id = :uid",
    "DELETE FROM career_facts WHERE user_id = :uid",
    "DELETE FROM career_timeline_entries WHERE user_id = :uid",
    "DELETE FROM career_discovery_profiles WHERE user_id = :uid",
    "DELETE FROM career_documents WHERE user_id = :uid",
]


def _normalize_sqlalchemy_url(url: str) -> str:
    """Route to psycopg3; plain ``postgresql://`` makes SQLAlchemy load psycopg2 (often missing)."""
    u = url.strip()
    if u.startswith("postgresql+psycopg://"):
        return u
    if u.startswith("postgresql+psycopg2://"):
        return "postgresql+psycopg://" + u.removeprefix("postgresql+psycopg2://")
    if u.startswith("postgresql://"):
        return "postgresql+psycopg://" + u.removeprefix("postgresql://")
    return u


# Hostnames copied from template .env files — not valid production targets.
_PLACEHOLDER_DB_HOSTS = frozenset(
    {
        "host",
        "your_host",
        "db_host",
        "hostname",
        "db_host_here",
        "postgres_host",
        "your-db-host",
    }
)


def _sqlalchemy_url_hostname(url: str) -> str | None:
    if "://" not in url:
        return None
    _, rest = url.split("://", 1)
    netloc = rest.split("/", 1)[0]
    if not netloc:
        return None
    return urlparse(f"http://{netloc}").hostname


def _reject_placeholder_db_host(url: str) -> None:
    host = _sqlalchemy_url_hostname(url)
    if host is not None and host.lower() in _PLACEHOLDER_DB_HOSTS:
        print(
            f"ATLAS_DATABASE_URL uses hostname {host!r}, which looks like a template placeholder.\n"
            "Fix the value in backend/.env: the part after @ should be your real server, e.g. "
            "127.0.0.1:5432 or localhost:5432 — not `host`.\n"
            "Example: ATLAS_DATABASE_URL=postgresql+psycopg://atlas:YOUR_PASSWORD@127.0.0.1:5432/atlas\n"
            "If .env has this variable twice, the script uses the **last** non-comment line.\n"
            "Docker edge case (service truly named `host`): add --skip-hostname-placeholder-check "
            "or use -SkipHostnamePlaceholderCheck in PowerShell.",
            file=sys.stderr,
        )
        sys.exit(2)


def _resolve_database_url(*, env_file: Path | None, explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    if env_file:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(BACKEND_ROOT / ".env", override=False)
    url = (os.environ.get("ATLAS_DATABASE_URL") or "").strip()
    if not url:
        print(
            "Missing database URL: set ATLAS_DATABASE_URL or pass --database-url "
            "or use --env-file with that variable.",
            file=sys.stderr,
        )
        sys.exit(2)
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="Clear career memory for one tenant.")
    parser.add_argument(
        "--user-id",
        default="d713ee46-77c9-50cb-ac74-17fa99329375",
        help="Tenant UUID (default: seeded local user).",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="SQLAlchemy URL (postgresql+psycopg://...). Overrides env.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Optional .env path to load before reading ATLAS_DATABASE_URL.",
    )
    parser.add_argument(
        "--skip-hostname-placeholder-check",
        action="store_true",
        help="Allow hostnames that look like .env templates (rare: Docker service named 'host').",
    )
    args = parser.parse_args()

    try:
        uid = UUID(args.user_id)
    except ValueError as exc:
        print(f"Invalid --user-id: {exc}", file=sys.stderr)
        sys.exit(2)

    db_url = _normalize_sqlalchemy_url(
        _resolve_database_url(
            env_file=args.env_file,
            explicit=args.database_url or None,
        )
    )
    if not args.skip_hostname_placeholder_check:
        _reject_placeholder_db_host(db_url)

    engine = create_engine(db_url)
    with engine.begin() as conn:
        for stmt in DELETES:
            conn.execute(text(stmt), {"uid": uid})

    print(f"Career memory cleared for user_id={uid}")


if __name__ == "__main__":
    main()
