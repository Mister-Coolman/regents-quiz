import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "regentsqs.db"))


def get_conn():
    return sqlite3.connect(DB_PATH)


# The schema version this code expects (PRAGMA user_version). Migrations run
# offline with `python migrate.py`; see that file for why.
SCHEMA_VERSION = 1


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
    """, (question_id, sess_id))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_topics(subject):
    conn = get_conn()
    cur = conn.cursor()
    if subject:
        cur.execute("SELECT DISTINCT topic FROM questions WHERE subject = ?", (subject,))
    else:
        cur.execute("SELECT DISTINCT topic FROM questions")
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
      WHERE sq.session_id = ?
      ORDER BY sq.message_idx, sq.question_idx
    """, (session_id,))
    for r in cur.fetchall():
        q = dict(r)
        msg = by_id.get(q.pop("message_idx"))
        if msg is not None:
            msg["questions"].append(q)

    conn.close()
    return rows


def end_session(sess_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM session_messages WHERE session_id = ?", (sess_id,))
    cur.execute("DELETE FROM sessions         WHERE session_id = ?", (sess_id,))
    cur.execute("DELETE FROM session_questions WHERE session_id = ?", (sess_id,))
    conn.commit()
    conn.close()
