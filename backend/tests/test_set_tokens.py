"""Signed set tokens: a reopened chat can check what it was served, and
nothing else."""
import sqlite3

import set_tokens
from tests.test_ela import ask


def test_round_trip_and_tampering():
    token = set_tokens.sign([5, 3, 9])
    assert set_tokens.verify(token) == {3, 5, 9}
    payload, sig = token.split(".")
    forged = set_tokens._b64(b"[3,5,9,1,2]")
    assert set_tokens.verify(f"{forged}.{sig}") == set()
    assert set_tokens.verify(f"{payload}.{sig[:-1]}x") == set()
    for junk in (None, "", "abc", "a.b.c", 12, "x" * 2000):
        assert set_tokens.verify(junk) == set()


def check(client, sid, qid, token=None):
    body = {"session_id": sid, "question_id": qid, "answer": "1"}
    if token:
        body["set_token"] = token
    return client.post("/api/check", json=body)


def test_reopened_chat_checks_with_its_token(synth_client, parsed):
    parsed(subject="Algebra I", qtype="MCQ", limit=2)
    body = ask(synth_client, sid="first-session-01", text="2 algebra mcqs")
    qid, token = body["questions"][0]["id"], body["set_token"]
    # A new session (as after a deploy wiped the old one) is refused without
    # the token and allowed with it.
    assert check(synth_client, "after-deploy-01", qid).status_code == 404
    assert check(synth_client, "after-deploy-01", qid, token).status_code == 200


def test_token_doesnt_open_other_questions(synth_client, parsed, synth_db):
    parsed(subject="Algebra I", qtype="MCQ", limit=1)
    body = ask(synth_client, sid="first-session-02", text="1 algebra mcq")
    served = body["questions"][0]["id"]
    conn = sqlite3.connect(synth_db)
    other = conn.execute("SELECT id FROM questions WHERE subject = 'Geometry'").fetchone()[0]
    conn.close()
    assert other != served
    assert check(synth_client, "after-deploy-02", other, body["set_token"]).status_code == 404


def test_token_respects_withdrawal(synth_client, parsed, ela_on, synth_db, monkeypatch):
    parsed(subject="ELA", qtype="MCQ", limit=5)
    body = ask(synth_client, sid="first-session-03")
    qid, stim = body["questions"][0]["id"], body["stimuli"][0]["id"]
    assert check(synth_client, "after-deploy-03", qid, body["set_token"]).status_code == 200
    monkeypatch.setattr(ela_on, "WITHDRAWN_STIMULI", frozenset({stim}))
    assert check(synth_client, "after-deploy-03", qid, body["set_token"]).status_code == 404


def test_history_rows_carry_tokens(synth_client, parsed):
    parsed(subject="Algebra I", qtype="MCQ", limit=2)
    ask(synth_client, sid="first-session-04", text="2 algebra mcqs")
    rows = synth_client.get("/api/history/first-session-04").get_json()
    bot = [r for r in rows if r["questions"]][0]
    assert set_tokens.verify(bot["set_token"]) == {q["id"] for q in bot["questions"]}
