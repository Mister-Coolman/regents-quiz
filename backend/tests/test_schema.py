import os
import shutil
import sqlite3

import pytest

import migrate
from conftest import needs_db
from tests import golden


@needs_db
def test_math_payloads_match_golden(db_copy):
    """Every question's public payload and grading is unchanged. After an
    intentional change, review it, then run `python -m tests.golden --update`."""
    missing, added, changed = golden.compare(golden.load(), golden.compute(db_copy))
    assert not missing, f"questions removed: {missing[:20]}"
    assert not changed, f"payload or grading changed: {changed[:20]}"


@needs_db
def test_app_refuses_an_old_schema(db_copy, monkeypatch):
    import db
    conn = sqlite3.connect(db_copy)
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    with pytest.raises(db.SchemaTooOld):
        db.init_db()


@needs_db
def test_migrations_are_idempotent(db_copy):
    before = migrate.current_version(sqlite3.connect(db_copy))
    assert migrate.migrate(db_copy) == before == migrate.latest_version()


@needs_db
def test_failed_migration_changes_nothing(db_copy, tmp_path, monkeypatch):
    mig_dir = tmp_path / "migrations"
    shutil.copytree(migrate.MIGRATIONS_DIR, mig_dir)
    next_no = migrate.latest_version() + 1
    (mig_dir / f"{next_no:04d}_broken.sql").write_text(
        "CREATE TABLE should_not_exist (x INTEGER);\n"
        "INSERT INTO no_such_table VALUES (1);\n"
    )
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", str(mig_dir))
    with pytest.raises(sqlite3.OperationalError):
        migrate.migrate(db_copy)

    conn = sqlite3.connect(db_copy)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "should_not_exist" not in tables
    assert migrate.current_version(conn) == next_no - 1
    conn.close()
    assert os.path.exists(f"{db_copy}.bak-pre-{next_no:04d}")
