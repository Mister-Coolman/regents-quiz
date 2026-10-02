"""The ELA path, against a small synthetic bank (no real database needed)."""
import copy
import json
import os
import sqlite3

import pytest

import ela_import
from answers import HIDDEN_FIELDS, OPTIONAL_PUBLIC_FIELDS, PUBLIC_FIELDS
from conftest import MATH_ROWS, build_synthetic_db, ela_bundle
from tests import golden

SID = "ela-session-0001"
ALLOWED = set(PUBLIC_FIELDS) | set(OPTIONAL_PUBLIC_FIELDS) | {"hints"}


def ask(client, sid=SID, text="give me an ELA passage"):
    return client.post("/api/query", json={"session_id": sid, "query": text}).get_json()


def ela_ids(db_path):
    conn = sqlite3.connect(db_path)
    ids = [r[0] for r in conn.execute("SELECT id FROM questions WHERE subject = 'ELA' ORDER BY question_no")]
    conn.close()
    return ids


@pytest.fixture
def ela_parsed(parsed):
    parsed(subject="ELA", qtype="MCQ", limit=5)
    return parsed


# ---- Migration 0002 ----

def test_migration_backfills_exams_and_keeps_math_payloads(tmp_path):
    """Math fingerprints are identical before and after 0002, and every math
    row gets an exam."""
    import migrate
    path = tmp_path / "bank.db"
    conn = sqlite3.connect(path)
    with open(os.path.join(migrate.MIGRATIONS_DIR, "0001_baseline.sql")) as f:
        conn.executescript(f.read())
    conn.executemany("""INSERT INTO questions (subject, topic, month, year, type, question_image_path,
                        correct_answer, explanation, question_no) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", MATH_ROWS)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    before = golden.compute(str(path))
    migrate.migrate(str(path))
    assert golden.compute(str(path)) == before

    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM questions WHERE exam_id IS NULL").fetchone()[0] == 0
    exams = conn.execute("SELECT subject, month, year, code FROM exams ORDER BY id").fetchall()
    assert ("Algebra I", "June", 2024, "624") in exams
    assert ("Geometry", "August", 2022, "822") in exams
    assert len(exams) == 3
    conn.close()


def test_golden_ignores_ela_rows(synth_db):
    fingerprints = golden.compute(synth_db)
    assert len(fingerprints) == len(MATH_ROWS)


# ---- Import gates ----

def test_bundle_gates(tmp_path):
    bundle = ela_bundle(str(tmp_path))
    assert ela_import.check_bundle(bundle, str(tmp_path), allow_partial=True) == []
    assert ela_import.check_bundle(bundle, str(tmp_path))  # only 5 of 24 questions

    def broken(change):
        b = copy.deepcopy(bundle)
        change(b)
        return ela_import.check_bundle(b, str(tmp_path), allow_partial=True)

    assert broken(lambda b: b["stimuli"][0]["lines"][3].update(text="costs $5"))
    assert broken(lambda b: b["stimuli"][0]["lines"][3].update(text="a || b"))
    assert broken(lambda b: b["stimuli"][0]["lines"][3].update(n=40))           # not monotonic
    assert broken(lambda b: b["questions"][0].update(question_text="In lines 30 through 31, the"))
    warnings = []
    b = copy.deepcopy(bundle)
    b["questions"][0]["line_refs"] = [[1, 2]]                                       # differs from stem
    assert ela_import.check_bundle(b, str(tmp_path), allow_partial=True, warnings=warnings) == []
    assert warnings and "stem reads as" in warnings[0]
    assert broken(lambda b: b["questions"][0].update(correct_answer="5"))
    assert broken(lambda b: b["questions"][0].update(choices=["a", "b", "c"]))
    assert broken(lambda b: b["questions"][0].update(image="crops/missing.png"))


def test_reimport_keeps_ids_and_resets_changed_passages(synth_db, tmp_path):
    before_q = ela_ids(synth_db)
    conn = sqlite3.connect(synth_db)
    before_s = dict(conn.execute("SELECT label, id FROM stimuli").fetchall())
    bundle_dir = str(tmp_path / "bundle2")
    bundle = ela_bundle(bundle_dir)
    bundle["stimuli"][1]["lines"][0]["text"] = "A corrected first line"
    ela_import.import_bundle(conn, bundle, bundle_dir, static_dir=str(tmp_path / "static"))
    conn.commit()
    after_s = dict(conn.execute("SELECT label, id FROM stimuli").fetchall())
    verified = dict(conn.execute("SELECT label, verified_at IS NOT NULL FROM stimuli").fetchall())
    conn.close()
    assert ela_ids(synth_db) == before_q
    assert after_s == before_s
    assert verified == {"A": 1, "B": 0}


# ---- Serving ----

def test_ela_is_off_by_default(synth_client, ela_parsed):
    body = ask(synth_client)
    assert "questions" not in body
    assert "isn't available" in body["response"]
    assert synth_client.get("/api/features").get_json() == {"ela": False}


def test_passage_set_is_served_whole(synth_client, ela_parsed, ela_on):
    body = ask(synth_client)
    assert "pdf_url" not in body and "PDF" not in body["response"]
    assert len(body["stimuli"]) == 1
    stim = body["stimuli"][0]
    qs = body["questions"]
    assert all(q["stimulus_ids"] == [stim["id"]] for q in qs)
    assert len(qs) == (3 if stim["label"] == "A" else 2)
    assert [q["question_no"] for q in qs] == sorted(q["question_no"] for q in qs)
    for q in qs:
        assert set(q) <= ALLOWED
        assert not set(q) & set(HIDDEN_FIELDS)
        assert q["alt_text"].startswith(f"Question {q['question_no']}.")
    assert stim["lines"][0]["n"] == 1 and stim["credit"]
    assert synth_client.get("/api/features").get_json() == {"ela": True}


def test_line_refs_and_credit_escaping(synth_client, ela_parsed, ela_on):
    seen = {}
    for _ in range(2):
        body = ask(synth_client)
        seen[body["stimuli"][0]["label"]] = body
    assert set(seen) == {"A", "B"}, "the unseen set should come second"
    refs = {q["question_no"]: q["line_refs"] for q in seen["A"]["questions"]}
    assert [(r["start"], r["end"]) for r in refs[1]] == [(3, 5)]
    assert [(r["start"], r["end"]) for r in refs[3]] == [(12, 12)]
    assert refs[2] == []
    # The poem's credit has markup in it; it travels as data, never in the reply HTML.
    assert "<i>" not in seen["B"]["response"]
    assert seen["B"]["stimuli"][0]["credit"].endswith("<i>Journal</i>")


def test_short_limit_still_gets_a_whole_set(synth_client, parsed, ela_on):
    parsed(subject="ELA", qtype="MCQ", limit=1)
    body = ask(synth_client)
    assert len(body["stimuli"]) == 1 and len(body["questions"]) in (2, 3)
    parsed(subject="ELA", qtype="MCQ", limit=20)
    body = ask(synth_client, sid="ela-session-0002")
    assert len(body["stimuli"]) == 2 and len(body["questions"]) == 5


def test_check_and_history(synth_client, ela_parsed, ela_on, synth_db):
    body = ask(synth_client)
    q = body["questions"][0]
    conn = sqlite3.connect(synth_db)
    key = conn.execute("SELECT correct_answer FROM questions WHERE id = ?", (q["id"],)).fetchone()[0]
    conn.close()
    out = synth_client.post("/api/check", json={"session_id": SID, "question_id": q["id"], "answer": key}).get_json()
    assert out["correct"] is True and out["correct_answer"] == key

    rows = synth_client.get(f"/api/history/{SID}").get_json()
    bot = [r for r in rows if r["questions"]][0]
    assert [x["id"] for x in bot["questions"]] == [x["id"] for x in body["questions"]]
    assert [s["id"] for s in bot["stimuli"]] == [s["id"] for s in body["stimuli"]]


def test_download_refuses_ela(synth_client, synth_db):
    assert synth_client.get(f"/api/download?ids={ela_ids(synth_db)[0]}").status_code == 400


def test_math_requests_never_pick_ela(synth_client, parsed, ela_on):
    parsed(subject="", qtype="MCQ", limit=20)
    body = ask(synth_client, text="20 multiple choice questions")
    assert body["questions"] and all(q["subject"] != "ELA" for q in body["questions"])
    parsed(intent="count_questions", subject="", qtype="MCQ", limit=0)
    assert "<b>3</b>" in ask(synth_client, text="how many mcqs")["response"]


@pytest.mark.parametrize("how", ["secret", "database"])
def test_withdrawn_passage_disappears_everywhere(synth_client, ela_parsed, ela_on, synth_db, monkeypatch, how):
    parsed_body = ask(synth_client)
    stim_id = parsed_body["stimuli"][0]["id"]
    qid = parsed_body["questions"][0]["id"]

    if how == "secret":
        monkeypatch.setattr(ela_on, "WITHDRAWN_STIMULI", frozenset({stim_id}))
    else:
        conn = sqlite3.connect(synth_db)
        conn.execute("UPDATE stimuli SET rights_status = 'withdrawn' WHERE id = ?", (stim_id,))
        conn.commit()
        conn.close()

    check = synth_client.post("/api/check", json={"session_id": SID, "question_id": qid, "answer": "1"})
    assert check.status_code == 404
    rows = synth_client.get(f"/api/history/{SID}").get_json()
    assert all(not r["questions"] and not r.get("stimuli") for r in rows)
    for _ in range(3):
        body = ask(synth_client, sid="ela-session-0003")
        assert all(s["id"] != stim_id for s in body["stimuli"])


def test_unverified_passages_are_not_served(tmp_path, monkeypatch, parsed, ela_on):
    import app as app_module
    import db
    path = build_synthetic_db(tmp_path / "unverified.db", tmp_path / "static", verify=False)
    monkeypatch.setattr(db, "DB_PATH", path)
    app_module.limiter.enabled = False
    try:
        parsed(subject="ELA", qtype="MCQ", limit=5)
        body = ask(app_module.app.test_client())
    finally:
        app_module.limiter.enabled = True
    assert "questions" not in body and "No English Language Arts passages" in body["response"]


def test_turning_ela_off_hides_served_sets(synth_client, ela_parsed, ela_on, monkeypatch):
    qid = ask(synth_client)["questions"][0]["id"]
    monkeypatch.setattr(ela_on, "ELA_ENABLED", False)
    assert synth_client.post("/api/check", json={"session_id": SID, "question_id": qid, "answer": "1"}).status_code == 404
    rows = synth_client.get(f"/api/history/{SID}").get_json()
    assert all(not r["questions"] for r in rows)


def test_ela_topics_and_essays(synth_client, parsed, ela_on):
    parsed(intent="list_topics", subject="ELA", qtype="", limit=0)
    body = ask(synth_client, text="what ELA practice do you have")
    assert "whole passage sets" in body["response"] and "<b>2</b>" in body["response"]
    parsed(subject="ELA", qtype="Essay", limit=1)
    body = ask(synth_client, text="an ELA essay")
    assert "questions" not in body and "multiple" in body["response"]


def test_copy_rules(synth_client, parsed, ela_on):
    """Sentence case, no exclamation marks, no em dashes, no 'coming soon'."""
    import app as app_module
    with app_module.app.app_context():
        texts = [app_module.ELA_UNAVAILABLE, app_module.help_response().get_json()["response"]]
    parsed(intent="list_topics", subject="ELA", qtype="", limit=0)
    texts.append(ask(synth_client)["response"])
    for t in texts:
        assert "!" not in t and "—" not in t and "coming soon" not in t.lower()


def test_stimuli_json_shape(synth_db):
    conn = sqlite3.connect(synth_db)
    lines = json.loads(conn.execute("SELECT lines FROM stimuli WHERE label = 'B'").fetchone()[0])
    conn.close()
    assert lines[4] == {"n": 5, "text": "Line 5 of the poem", "stanza_break": True}
    assert "stanza_break" not in lines[0]


def test_extractor_bundle_is_translated(tmp_path):
    """ela_extract.py's own bundle shape imports after from_extractor."""
    ours = ela_bundle(str(tmp_path))
    raw = {
        "exam": {"subject": "ELA", "month": "Jun", "year": 2026, "code": "626", "source": "x.pdf"},
        "stimuli": [{
            "label": s["label"], "kind": s["kind"], "title": s["title"], "title_notes": [],
            "lines": [{"n": l["n"], "text": l["text"], "indent": False, "gap_before": bool(l.get("stanza_break")),
                       "italic": [], "notes": [], "page": 1, "y": 0.0} for l in s["lines"]],
            "line_count": len(s["lines"]), "printed_numbers": [5, 10],
            "attribution": [{"text": s["credit"], "italic": []}],
            "footnotes": [{"n": 1, "term": "word", "gloss": "meaning"}],
            "pages": [1],
        } for s in ours["stimuli"]],
        "questions": [{
            "no": q["question_no"], "passage": q["stimulus"], "stem": q["question_text"],
            "choices": q["choices"], "key": q["correct_answer"], "standard_raw": "RL.1", "standard": "RL.1",
            # Unmerged, as a stem parser may give them: "lines 1 and 2" -> 1-1, 2-2.
            "line_refs": [{"start": n, "end": n, "source": f"line {n}"}
                          for a, b in ela_import.parse_line_refs(q["question_text"]) for n in range(a, b + 1)],
            "crop": q["image"], "crop_px": [10, 10], "crop_rect": {"page": 1, "rect": [0, 0, 1, 1]},
        } for q in ours["questions"]],
        "figures": [{"page": 6, "bbox": [0, 0, 1, 1], "passage": "C"}],
        "gates": {"errors": [], "warnings": []},
    }
    bundle = ela_import.from_extractor(raw)
    assert bundle["exam"]["month"] == "June"
    assert bundle["stimuli"][0]["footnotes"] == ["1 word: meaning"]
    assert bundle["stimuli"][1]["lines"][4].get("stanza_break") is True
    warnings = []
    assert ela_import.check_bundle(bundle, str(tmp_path), allow_partial=True, warnings=warnings) == []
    assert warnings == []
    assert bundle["questions"][0]["line_refs"] == [[3, 3], [4, 4], [5, 5]]
    assert ela_import.from_extractor(ours) is ours


def test_footnote_markers_reach_the_reader_without_unverifying(synth_client, ela_parsed, ela_on, synth_db, tmp_path):
    bundle_dir = str(tmp_path / "marks")
    bundle = ela_bundle(bundle_dir)
    a = bundle["stimuli"][0]
    a["intro"] = "In this excerpt, a story begins."
    a["intro_notes"] = [{"n": 1, "at": 15}]
    a["title_notes"] = [{"n": 2, "at": 9}]
    a["lines"][2]["notes"] = [{"n": 3, "at": 4}]
    conn = sqlite3.connect(synth_db)
    summary = ela_import.import_bundle(conn, bundle, bundle_dir, static_dir=str(tmp_path / "static"))
    conn.commit()
    conn.close()
    assert summary.get("stimuli_changed", 0) == 1      # the intro is new text: A needs a fresh check
    conn = sqlite3.connect(synth_db)
    conn.execute("UPDATE stimuli SET verified_by = 'test', verified_at = CURRENT_TIMESTAMP")
    conn.commit()
    a["lines"][2]["notes"] = [{"n": 3, "at": 6}]       # a marker moves; the text doesn't
    summary = ela_import.import_bundle(conn, bundle, bundle_dir, static_dir=str(tmp_path / "static"))
    conn.commit()
    assert summary.get("stimuli_marks_updated") == 1 and not summary.get("stimuli_changed")
    assert conn.execute("SELECT COUNT(*) FROM stimuli WHERE verified_at IS NULL").fetchone()[0] == 0
    conn.close()

    for _ in range(2):
        body = ask(synth_client)
        stim = body["stimuli"][0]
        if stim["label"] == "A":
            break
    assert stim["intro_notes"] == [{"n": 1, "at": 15}] and stim["title_notes"] == [{"n": 2, "at": 9}]
    assert stim["lines"][2]["notes"] == [{"n": 3, "at": 6}]


def test_unnumbered_subheading_passes_the_gates(tmp_path):
    bundle = ela_bundle(str(tmp_path))
    lines = bundle["stimuli"][0]["lines"]
    lines.insert(6, {"n": None, "text": "A Subheading", "heading": True})
    assert ela_import.check_bundle(bundle, str(tmp_path), allow_partial=True) == []
    assert ela_import._line(lines[6]) == {"n": None, "text": "A Subheading", "heading": True}
