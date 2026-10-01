import json
import os
import sqlite3

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "regentsqs.db"))


def get_conn():
    return sqlite3.connect(DB_PATH)


# The schema version this code expects (PRAGMA user_version). Migrations run
# offline with `python migrate.py`; see that file for why.
SCHEMA_VERSION = 2


class SchemaTooOld(RuntimeError):
    pass


def init_db():
    """Refuse to start on a database older than the code. Under gunicorn
    --preload the app then never boots, the Fly health check fails, and the
    previous release keeps serving."""
    conn = get_conn()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    if version < SCHEMA_VERSION:
        raise SchemaTooOld(
            f"{DB_PATH} is at schema version {version}, this code needs {SCHEMA_VERSION}. "
            f"Run `python migrate.py` before deploying."
        )


def touch_session(sess_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sessions(session_id, last_active)
        VALUES (?, CURRENT_TIMESTAMP)
    ON CONFLICT(session_id) DO
        UPDATE SET last_active = CURRENT_TIMESTAMP
    """, (sess_id,))
    conn.commit()
    conn.close()


def get_last_query(sess_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT last_subject, last_topic, last_type, last_limit FROM sessions WHERE session_id = ?",
        (sess_id,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    subject, topic, qtype, limit = row
    if not any([subject, topic, qtype, limit]):
        return None
    return {"subject": subject or "", "topic": topic or "", "type": qtype or "", "limit": limit or 0}


def set_last_query(sess_id, subject, topic, qtype, limit):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE sessions SET last_subject = ?, last_topic = ?, last_type = ?, last_limit = ? WHERE session_id = ?",
        (subject or None, topic or None, qtype or None, limit or None, sess_id),
    )
    conn.commit()
    conn.close()


# Subjects served as single questions with a PDF. ELA is served only as whole
# passage sets (fetch_ela_sets), so a request that names no subject must never
# pick ELA rows one by one.
MATH_SUBJECTS = ("Algebra I", "Geometry", "Algebra II")
ELA_SUBJECT = "ELA"
_MATH_IN = "subject IN (" + ",".join("'%s'" % s for s in MATH_SUBJECTS) + ")"


def _servable_stimulus(alias="s"):
    """SQL condition: this passage may be shown. Verified by a person, not
    withdrawn in the database, not withdrawn by the WITHDRAWN_STIMULI secret.
    The ids are integers parsed in config, so inlining them is safe."""
    cond = f"({alias}.verified_at IS NOT NULL AND {alias}.rights_status != 'withdrawn'"
    if config.WITHDRAWN_STIMULI:
        ids = ",".join(str(int(i)) for i in sorted(config.WITHDRAWN_STIMULI))
        cond += f" AND {alias}.id NOT IN ({ids})"
    return cond + ")"


def _servable_question(alias="q"):
    """SQL condition: this question may be served, graded or shown in history.
    Math always; ELA only while ELA is enabled and only when it belongs to at
    least one passage and every passage it belongs to is servable."""
    if not config.ELA_ENABLED:
        return f"({alias}.subject != '{ELA_SUBJECT}')"
    return f"""({alias}.subject != '{ELA_SUBJECT}' OR (
        EXISTS (SELECT 1 FROM question_stimuli qs0 WHERE qs0.question_id = {alias}.id)
        AND NOT EXISTS (
            SELECT 1 FROM question_stimuli qs1 JOIN stimuli s1 ON s1.id = qs1.stimulus_id
            WHERE qs1.question_id = {alias}.id AND NOT {_servable_stimulus("s1")})))"""


def fetch_questions(subject, topic, qtype, limit, sess_id=None):
    """Randomly select questions, preferring ones not already served in this
    session. Falls back to repeats (still randomized, but ordered last) once
    the unseen pool for the given filters is exhausted."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    seen_ids = []
    if sess_id:
        cur.execute("SELECT DISTINCT question_id FROM session_questions WHERE session_id = ?", (sess_id,))
        seen_ids = [row[0] for row in cur.fetchall()]

    query = "SELECT * FROM questions WHERE 1=1"
    params = []
    if subject:
        query += " AND subject = ?"
        params.append(subject)
    else:
        query += " AND " + _MATH_IN
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if qtype:
        query += " AND type = ?"
        params.append(qtype)

    if seen_ids:
        placeholders = ",".join("?" * len(seen_ids))
        query += f" ORDER BY (id IN ({placeholders})), RANDOM() LIMIT ?"
        params.extend(seen_ids)
    else:
        query += " ORDER BY RANDOM() LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def fetch_questions_by_ids(ids):
    """Look up specific questions, preserving the order of `ids`. Used to
    rebuild a PDF on demand from the ids carried in its download link."""
    if not ids:
        return []
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    placeholders = ",".join("?" * len(ids))
    cur.execute(f"SELECT * FROM questions WHERE id IN ({placeholders})", ids)
    by_id = {row["id"]: dict(row) for row in cur.fetchall()}
    conn.close()
    return [by_id[i] for i in ids if i in by_id]


def fetch_served_question(sess_id, question_id):
    """The full question row, but only if it was served to this session --
    answers are released for questions a student was actually given."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
      SELECT q.* FROM questions q
      WHERE q.id = ?
        AND EXISTS (SELECT 1 FROM session_questions sq
                    WHERE sq.session_id = ? AND sq.question_id = q.id)
        AND """ + _servable_question("q"), (question_id, sess_id))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_topics(subject):
    conn = get_conn()
    cur = conn.cursor()
    if subject:
        cur.execute("SELECT DISTINCT topic FROM questions WHERE subject = ?", (subject,))
    else:
        cur.execute("SELECT DISTINCT topic FROM questions WHERE " + _MATH_IN)
    topics = [row[0] for row in cur.fetchall() if row[0]]
    conn.close()
    return topics


