"""Read-only checks on the question bank before it ships in an image.

Exits non-zero if anything that would break the live app is wrong. Warnings
(things worth knowing that don't block a release) are printed but don't fail.

  python scripts/check_data.py            # check backend/regentsqs.db
  python scripts/check_data.py --ship     # also require empty session tables
"""
import argparse
import os
import sqlite3
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
sys.path.insert(0, BACKEND)

import db  # noqa: E402
from topics import SUBJECT_TOPICS  # noqa: E402

STATIC = os.path.join(BACKEND, "static")
MCQ_MAX_NO = 24          # every math Regents: Part I is questions 1-24
EXPLANATION_HEADINGS = ("What's being asked", "Approach", "Work", "Answer")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=db.DB_PATH)
    parser.add_argument("--ship", action="store_true", help="also require empty session tables")
    args = parser.parse_args()

    errors, warnings = [], []
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        errors.append("PRAGMA integrity_check failed")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != db.SCHEMA_VERSION:
        errors.append(f"schema version {version}, code expects {db.SCHEMA_VERSION} (run backend/migrate.py)")

    rows = [dict(r) for r in conn.execute("SELECT * FROM questions")]
    if not rows:
        errors.append("questions table is empty")

    for q in rows:
        tag = f"id {q['id']} ({q['subject']} {q['month']} {q['year']})"
        path = os.path.join(STATIC, q["question_image_path"] or "")
        if not q["question_image_path"] or not os.path.isfile(path):
            errors.append(f"{tag}: image missing: {q['question_image_path']}")
        if q["subject"] in SUBJECT_TOPICS and q["topic"] not in SUBJECT_TOPICS[q["subject"]]:
            errors.append(f"{tag}: topic '{q['topic']}' is not in topics.SUBJECT_TOPICS")
        key = str(q["correct_answer"] or "").strip()
        if q["type"] == "MCQ" and key not in ("1", "2", "3", "4"):
            errors.append(f"{tag}: MCQ key '{key}' is not 1-4")
        if q["type"] != "MCQ" and key != "N/A":
            errors.append(f"{tag}: {q['type']} key '{key}' should be N/A")
        n = q.get("question_no")
        if n is None:
            warnings.append(f"{tag}: no question_no")
        elif (q["type"] == "MCQ") != (1 <= n <= MCQ_MAX_NO):
            errors.append(f"{tag}: question_no {n} doesn't fit a {q['type']}")
        expl = q["explanation"] or ""
        if not expl:
            warnings.append(f"{tag}: no explanation")
        elif not all(f"**{h}**" in expl for h in EXPLANATION_HEADINGS):
            warnings.append(f"{tag}: explanation is missing a section, so hints are partial")

    used = {q["question_image_path"] for q in rows}
    on_disk = set()
    for folder, _, files in os.walk(os.path.join(STATIC, "images")):
        for f in files:
            if f.endswith(".png"):
                on_disk.add(os.path.relpath(os.path.join(folder, f), STATIC))
    orphans = on_disk - used
    if orphans:
        warnings.append(f"{len(orphans)} images in static/ belong to no question (shipped for nothing)")

    sessions = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("sessions", "session_messages", "session_questions")}
    if args.ship and any(sessions.values()):
        errors.append(f"session tables aren't empty {sessions}: local chats would ship in the image")
    conn.close()

    per_subject = Counter(q["subject"] for q in rows)
    print(f"[check] {len(rows)} questions: " + ", ".join(f"{s} {c}" for s, c in sorted(per_subject.items())))
    shown = Counter()
    for w in warnings:
        kind = w.split(": ", 1)[-1]
        shown[kind] += 1
        if shown[kind] <= 3:
            print(f"[warn] {w}")
    hidden = sum(c - 3 for c in shown.values() if c > 3)
    if hidden:
        print(f"[warn] ... and {hidden} more warnings of the same kinds")
    for e in errors[:50]:
        print(f"[error] {e}")
    if errors:
        print(f"[check] FAILED with {len(errors)} errors")
        sys.exit(1)
    print("[check] ok")


if __name__ == "__main__":
    main()
