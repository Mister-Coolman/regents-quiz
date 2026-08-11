import json
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "regentsqs.db"))


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        month TEXT NOT NULL,
        year INTEGER NOT NULL,
        type TEXT NOT NULL,
        question_image_path TEXT NOT NULL,
        correct_answer TEXT,
        explanation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id   TEXT PRIMARY KEY,
        started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS session_messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id   TEXT    NOT NULL,
        sender       TEXT    NOT NULL,
        text         TEXT    NOT NULL,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            ON DELETE CASCADE
        );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS session_questions (
        session_id    TEXT    NOT NULL,
        message_idx   INTEGER NOT NULL,
        question_idx  INTEGER NOT NULL,
        question_id   INTEGER NOT NULL,
        question_data TEXT    NOT NULL,
        PRIMARY KEY (session_id, message_idx, question_idx),
        FOREIGN KEY (session_id, message_idx)
            REFERENCES session_messages(session_id, id)
            ON DELETE CASCADE
    );
    """)
    conn.commit()
    conn.close()


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


def fetch_questions(subject, topic, qtype, limit):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
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
    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


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
            json.dumps(q, ensure_ascii=False)
        ))

    conn.commit()
    conn.close()
    return bot_msg_id


def get_history(session_id):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
      SELECT
        sm.id        AS id,
        sm.sender    AS sender,
        sm.text      AS text,
        GROUP_CONCAT(sq.question_data, '||') AS questions_concat
      FROM session_messages sm
      LEFT JOIN session_questions sq
        ON sm.session_id = sq.session_id
       AND sm.id         = sq.message_idx
      WHERE sm.session_id = ?
      GROUP BY sm.id
      ORDER BY sm.created_at
    """, (session_id,))

    rows = []
    for r in cur.fetchall():
        row = dict(r)
        qc = row.pop('questions_concat')
        row['questions'] = [json.loads(q) for q in (qc.split('||') if qc else [])]
        rows.append(row)

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