def count_questions(subject, topic, qtype):
    conn = get_conn()
    cur = conn.cursor()
    query = "SELECT COUNT(*) FROM questions WHERE 1=1"
    params = []
    if subject:
        query += " AND subject = ?"; params.append(subject)
    else:
        query += " AND " + _MATH_IN
    if topic:
        query += " AND topic = ?"; params.append(topic)
    if qtype:
        query += " AND type = ?"; params.append(qtype)
    cur.execute(query, params)
    (count,) = cur.fetchone()
    conn.close()
    return count


def save_exchange(sess_id, user_query, bot_resp, questions):
    """Persist the student query, bot reply, and any attached questions in one transaction."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
      INSERT INTO session_messages(session_id, sender, text)
      VALUES (?, 'student', ?)
    """, (sess_id, user_query))

    cur.execute("""
      INSERT INTO session_messages(session_id, sender, text)
      VALUES (?, 'bot', ?)
    """, (sess_id, bot_resp))
    bot_msg_id = cur.lastrowid

    for i, q in enumerate(questions):
        cur.execute("""
        INSERT INTO session_questions
            (session_id, message_idx, question_idx, question_id, question_data)
        VALUES (?, ?, ?, ?, ?)
        """, (
            sess_id,
            bot_msg_id,
            i,
            q["id"],
            # Only the id: the row (with its answer) stays in `questions`, and
            # history rebuilds from there. Copying the full row duplicated
            # every answer into the session tables.
            json.dumps({"id": q["id"]})
        ))

    conn.commit()
    conn.close()
    return bot_msg_id


def get_history(session_id):
    """Messages in order, each with the questions it served, in the order they
    were served. Questions are read from `questions` by id, so a row removed
    from the bank simply drops out of old history."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
      SELECT id, sender, text FROM session_messages
      WHERE session_id = ?
      ORDER BY created_at, id
    """, (session_id,))
    rows = [dict(r, questions=[]) for r in cur.fetchall()]
    by_id = {r["id"]: r for r in rows}

    cur.execute("""
      SELECT sq.message_idx, q.*
      FROM session_questions sq
      JOIN questions q ON q.id = sq.question_id
      WHERE sq.session_id = ? AND """ + _servable_question("q") + """
      ORDER BY sq.message_idx, sq.question_idx
    """, (session_id,))
    for r in cur.fetchall():
        q = dict(r)
        msg = by_id.get(q.pop("message_idx"))
        if msg is not None:
            msg["questions"].append(q)

    # Passages go back only for sets this session was served, and only while
    # they are still servable (a withdrawn one drops out of old chats too).
    if config.ELA_ENABLED:
        for msg in rows:
            ela = [q for q in msg["questions"] if q["subject"] == ELA_SUBJECT]
            if ela:
                _attach_ela_links(cur, ela)
                ids = []
                for q in ela:
                    ids.extend(i for i in q["stimulus_ids"] if i not in ids)
                msg["stimuli"] = _fetch_stimuli(cur, ids)

    conn.close()
    return rows


# ---- ELA passage sets ----

