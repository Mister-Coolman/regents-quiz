"""Load one ELA exam's extracted bundle into the question bank.

Reads scripts/ela_out/<code>/bundle.json (written by ela_extract.py), re-runs
the hard gates, copies the question crops into backend/static/images/ela/<code>/
and upserts the exam, its passages (stimuli), its questions and the links
between them. Run it on a migrated database (backend/migrate.py).

Re-running is safe. Rows are matched on (exam, passage label) and (exam,
question number), so ids survive a re-import: WITHDRAWN_STIMULI, download
links and saved progress all refer to ids. A passage whose text changes
loses its verification and must be checked again (scripts/ela_stimuli.py).

Nothing here is served until a person verifies each passage and ELA_ENABLED
is on.

  python scripts/ela_import.py 626 [--dry-run] [--allow-partial]

bundle.json, as this script expects it:

  {
    "exam": {"subject": "ELA", "month": "June", "year": 2026, "code": "626",
             "framework": "Next Generation"},
    "stimuli": [
      {"label": "A", "kind": "literary" | "poem" | "informational",
       "title": "...", "author": "...", "intro": "..." | null,
       "lines": [{"n": 1, "text": "...", "stanza_break": true,
                  "notes": [{"n": 1, "at": 14}]}, ...],
       "title_notes": [...], "intro_notes": [...]   (footnote markers, optional)
       "footnotes": ["..."], "credit": "..."}
    ],
    "questions": [
      {"question_no": 1, "part": 1, "stimulus": "A", "image": "crops/q01.png",
       "question_text": "...", "choices": ["...", "...", "...", "..."],
       "correct_answer": "2", "standard": "RL.1",
       "line_refs": [[12, 15]], "alt_text": "..." (optional)}
    ]
  }

"stanza_break": true marks a blank line before that line; "indent": true an
indented printed line. Bundles written by ela_extract.py are translated into
this shape first (from_extractor).
"heading": true marks an unnumbered subheading (set in bold).
"n" is the printed line number for every line of a numbered passage (null
for unnumbered lines such as a title inside the text). "line_refs" is
optional: when present it is used as given (a difference from what
parse_line_refs reads in the stem is printed as a warning), and when absent
it is filled from the stem.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
OUT_DIR = os.path.join(ROOT, "scripts", "ela_out")
STATIC = os.path.join(BACKEND, "static")
DB_PATH = os.path.join(BACKEND, "regentsqs.db")

ELA_SUBJECT = "ELA"
PART1_QUESTIONS = 24
KINDS = {"literary": "Literary text", "poem": "Poetry", "informational": "Informational text"}
MONTH_NO = {"January": 1, "June": 6, "August": 8}
MONTHS = tuple(MONTH_NO)

# "line 7", "lines 12 through 15", "lines 3-5 and 9", "lines 1–4, 8, and 10–12"
_RANGE = r"\d+(?:\s*(?:through|to|-|–|—)\s*\d+)?"
LINE_REF_RE = re.compile(rf"\blines?\s+({_RANGE}(?:\s*(?:,\s*and|,|and)\s*{_RANGE})*)", re.IGNORECASE)


def merge_ranges(refs):
    """Join ranges that touch: "lines 7 and 8" is one passage of two lines,
    not two citations."""
    out = []
    for start, end in refs:
        if out and out[-1][1] + 1 == start:
            out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def parse_line_refs(stem):
    """[(start, end)] cited in a question stem, in order. Only ever call this
    on the stem: choices quote the passage and their numbers aren't refs."""
    refs = []
    for m in LINE_REF_RE.finditer(stem or ""):
        for part in re.split(r"\s*(?:,\s*and|,|and)\s*", m.group(1)):
            nums = [int(n) for n in re.findall(r"\d+", part)]
            if nums:
                refs.append((nums[0], nums[-1]))
    return merge_ranges(refs)


def _kind(raw):
    k = (raw or "").strip().lower()
    for prefix, kind in (("lit", "literary"), ("fic", "literary"), ("poe", "poem"), ("inf", "informational")):
        if k.startswith(prefix):
            return kind
    return k


