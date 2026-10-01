"""Apply numbered schema migrations to the question database.

The database ships inside the Docker image and isn't in git, so the migrated
file *is* the release artifact. Migrations therefore run offline, here, never
at app start: the app only checks the version (db.SCHEMA_VERSION) and refuses
to boot on an older file, which keeps a mismatched image from taking traffic.

Each file in migrations/ is NNNN_name.sql. Pending ones run in order inside a
single transaction, which also sets PRAGMA user_version, so a failing
migration leaves the database exactly as it was. The file is copied to
regentsqs.db.bak-pre-NNNN first anyway.

Only additive statements belong in a migration (CREATE ... IF NOT EXISTS,
ALTER TABLE ... ADD COLUMN, data backfills). Never rebuild the questions
table: ids must survive, because download links and saved progress use them.

Usage:
  python migrate.py            # apply pending migrations
  python migrate.py --status   # show current and latest version
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS_DIR = os.path.join(BASE_DIR, "migrations")
NAME_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def migrations():
    """[(version, path)] in order."""
    out = []
    for name in sorted(os.listdir(MIGRATIONS_DIR)):
        m = NAME_RE.match(name)
        if m:
            out.append((int(m.group(1)), os.path.join(MIGRATIONS_DIR, name)))
    versions = [v for v, _ in out]
    if versions != list(range(1, len(versions) + 1)):
        sys.exit(f"migrations must be numbered 0001.. with no gaps, found {versions}")
    return out


def latest_version():
    found = migrations()
    return found[-1][0] if found else 0


def statements(sql):
    """Split a script into statements. executescript() would commit on its
    own and break the single transaction."""
    out, buf = [], ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip() and not buf.strip().startswith("--"):
        out.append(buf.strip())
    return out


def current_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(db_path):
    conn = sqlite3.connect(db_path, isolation_level=None)
    version = current_version(conn)
    pending = [(v, p) for v, p in migrations() if v > version]
    if not pending:
        print(f"[migrate] {os.path.basename(db_path)} is at version {version}; nothing to do")
        return version

    backup = f"{db_path}.bak-pre-{pending[0][0]:04d}"
    conn.close()
    shutil.copy2(db_path, backup)
    print(f"[migrate] backed up to {os.path.basename(backup)}")

    conn = sqlite3.connect(db_path, isolation_level=None)
    try:
        conn.execute("BEGIN")
        for v, path in pending:
            with open(path) as f:
                for stmt in statements(f.read()):
                    conn.execute(stmt)
            conn.execute(f"PRAGMA user_version = {v}")
            print(f"[migrate] applied {os.path.basename(path)}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        conn.close()
        raise
    version = current_version(conn)
    conn.close()
    print(f"[migrate] now at version {version}")
    return version


def main():
    import db
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--db", default=db.DB_PATH)
    args = parser.parse_args()
    if args.status:
        conn = sqlite3.connect(args.db)
        print(f"current {current_version(conn)}, latest {latest_version()}, "
              f"app requires {db.SCHEMA_VERSION}")
        conn.close()
        return
    migrate(args.db)


if __name__ == "__main__":
    main()