def _attach_ela_links(cur, questions):
    """Add stimulus_ids and line_refs to ELA question dicts, in place."""
    if not questions:
        return
    by_id = {q["id"]: q for q in questions}
    for q in questions:
        q["stimulus_ids"], q["line_refs"] = [], []
    ph = ",".join("?" * len(by_id))
    cur.execute(f"""SELECT question_id, stimulus_id FROM question_stimuli
                    WHERE question_id IN ({ph}) ORDER BY stimulus_id""", list(by_id))
    for qid, sid in cur.fetchall():
        by_id[qid]["stimulus_ids"].append(sid)
    cur.execute(f"""SELECT question_id, stimulus_id, line_start, line_end FROM question_line_refs
                    WHERE question_id IN ({ph}) ORDER BY line_start""", list(by_id))
    for qid, sid, start, end in cur.fetchall():
        by_id[qid]["line_refs"].append({"stimulus_id": sid, "start": start, "end": end})


def _fetch_stimuli(cur, ids):
    """Servable passages by id, in the order given, ready to send."""
    if not ids:
        return []
    ph = ",".join("?" * len(ids))
    cur.execute(f"""
      SELECT s.id, s.label, s.kind, s.title, s.author, s.intro, s.lines, s.footnotes, s.credit,
             e.month, e.year
      FROM stimuli s JOIN exams e ON e.id = s.exam_id
      WHERE s.id IN ({ph}) AND {_servable_stimulus("s")}
    """, list(ids))
    found = {}
    for r in cur.fetchall():
        sid, label, kind, title, author, intro, lines, footnotes, credit, month, year = r
        found[sid] = {
            "id": sid, "label": label, "kind": kind, "title": title, "author": author,
            "intro": intro, "lines": json.loads(lines), "footnotes": json.loads(footnotes or "[]"),
            "credit": credit, "month": month, "year": year,
        }
    return [found[i] for i in ids if i in found]


def fetch_ela_sets(max_sets, max_questions, sess_id=None):
    """Whole passage sets: a passage and every question about it.

    Sets this session hasn't seen come first, then repeats, each group in
    random order. Up to `max_sets` sets are added while the question total
    stays within `max_questions`, but at least one set is always returned:
    a set is never cut in half to fit.

    Returns (stimuli, questions); questions are grouped by passage and in
    printed order within it."""
    if not config.ELA_ENABLED:
        return [], []
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"""
      SELECT s.id AS stimulus_id,
             COUNT(*) AS n,
             MAX(EXISTS (SELECT 1 FROM session_questions sq
                         WHERE sq.session_id = ? AND sq.question_id = q.id)) AS seen
      FROM stimuli s
      JOIN question_stimuli qs ON qs.stimulus_id = s.id
      JOIN questions q ON q.id = qs.question_id
      WHERE q.subject = ? AND {_servable_stimulus("s")} AND {_servable_question("q")}
      GROUP BY s.id
      ORDER BY seen, RANDOM()
    """, (sess_id or "", ELA_SUBJECT))
    picked, total = [], 0
    for r in cur.fetchall():
        if picked and total + r["n"] > max_questions:
            continue
        picked.append(r["stimulus_id"])
        total += r["n"]
        if len(picked) >= max_sets:
            break
    if not picked:
        conn.close()
        return [], []

    questions, seen_q = [], set()
    for sid in picked:
        cur.execute(f"""
          SELECT q.* FROM questions q JOIN question_stimuli qs ON qs.question_id = q.id
          WHERE qs.stimulus_id = ? AND q.subject = ? AND {_servable_question("q")}
          ORDER BY q.question_no, q.id
        """, (sid, ELA_SUBJECT))
        for row in cur.fetchall():
            if row["id"] not in seen_q:
                seen_q.add(row["id"])
                questions.append(dict(row))
    _attach_ela_links(cur, questions)
    stimuli = _fetch_stimuli(cur, picked)
    conn.close()
    return stimuli, questions


def count_ela():
    """(servable passage sets, questions in them)."""
    if not config.ELA_ENABLED:
        return 0, 0
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"""
      SELECT COUNT(DISTINCT s.id), COUNT(DISTINCT q.id)
      FROM stimuli s
      JOIN question_stimuli qs ON qs.stimulus_id = s.id
      JOIN questions q ON q.id = qs.question_id
      WHERE q.subject = ? AND {_servable_stimulus("s")} AND {_servable_question("q")}
    """, (ELA_SUBJECT,))
    sets, questions = cur.fetchone()
    conn.close()
    return sets, questions


def end_session(sess_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM session_messages WHERE session_id = ?", (sess_id,))
    cur.execute("DELETE FROM sessions         WHERE session_id = ?", (sess_id,))
    cur.execute("DELETE FROM session_questions WHERE session_id = ?", (sess_id,))
    conn.commit()
    conn.close()
