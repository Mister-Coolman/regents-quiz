-- The schema as of the question_no backfill. Every statement is a no-op on
-- the existing database; it records the starting point so later migrations
-- have a version to build on.

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    rubric TEXT,
    question_no INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_subject TEXT,
    last_topic   TEXT,
    last_type    TEXT,
    last_limit   INTEGER
);

CREATE TABLE IF NOT EXISTS session_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    sender       TEXT    NOT NULL,
    text         TEXT    NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        ON DELETE CASCADE
);

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

-- One number per question on each exam; NULL is allowed (and repeatable)
-- for rows whose number couldn't be read.
CREATE UNIQUE INDEX IF NOT EXISTS ux_questions_exam_no
    ON questions(subject, year, month, question_no)
    WHERE question_no IS NOT NULL;