def from_extractor(raw):
    """Translate ela_extract.py's bundle into the shape documented above.

    ela_extract.py writes questions as {no, passage, stem, key, crop,
    line_refs: [{start, end, source}]}, lines with gap_before and indent,
    credit lines as `attribution` and footnotes as {n, term, gloss}.
    Bundles already in the documented shape pass through unchanged."""
    questions = raw.get("questions") or []
    if not questions or "no" not in questions[0]:
        return raw
    exam = dict(raw["exam"])
    exam.pop("source", None)
    month = str(exam.get("month") or "")
    exam["month"] = next((m for m in MONTHS if m[:3].lower() == month[:3].lower()), month)
    if str(exam.get("subject") or "").lower() in ("ela", "english", "english language arts"):
        exam["subject"] = ELA_SUBJECT
    stimuli = []
    for s in raw["stimuli"]:
        lines = []
        for line in s["lines"]:
            out = {"n": line.get("n"), "text": line["text"]}
            if line.get("gap_before"):
                out["stanza_break"] = True
            if line.get("indent"):
                out["indent"] = True
            if line.get("heading"):
                out["heading"] = True
            if line.get("notes"):
                out["notes"] = [{"n": n["n"], "at": n["at"]} for n in line["notes"]]
            lines.append(out)
        stimuli.append({
            "label": s["label"],
            "kind": _kind(s.get("kind")),
            "title": s.get("title"),
            "author": s.get("author"),
            "intro": s.get("intro"),
            "title_notes": s.get("title_notes") or [],
            "intro_notes": s.get("intro_notes") or [],
            "lines": lines,
            "footnotes": [f"{f.get('n', '')} {f.get('term', '')}: {f.get('gloss', '')}".strip()
                          for f in s.get("footnotes") or []],
            "credit": "\n".join(a["text"] for a in s.get("attribution") or [] if a.get("text")) or None,
        })
    return {
        "exam": exam,
        "stimuli": stimuli,
        "questions": [{
            "question_no": q["no"],
            "part": q.get("part", 1),
            "stimulus": q["passage"],
            "image": q["crop"],
            "question_text": q["stem"],
            "choices": q["choices"],
            "correct_answer": str(q["key"]),
            "standard": q.get("standard"),
            # `source` is the matched stem text ("lines 11 and 12"); the
            # extractor reads refs from the stem only, so all of them count.
            "line_refs": [[r["start"], r["end"]] for r in q.get("line_refs") or []],
        } for q in questions],
        # Kept for the report only: figures are never imported (they may be
        # third-party images, and no question so far refers to one).
        "figures": raw.get("figures") or [],
    }


def _texts(bundle):
    for s in bundle["stimuli"]:
        for key in ("title", "author", "intro", "credit"):
            if s.get(key):
                yield f"passage {s['label']} {key}", s[key]
        for line in s["lines"]:
            yield f"passage {s['label']} line {line.get('n')}", line["text"]
        for i, f in enumerate(s.get("footnotes") or []):
            yield f"passage {s['label']} footnote {i + 1}", f
    for q in bundle["questions"]:
        yield f"question {q['question_no']}", q.get("question_text") or ""
        for c in q.get("choices") or []:
            yield f"question {q['question_no']} choice", c
        if q.get("alt_text"):
            yield f"question {q['question_no']} alt text", q["alt_text"]


def check_bundle(bundle, bundle_dir, allow_partial=False, warnings=None):
    """The hard gates. Returns a list of errors; empty means importable.
    Things worth a look that don't block go into `warnings` if given."""
    errors = []
    warnings = [] if warnings is None else warnings
    exam = bundle.get("exam") or {}
    if exam.get("subject") != ELA_SUBJECT:
        errors.append(f"exam subject must be {ELA_SUBJECT}")
    if exam.get("month") not in MONTHS:
        errors.append(f"exam month must be one of {MONTHS}, got {exam.get('month')!r}")
    if not isinstance(exam.get("year"), int):
        errors.append("exam year must be an integer")

    stimuli = {s.get("label"): s for s in bundle.get("stimuli") or []}
    if len(stimuli) != len(bundle.get("stimuli") or []):
        errors.append("passage labels must be unique")
    numbered = {}
    for label, s in stimuli.items():
        if s.get("kind") not in KINDS:
            errors.append(f"passage {label}: kind must be one of {sorted(KINDS)}")
        if not s.get("lines"):
            errors.append(f"passage {label}: no lines")
            continue
        ns = [line.get("n") for line in s["lines"] if line.get("n") is not None]
        if ns != sorted(set(ns)) or (ns and ns != list(range(ns[0], ns[0] + len(ns)))):
            errors.append(f"passage {label}: line numbers aren't 1, 2, 3... in order")
        numbered[label] = set(ns)

    questions = bundle.get("questions") or []
    nos = [q.get("question_no") for q in questions]
    if not all(isinstance(n, int) for n in nos):
        return errors + ["some questions have no integer question_no: is this bundle in the documented "
                         "shape, or ela_extract.py's (see from_extractor)?"]
    if not allow_partial and sorted(nos) != list(range(1, PART1_QUESTIONS + 1)):
        errors.append(f"expected questions 1-{PART1_QUESTIONS}, got {sorted(n for n in nos if n)}")
    if len(set(nos)) != len(nos):
        errors.append("question numbers must be unique")

    for q in questions:
        tag = f"question {q.get('question_no')}"
        label = q.get("stimulus")
        if label not in stimuli:
            errors.append(f"{tag}: passage {label!r} not in bundle")
        if str(q.get("correct_answer")) not in ("1", "2", "3", "4"):
            errors.append(f"{tag}: key {q.get('correct_answer')!r} is not 1-4")
        choices = q.get("choices")
        if not (isinstance(choices, list) and len(choices) == 4 and all(isinstance(c, str) and c.strip() for c in choices)):
            errors.append(f"{tag}: needs 4 non-empty choices")
        if not (q.get("question_text") or "").strip():
            errors.append(f"{tag}: no stem text")
        image = os.path.join(bundle_dir, q.get("image") or "")
        if not q.get("image") or not os.path.isfile(image):
            errors.append(f"{tag}: crop missing: {q.get('image')}")
        parsed = parse_line_refs(q.get("question_text"))
        given = merge_ranges([tuple(r) for r in q["line_refs"]]) if q.get("line_refs") is not None else parsed
        if given != parsed:
            # The extractor's refs win: it also resolves "the second stanza"
            # and similar, which this simple parser doesn't. Worth a look,
            # since a missed ref means lines that won't be highlighted.
            warnings.append(f"{tag}: line_refs {given}, but the stem reads as {parsed}: "
                            f"\"{(q.get('question_text') or '')[:90]}\"")
        for start, end in given:
            if start > end:
                errors.append(f"{tag}: line range {start}-{end} runs backwards")
            missing = [n for n in range(start, end + 1) if n not in numbered.get(label, set())]
            if missing:
                errors.append(f"{tag}: cites line(s) {missing} that passage {label} doesn't have")

    for where, text in _texts(bundle):
        # Passages and stems render as plain text, so a price's '$' is fine.
        if "||" in text:
            errors.append(f"{where}: contains '||'")
    return errors


