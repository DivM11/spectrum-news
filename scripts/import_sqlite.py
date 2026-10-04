"""One-time copy of an existing SQLite file into the SQLAlchemy store
(SQLite or Postgres). Preserves row ids so history links stay valid.

Usage:
  uv run python scripts/import_sqlite.py --from data/spectrum.db --to postgresql+psycopg://...
  (omit --to to verify against a temp SQLite copy instead)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import text  # noqa: E402

from spectrum_news import db as db_mod  # noqa: E402
from spectrum_news import schema  # noqa: E402


def copy_table(src: sqlite3.Connection, table_name: str, engine) -> int:
    cols = [c.name for c in schema.metadata.tables[table_name].columns]
    rows = src.execute(
        f"SELECT {', '.join(cols)} FROM {table_name}"  # noqa: S608 - internal names only
    ).fetchall()
    if not rows:
        return 0
    table = schema.metadata.tables[table_name]
    with engine.begin() as conn:
        conn.execute(table.insert(), [dict(zip(cols, r)) for r in rows])
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="src", required=True, help="SQLite file to import")
    parser.add_argument("--to", dest="dst", default="", help="Target URL (default: temp SQLite check)")
    args = parser.parse_args()

    if not os.path.exists(args.src):
        raise SystemExit(f"SQLite file not found: {args.src}")

    dst = args.dst or "sqlite://"
    db_mod.init_db(dst)
    engine = db_mod.engine_for(dst)
    src = sqlite3.connect(args.src)
    try:
        total = 0
        for table_name in schema.TABLES_IN_LOAD_ORDER:
            try:
                n = copy_table(src, table_name, engine)
            except sqlite3.OperationalError as exc:
                print(f"skip {table_name}: {exc}")
                continue
            print(f"{table_name}: {n} rows")
            total += n
        if engine.dialect.name == "postgresql":
            # Explicit ids don't advance serial sequences; reset them to max(id).
            # Table names are internal constants (see schema.py), never user input.
            with engine.begin() as conn:
                for table_name in ("search_runs", "articles", "analyses"):
                    conn.execute(text(
                        "SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                        "(SELECT COALESCE(MAX(id), 1) FROM {t}))".format(t=table_name)))
                    print(f"{table_name}: sequence reset")
    finally:
        src.close()
    print(f"imported {total} rows into {dst if args.dst else 'throwaway SQLite (verify-only)'}")


if __name__ == "__main__":
    main()
