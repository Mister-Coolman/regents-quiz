import sqlite3

import pytest

from answers import HIDDEN_FIELDS, PUBLIC_FIELDS, public_question
from conftest import needs_db

SID = "test-session-0001"
ALLOWED = set(PUBLIC_FIELDS) | {"hints"}


def query(client, sid=SID, text="give me 3 algebra 1 mcqs"):
    return client.post("/api/query", json={"session_id": sid, "query": text})


def test_public_question_is_an_allowlist():
    row = {
        "id": 1, "subject": "ELA", "topic": "t", "month": "June", "year": 2026, "type": "MCQ",
        "question_image_path": "x.png", "question_no": 3,
        "correct_answer": "2", "explanation": "**Answer** 2", "rubric": "r",
        "question_text": "the stem", "choices": "[...]", "standard": "RL.1", "created_at": "now",
    }
    out = public_question(row)
    assert set(out) <= ALLOWED
    assert not set(out) & set(HIDDEN_FIELDS)
    assert "question_text" not in out and "choices" not in out


@needs_db
def test_query_sends_only_public_fields(client, parsed):
    body = query(client).get_json()
    assert len(body["questions"]) == 3
    for q in body["questions"]:
        assert set(q) <= ALLOWED
        assert q["question_no"] is not None


@needs_db
def test_history_is_ordered_and_public(client, parsed):
    first = [q["id"] for q in query(client).get_json()["questions"]]
    parsed(subject="Geometry", qtype="CRQ", limit=2)
    second = [q["id"] for q in query(client, text="2 geometry crqs").get_json()["questions"]]

    rows = client.get(f"/api/history/{SID}").get_json()
    assert [r["sender"] for r in rows] == ["student", "bot", "student", "bot"]
    served = [[q["id"] for q in r["questions"]] for r in rows if r["questions"]]
    assert served == [first, second]
    for r in rows:
        for q in r["questions"]:
            assert set(q) <= ALLOWED


@needs_db
def test_snapshots_store_only_the_id(client, parsed, db_copy):
    query(client)
    conn = sqlite3.connect(db_copy)
    data = [r[0] for r in conn.execute("SELECT question_data FROM session_questions")]
    conn.close()
    assert data and all(d.startswith('{"id":') and "correct_answer" not in d for d in data)


@needs_db
def test_check_grades_served_questions_only(client, parsed, db_copy):
    q = query(client).get_json()["questions"][0]
    conn = sqlite3.connect(db_copy)
    key = conn.execute("SELECT correct_answer FROM questions WHERE id = ?", (q["id"],)).fetchone()[0]
    conn.close()
    wrong = next(a for a in "1234" if a != key)

    ok = client.post("/api/check", json={"session_id": SID, "question_id": q["id"], "answer": key}).get_json()
    assert ok["correct"] is True and ok["correct_answer"] == key
    bad = client.post("/api/check", json={"session_id": SID, "question_id": q["id"], "answer": wrong}).get_json()
    assert bad["correct"] is False

    stranger = client.post("/api/check", json={"session_id": "another-session", "question_id": q["id"], "answer": key})
    assert stranger.status_code == 404


@needs_db
def test_constructed_response_is_ungraded(client, parsed):
    parsed(subject="Geometry", qtype="CRQ", limit=1)
    q = query(client, text="1 geometry crq").get_json()["questions"][0]
    out = client.post("/api/check", json={"session_id": SID, "question_id": q["id"], "answer": "42"}).get_json()
    assert out["correct"] is None and out["correct_answer"] is None


@needs_db
def test_download_rules(client, db_copy):
    conn = sqlite3.connect(db_copy)
    ids = [r[0] for r in conn.execute("SELECT id FROM questions LIMIT 3")]
    conn.execute("""INSERT INTO questions (subject, topic, month, year, type, question_image_path, correct_answer)
                    VALUES ('ELA', 'Vocabulary', 'June', 2026, 'MCQ', '', '2')""")
    ela_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()

    ok = client.get("/api/download?ids=" + ",".join(map(str, ids)))
    assert ok.status_code == 200 and ok.mimetype == "application/pdf"
    assert client.get(f"/api/download?ids={ids[0]},{ela_id}").status_code == 400
    assert client.get("/api/download?ids=" + ",".join(["1"] * 51)).status_code == 400


@needs_db
def test_oversized_body_is_refused(client):
    resp = client.post("/api/query", data="x" * (100 * 1024), content_type="application/json")
    assert resp.status_code == 413


@needs_db
def test_daily_llm_cap(client, parsed, monkeypatch):
    import llm_client
    monkeypatch.setattr(llm_client, "LLM_DAILY_CAP", 1)
    assert "questions" in query(client).get_json()
    second = query(client).get_json()
    assert second["response"].startswith("Practice sets are paused for today")
    assert "questions" not in second


@needs_db
def test_api_is_not_indexed(client):
    assert client.get("/healthz").headers["X-Robots-Tag"] == "noindex, nofollow"


@needs_db
def test_readyz(client):
    body = client.get("/readyz").get_json()
    assert body["ok"] and body["images"] and sum(body["questions"].values()) > 0
