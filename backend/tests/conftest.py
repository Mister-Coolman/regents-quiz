"""Shared fixtures. Tests run against a throwaway copy of the real question
bank (backend/regentsqs.db, which isn't in git); tests that need it are
skipped when it's absent. The LLM is never called."""
import os
import shutil
import sqlite3
import sys

import pytest

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

REAL_DB = os.path.join(BACKEND, "regentsqs.db")

needs_db = pytest.mark.skipif(not os.path.exists(REAL_DB), reason="question bank not present")


@pytest.fixture
def db_copy(tmp_path, monkeypatch):
    """A private copy of the bank with empty session tables, wired into db."""
    if not os.path.exists(REAL_DB):
        pytest.skip("question bank not present")
    import db
    path = tmp_path / "regentsqs.db"
    shutil.copy2(REAL_DB, path)
    conn = sqlite3.connect(path)
    for table in ("session_questions", "session_messages", "sessions"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    return str(path)


@pytest.fixture
def client(db_copy, monkeypatch):
    import app as app_module
    import llm_client
    app_module.limiter.enabled = False
    monkeypatch.setattr(llm_client, "_budget", {"day": None, "used": 0})
    yield app_module.app.test_client()
    app_module.limiter.enabled = True


@pytest.fixture
def parsed(monkeypatch):
    """Set what the (stubbed) query parser returns."""
    import app as app_module

    def set_result(intent="generate", subject="Algebra I", topic="", qtype="MCQ", limit=3, reply=""):
        monkeypatch.setattr(app_module, "parse_query_with_ollama",
                            lambda *a, **k: (intent, subject, topic, qtype, limit, reply))
    set_result()
    return set_result
