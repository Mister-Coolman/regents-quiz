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


# ---- A small synthetic bank, for tests that must run without the real one ----

SCRIPTS = os.path.join(os.path.dirname(BACKEND), "scripts")
sys.path.insert(0, SCRIPTS)

MATH_ROWS = [
    # subject, topic, month, year, type, image, key, explanation, question_no
    ("Algebra I", "Creating Equations", "June", 2024, "MCQ", "images/a1.png", "2",
     "**What's being asked** x\n**Approach** y\n**Work**\n1. a\n2. b\n**Answer** Choice 2", 1),
    ("Algebra I", "Systems of Equations", "June", 2024, "MCQ", "images/a2.png", "4", None, 2),
    ("Algebra I", "Creating Equations", "January", 2023, "MCQ", "images/a3.png", "1", None, 7),
    ("Geometry", "Constructions", "August", 2022, "CRQ", "images/g1.png", "N/A", "**Answer** see", 30),
]

PASSAGE_A = [f"Line {n} of the story, which goes on for a while." for n in range(1, 13)]
PASSAGE_B = [f"Line {n} of the poem" for n in range(1, 9)]


def ela_bundle(bundle_dir):
    """A two-passage ELA bundle with five questions, crops on disk."""
    os.makedirs(os.path.join(bundle_dir, "crops"), exist_ok=True)
    questions = []
    stems = {
        1: ("A", "In lines 3 through 5, the narrator suggests that"),
        2: ("A", "The central idea of the passage is"),
        3: ("A", "Line 12 mainly serves to"),
        4: ("B", "In lines 1 and 2, the speaker"),
        5: ("B", "The poem's structure"),
    }
    for no, (label, stem) in stems.items():
        crop = f"crops/q{no:02d}.png"
        with open(os.path.join(bundle_dir, crop), "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        questions.append({
            "question_no": no, "part": 1, "stimulus": label, "image": crop,
            "question_text": stem, "choices": ["one", "two", "three", "four"],
            "correct_answer": str((no % 4) + 1), "standard": "RL.1",
        })
    return {
        "exam": {"subject": "ELA", "month": "June", "year": 2026, "code": "626", "framework": "Next Generation"},
        "stimuli": [
            {"label": "A", "kind": "literary", "title": "The Story", "author": "A. Writer",
             "lines": [{"n": i + 1, "text": t} for i, t in enumerate(PASSAGE_A)],
             "footnotes": ["1 a note"], "credit": "From The Story by A. Writer. Copyright 2001."},
            {"label": "B", "kind": "poem", "title": "The Poem", "author": "B. Poet",
             "lines": [{"n": i + 1, "text": t, "stanza_break": i == 4} for i, t in enumerate(PASSAGE_B)],
             "footnotes": [], "credit": "\"The Poem\" by B. Poet <i>Journal</i>"},
        ],
        "questions": questions,
    }


def build_synthetic_db(path, static_dir, with_ela=True, verify=True):
    import migrate
    conn = sqlite3.connect(path)
    with open(os.path.join(migrate.MIGRATIONS_DIR, "0001_baseline.sql")) as f:
        conn.executescript(f.read())
    conn.executemany("""INSERT INTO questions (subject, topic, month, year, type, question_image_path,
                        correct_answer, explanation, question_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", MATH_ROWS)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()
    migrate.migrate(str(path))
    if with_ela:
        import ela_import
        bundle_dir = os.path.join(os.path.dirname(str(path)), "bundle")
        bundle = ela_bundle(bundle_dir)
        conn = sqlite3.connect(path)
        ela_import.import_bundle(conn, bundle, bundle_dir, static_dir=str(static_dir))
        if verify:
            conn.execute("UPDATE stimuli SET verified_by = 'test', verified_at = CURRENT_TIMESTAMP")
        conn.commit()
        conn.close()
    return str(path)


@pytest.fixture
def synth_db(tmp_path, monkeypatch):
    import db
    path = build_synthetic_db(tmp_path / "synth.db", tmp_path / "static")
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def ela_on(monkeypatch):
    import config
    monkeypatch.setattr(config, "ELA_ENABLED", True)
    monkeypatch.setattr(config, "WITHDRAWN_STIMULI", frozenset())
    return config


@pytest.fixture
def synth_client(synth_db, monkeypatch):
    import app as app_module
    import llm_client
    app_module.limiter.enabled = False
    monkeypatch.setattr(llm_client, "_budget", {"day": None, "used": 0})
    yield app_module.app.test_client()
    app_module.limiter.enabled = True
