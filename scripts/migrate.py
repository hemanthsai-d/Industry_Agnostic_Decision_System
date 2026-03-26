from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_NAME_RE = re.compile(r"^(\d+)_.*\.sql$")


def ensure_migration_table(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              checksum TEXT NOT NULL,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
    conn.commit()


def list_migration_files() -> list[Path]:
    files = []
    for p in MIGRATIONS_DIR.glob("*.sql"):
        if MIGRATION_NAME_RE.match(p.name):
            files.append(p)
    files.sort(key=lambda x: x.name)
    return files


def get_applied(conn: psycopg.Connection) -> dict[str, dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT version, checksum, applied_at FROM schema_migrations;")
        rows = cur.fetchall()
    return {r["version"]: r for r in rows}


def version_from_filename(name: str) -> str:
    m = MIGRATION_NAME_RE.match(name)
    if not m:
        raise ValueError(f"Invalid migration filename: {name}")
    return m.group(1)


def apply_migrations(dsn: str) -> None:
    files = list_migration_files()
    if not files:
        print("No migration files found.")
        return

    with psycopg.connect(dsn) as conn:
        ensure_migration_table(conn)
        applied = get_applied(conn)

        for file in files:
            version = version_from_filename(file.name)
            sql = file.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()

            if version in applied:
                if applied[version]["checksum"] != checksum:
                    raise RuntimeError(
                        f"Checksum mismatch for already-applied migration {file.name}. "
                        "Do not modify applied migrations; create a new versioned file."
                    )
                print(f"SKIP  {file.name} (already applied)")
                continue

            print(f"APPLY {file.name}")
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    """
                    INSERT INTO schema_migrations (version, name, checksum)
                    VALUES (%s, %s, %s);
                    """,
                    (version, file.name, checksum),
                )
            conn.commit()

    print("Migrations complete.")


def show_status(dsn: str) -> None:
    files = list_migration_files()
    with psycopg.connect(dsn) as conn:
        ensure_migration_table(conn)
        applied = get_applied(conn)

    for file in files:
        version = version_from_filename(file.name)
        state = "APPLIED" if version in applied else "PENDING"
        print(f"{state:8} {file.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SQL migrations")
    parser.add_argument("command", choices=["migrate", "status"], nargs="?", default="migrate")
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        if args.command == "status":
            show_status(dsn)
        else:
            apply_migrations(dsn)
    except psycopg.OperationalError as exc:
        print(
            "Database connection failed. Ensure Postgres is running and POSTGRES_DSN is correct.\n"
            f"Details: {exc}"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