def _line(line):
    out = {"n": line.get("n"), "text": line["text"]}
    if line.get("stanza_break"):
        out["stanza_break"] = True
    if line.get("indent"):
        out["indent"] = True
    if line.get("heading"):
        out["heading"] = True
    if line.get("notes"):
        out["notes"] = line["notes"]
    return out


def _stimulus_fields(s):
    return {
        "kind": s["kind"],
        "title": s.get("title"),
        "author": s.get("author"),
        "intro": s.get("intro"),
        "lines": json.dumps([_line(line) for line in s["lines"]], ensure_ascii=False),
        "footnotes": json.dumps(s.get("footnotes") or [], ensure_ascii=False),
        "credit": s.get("credit"),
        "marks": json.dumps({"title": s.get("title_notes") or [], "intro": s.get("intro_notes") or []}),
    }


def _text_only(fields):
    """The fields a person verified, without footnote marker positions: adding
    or moving a marker doesn't undo a line-by-line check of the text."""
    lines = [{k: v for k, v in line.items() if k != "notes"} for line in json.loads(fields["lines"])]
    return {**{k: v for k, v in fields.items() if k not in ("lines", "marks")}, "lines": lines}


def import_bundle(conn, bundle, bundle_dir, static_dir=STATIC):
    """Upsert one exam. Returns a summary dict. The caller commits."""
    exam = bundle["exam"]
    code = exam.get("code") or f"{MONTH_NO[exam['month']]}{exam['year'] % 100:02d}"
    cur = conn.cursor()
    cur.execute("""INSERT INTO exams (subject, month, year, code, framework) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(subject, year, month) DO UPDATE SET code = excluded.code,
                       framework = COALESCE(excluded.framework, exams.framework)""",
                (ELA_SUBJECT, exam["month"], exam["year"], code, exam.get("framework")))
    exam_id = cur.execute("SELECT id FROM exams WHERE subject = ? AND month = ? AND year = ?",
                          (ELA_SUBJECT, exam["month"], exam["year"])).fetchone()[0]

    summary = {"exam_id": exam_id, "stimuli_new": 0, "stimuli_changed": 0, "questions_new": 0, "questions_updated": 0}
    stim_ids = {}
    for s in bundle["stimuli"]:
        fields = _stimulus_fields(s)
        row = cur.execute(f"SELECT id, {', '.join(fields)} FROM stimuli WHERE exam_id = ? AND label = ?",
                          (exam_id, s["label"])).fetchone()
        if row is None:
            cur.execute(f"INSERT INTO stimuli (exam_id, label, {', '.join(fields)}) VALUES (?, ?, {', '.join('?' * len(fields))})",
                        (exam_id, s["label"], *fields.values()))
            stim_ids[s["label"]] = cur.lastrowid
            summary["stimuli_new"] += 1
        else:
            stim_ids[s["label"]] = row[0]
            stored = dict(zip(fields, row[1:]))
            stored["marks"] = stored["marks"] or json.dumps({"title": [], "intro": []})
            if stored != fields:
                text_changed = _text_only(stored) != _text_only(fields)
                # Only a change to the text a person checked undoes the check.
                reset = ", verified_by = NULL, verified_at = NULL" if text_changed else ""
                cur.execute(f"UPDATE stimuli SET {', '.join(f'{k} = ?' for k in fields)}{reset} WHERE id = ?",
                            (*fields.values(), row[0]))
                summary["stimuli_changed" if text_changed else "stimuli_marks_updated"] = \
                    summary.get("stimuli_changed" if text_changed else "stimuli_marks_updated", 0) + 1

    rel_dir = os.path.join("images", "ela", code)
    os.makedirs(os.path.join(static_dir, rel_dir), exist_ok=True)
    for q in bundle["questions"]:
        no = q["question_no"]
        rel = os.path.join(rel_dir, f"q{no:02d}{os.path.splitext(q['image'])[1] or '.png'}")
        shutil.copy2(os.path.join(bundle_dir, q["image"]), os.path.join(static_dir, rel))
        label = q["stimulus"]
        kind = next(s["kind"] for s in bundle["stimuli"] if s["label"] == label)
        values = {
            "subject": ELA_SUBJECT, "topic": KINDS[kind], "month": exam["month"], "year": exam["year"],
            "type": "MCQ", "question_image_path": rel, "correct_answer": str(q["correct_answer"]),
            "question_no": no, "exam_id": exam_id, "part": q.get("part", 1), "standard": q.get("standard"),
            "question_text": q["question_text"], "choices": json.dumps(q["choices"], ensure_ascii=False),
            "alt_text": q.get("alt_text") or default_alt_text(q),
        }
        row = cur.execute("SELECT id FROM questions WHERE exam_id = ? AND question_no = ?", (exam_id, no)).fetchone()
        if row is None:
            cur.execute(f"INSERT INTO questions ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                        tuple(values.values()))
            qid = cur.lastrowid
            summary["questions_new"] += 1
        else:
            qid = row[0]
            cur.execute(f"UPDATE questions SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                        (*values.values(), qid))
            summary["questions_updated"] += 1
        cur.execute("DELETE FROM question_stimuli WHERE question_id = ?", (qid,))
        cur.execute("DELETE FROM question_line_refs WHERE question_id = ?", (qid,))
        cur.execute("INSERT INTO question_stimuli (question_id, stimulus_id) VALUES (?, ?)", (qid, stim_ids[label]))
        refs = merge_ranges([tuple(r) for r in q["line_refs"]]) if q.get("line_refs") is not None \
            else parse_line_refs(q["question_text"])
        for start, end in refs:
            cur.execute("""INSERT OR IGNORE INTO question_line_refs (question_id, stimulus_id, line_start, line_end)
                           VALUES (?, ?, ?, ?)""", (qid, stim_ids[label], start, end))
    return summary


def default_alt_text(q):
    """What a screen reader reads for the crop: the stem, then the choices,
    exactly as printed."""
    choices = " ".join(f"({i}) {c}" for i, c in enumerate(q["choices"], start=1))
    return f"Question {q['question_no']}. {q['question_text']} {choices}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("code", help="NYSED exam code, e.g. 626 for June 2026")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="run the gates, change nothing")
    parser.add_argument("--allow-partial", action="store_true", help="accept fewer than 24 questions")
    args = parser.parse_args()

    bundle_dir = os.path.join(OUT_DIR, args.code)
    with open(os.path.join(bundle_dir, "bundle.json")) as f:
        raw = json.load(f)
    for w in (raw.get("gates") or {}).get("warnings") or []:
        print(f"[extract warning] {w}")
    bundle = from_extractor(raw)
    for fig in bundle.get("figures") or []:
        # ela_extract.py counts pages from 0; people count from 1.
        page = fig.get("page")
        print(f"[import] not imported: figure in passage {fig.get('passage')} on page "
              f"{page + 1 if isinstance(page, int) else page}")
    warnings = []
    errors = check_bundle(bundle, bundle_dir, args.allow_partial, warnings)
    for w in warnings:
        print(f"[check] {w}")
    for e in errors:
        print(f"[gate] {e}")
    if errors:
        sys.exit(f"[import] {len(errors)} gate failures; nothing imported")
    print(f"[import] gates pass: {len(bundle['stimuli'])} passages, {len(bundle['questions'])} questions")
    if args.dry_run:
        return

    conn = sqlite3.connect(args.db)
    sys.path.insert(0, BACKEND)
    import db  # noqa: E402
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < db.SCHEMA_VERSION:
        sys.exit(f"[import] database is at schema {version}; run backend/migrate.py first")
    try:
        summary = import_bundle(conn, bundle, bundle_dir)
        conn.commit()
    finally:
        conn.close()
    print(f"[import] {summary}")
    print("[import] passages stay hidden until verified: python scripts/ela_stimuli.py verify "
          f"{args.code} --by <your name>")


if __name__ == "__main__":
    main()
