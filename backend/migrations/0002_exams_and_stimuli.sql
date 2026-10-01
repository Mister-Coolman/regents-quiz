-- Part 1 of ELA: exams, reading passages (stimuli) and the links between
-- questions and the passages they ask about. Additive only: no math row
-- changes except gaining an exam_id, and every new questions column is
-- nullable, so the public payload and grading of all math questions stay
-- byte-identical (tests/golden_math.json checks this).

-- One row per administration of one subject, e.g. ELA June 2026.
-- code is NYSED's file code: month number then two-digit year ("626").
CREATE TABLE IF NOT EXISTS exams (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    subject   TEXT    NOT NULL,
    month     TEXT    NOT NULL,
    year      INTEGER NOT NULL,
    code      TEXT,
    framework TEXT,                 -- 'Common Core' or 'Next Generation'
    UNIQUE (subject, year, month)
);

INSERT OR IGNORE INTO exams (subject, month, year, code)
SELECT DISTINCT subject, month, year,
       CASE lower(substr(month, 1, 3))
           WHEN 'jan' THEN '1' WHEN 'jun' THEN '6' WHEN 'aug' THEN '8'
           ELSE NULL END || substr(CAST(year AS TEXT), 3, 2)
FROM questions;

ALTER TABLE questions ADD COLUMN exam_id INTEGER REFERENCES exams(id);

UPDATE questions SET exam_id = (
    SELECT e.id FROM exams e
    WHERE e.subject = questions.subject AND e.month = questions.month AND e.year = questions.year
);

-- Columns ELA needs. All nullable; math rows leave them empty.
ALTER TABLE questions ADD COLUMN part INTEGER;
ALTER TABLE questions ADD COLUMN standard TEXT;
-- Internal: the stem and choices as text, for explanations and checks.
-- Never sent to the browser (answers.PUBLIC_FIELDS).
ALTER TABLE questions ADD COLUMN question_text TEXT;
ALTER TABLE questions ADD COLUMN choices TEXT;      -- JSON array of 4 strings
-- What a screen reader announces for the question image.
ALTER TABLE questions ADD COLUMN alt_text TEXT;

-- A passage, poem or other text that a group of questions is about.
-- lines is a JSON array of {"n": printed line number or null,
-- "text": "...", "stanza_break": true|absent}, in printed order.
CREATE TABLE IF NOT EXISTS stimuli (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id       INTEGER NOT NULL REFERENCES exams(id),
    label         TEXT    NOT NULL,             -- 'A', 'B', 'C' as printed
    kind          TEXT,                         -- 'literary', 'poem', 'informational'
    title         TEXT,
    author        TEXT,
    intro         TEXT,                         -- italic lead-in, if any
    lines         TEXT    NOT NULL,             -- JSON, see above
    footnotes     TEXT,                         -- JSON array of strings
    credit        TEXT,                         -- credit line as printed
    -- 'unreviewed', 'cleared' or 'withdrawn'. Withdrawn is never served.
    rights_status TEXT    NOT NULL DEFAULT 'unreviewed',
    -- Set after a person checks the text line by line against the exam.
    -- Unverified passages are never served.
    verified_by   TEXT,
    verified_at   TIMESTAMP,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (exam_id, label)
);

CREATE TABLE IF NOT EXISTS question_stimuli (
    question_id INTEGER NOT NULL REFERENCES questions(id),
    stimulus_id INTEGER NOT NULL REFERENCES stimuli(id),
    PRIMARY KEY (question_id, stimulus_id)
);
CREATE INDEX IF NOT EXISTS ix_question_stimuli_stimulus ON question_stimuli(stimulus_id);

-- Lines a question's stem cites ("in lines 12 through 15"), parsed from the
-- stem only, never from the choices.
CREATE TABLE IF NOT EXISTS question_line_refs (
    question_id INTEGER NOT NULL REFERENCES questions(id),
    stimulus_id INTEGER NOT NULL REFERENCES stimuli(id),
    line_start  INTEGER NOT NULL,
    line_end    INTEGER NOT NULL,
    PRIMARY KEY (question_id, stimulus_id, line_start)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_questions_exam_question_no
    ON questions(exam_id, question_no)
    WHERE question_no IS NOT NULL;
