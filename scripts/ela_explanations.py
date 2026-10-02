"""Write explanations for ELA Part 1 questions, adapted from
fireworks_explanations.py.

The model gets text, not an image: the passage with its printed line numbers,
the stem, the four choices and the key. Every explanation keeps the same four
headings as math (What's being asked / Approach / Work / Answer) so the quiz
can cut hints from it.

An explanation is stored only if it passes every validator:
  - the four headings, in order, with no self-correction
  - its Answer names the keyed choice, and no other
  - no '$' (the quiz renders explanations as Markdown with math)
  - at most 200 words, and at most 15 words quoted from the passage
  - every line it cites ("line 12", "lines 3-5") exists in the passage
A question that still fails after retries ships without an explanation.

Theme and "best supports" questions are flagged in the review report: a
person reads every one of those before release.

  python scripts/ela_explanations.py --exam 626 --dry-run   # report only
  python scripts/ela_explanations.py --apply                # save what that report showed
  python scripts/ela_explanations.py --exam 626             # generate and save in one go
  python scripts/ela_explanations.py --id 1812 --regenerate
"""
import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from ela_import import parse_line_refs  # noqa: E402
from fireworks_explanations import (  # noqa: E402
    API_KEY, FIREWORKS_MODEL, FIREWORKS_URL, HEADERS, REQUIRED_HEADERS, SELF_CORRECTION_RE, contradicts_key,
)

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
MAX_WORDS = 200
MAX_QUOTED_WORDS = 15
MAX_ATTEMPTS = 3
# Questions a person must check by hand even when every validator passes.
HAND_CHECK_RE = re.compile(r"\b(theme|central idea|best supports?|best supported|evidence)\b", re.IGNORECASE)

PROMPT = """You are writing a short explanation for a student practicing the New York State \
Regents exam in English Language Arts. Below is a passage with its printed line numbers, then \
one multiple-choice question about it. The correct answer is choice {key}.

Explain how a careful reader arrives at choice {key}. Teach the reading move (what to reread, \
what to notice, how the choice follows), not just the answer.

Format your entire response with EXACTLY these four headers, in this order, starting \
immediately with the first one:

**What's being asked**
One sentence restating what the question wants, in plain words.

**Approach**
One or two sentences naming the reading skill and where in the passage to look, by line number.

**Work**
Numbered steps. Point to specific lines by number ("In lines 12-15, ..."). Quote at most a few \
words at a time and no more than {max_quote} words in total; paraphrase the rest. When you \
mention another choice, say briefly why it doesn't fit.

**Answer**
One sentence that names choice {key} and why it is correct.

Rules: no LaTeX. Write any amount of money with a backslash before the dollar sign, like \\$5. Cite only line numbers that appear in the passage. Plain, \
calm language; no exclamation marks. Keep the whole response under {max_words} words.

PASSAGE {label}{title}
{passage}

QUESTION {no}
{stem}
(1) {c1}
(2) {c2}
(3) {c3}
(4) {c4}
"""

QUOTE_RE = re.compile(r"[\"“]([^\"”]+)[\"”]")
CITED_RE = re.compile(r"\blines?\s+\d+(?:\s*(?:-|–|through|to|and|,)\s*\d+)*", re.IGNORECASE)


def passage_text(lines):
    out = []
    for line in lines:
        if line.get("stanza_break"):
            out.append("")
        n = line.get("n")
        out.append(f"{n:>3}  {line['text']}" if n is not None else f"     {line['text']}")
    return "\n".join(out)


def problems(content, key, line_numbers):
    """Why this explanation can't ship; empty if it can."""
    found = []
    positions = [content.find(h) for h in REQUIRED_HEADERS]
    if not content.strip().startswith(REQUIRED_HEADERS[0]) or -1 in positions or positions != sorted(positions):
        found.append("headings missing or out of order")
    if SELF_CORRECTION_RE.search(content):
        found.append("self-correction")
    answer = content.split("**Answer**")[-1] if "**Answer**" in content else ""
    named = {int(n) for n in re.findall(r"(?:choice|option)\s*\(?([1-4])\)?", answer, re.IGNORECASE)}
    # contradicts_key strips "choice N ... is correct" as a dismissal, so also
    # require the Answer to name the key and no other choice.
    if contradicts_key(content, "MCQ", key) or named != {int(key)}:
        found.append("Answer doesn't name the keyed choice alone")
    if re.search(r"(?<!\\)\$", content):
        found.append("contains an unescaped '$' (prices must be written \\$5)")
    words = len(re.findall(r"\b\w+\b", content))
    if words > MAX_WORDS:
        found.append(f"{words} words (max {MAX_WORDS})")
    quoted = sum(len(q.split()) for q in QUOTE_RE.findall(content))
    if quoted > MAX_QUOTED_WORDS:
        found.append(f"{quoted} quoted words (max {MAX_QUOTED_WORDS})")
    for match in CITED_RE.finditer(content):
        for start, end in parse_line_refs(match.group(0)):
            missing = [n for n in range(start, end + 1) if n not in line_numbers]
            if missing:
                found.append(f"cites line(s) {missing} not in the passage")
    return found


def call(prompt, usage):
    resp = requests.post(FIREWORKS_URL, headers=HEADERS, timeout=90, json={
        "model": FIREWORKS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 700,
        "reasoning_effort": "none",
    })
    resp.raise_for_status()
    data = resp.json()
    for k in ("prompt_tokens", "completion_tokens"):
        usage[k] += (data.get("usage") or {}).get(k, 0)
    return data["choices"][0]["message"]["content"].strip()


def explain(row, stimulus, usage):
    """(content or '', problems of the last attempt)."""
    lines = json.loads(stimulus["lines"])
    numbers = {line["n"] for line in lines if line.get("n") is not None}
    choices = json.loads(row["choices"])
    prompt = PROMPT.format(
        key=row["correct_answer"], max_quote=MAX_QUOTED_WORDS, max_words=MAX_WORDS - 20,
        label=stimulus["label"], title=f": {stimulus['title']}" if stimulus["title"] else "",
        passage=passage_text(lines), no=row["question_no"], stem=row["question_text"],
        c1=choices[0], c2=choices[1], c3=choices[2], c4=choices[3],
    )
    last = []
    for _ in range(MAX_ATTEMPTS):
        content = call(prompt, usage)
        last = problems(content, row["correct_answer"], numbers)
        if not last:
            return content, []
    return "", last


def select(conn, args):
    where, params = ["q.subject = 'ELA'"], []
    if args.id:
        where.append("q.id = ?")
        params.append(args.id)
    if args.exam:
        where.append("e.code = ?")
        params.append(args.exam)
    if not args.regenerate:
        where.append("(q.explanation IS NULL OR TRIM(q.explanation) = '')")
    return conn.execute(f"""
      SELECT q.*, s.id AS stimulus_id FROM questions q
      JOIN exams e ON e.id = q.exam_id
      JOIN question_stimuli qs ON qs.question_id = q.id
      JOIN stimuli s ON s.id = qs.stimulus_id
      WHERE {' AND '.join(where)}
      ORDER BY e.year, e.month, q.question_no
    """, params).fetchall()


def write_report(path, results):
    parts = ["<!doctype html><meta charset='utf-8'><title>ELA explanation review</title>",
             "<style>body{font:16px/1.5 -apple-system,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem}"
             ".q{border:1px solid #ccc;border-radius:10px;padding:1rem;margin:1rem 0}"
             ".flag{color:#b00;font-weight:600}.hand{color:#a60;font-weight:600}"
             "pre{white-space:pre-wrap;background:#f5f5f7;padding:.75rem;border-radius:8px}</style>",
             f"<h1>ELA explanation review</h1><p>{sum(1 for r in results if r['content'])} of "
             f"{len(results)} passed every validator. Check every item marked for a hand check.</p>"]
    for r in results:
        notes = ""
        if r["problems"]:
            notes += f"<p class='flag'>Not stored: {html.escape('; '.join(r['problems']))}</p>"
        if r["hand_check"]:
            notes += "<p class='hand'>Hand check: theme or best-supports question</p>"
        parts.append(f"<div class='q'><b>id {r['id']}, question {r['no']}</b> (key {r['key']})"
                     f"<p>{html.escape(r['stem'])}</p>{notes}<pre>{html.escape(r['content'])}</pre></div>")
    with open(path, "w") as f:
        f.write("\n".join(parts))


def apply_saved(db_path, results_path):
    """Store the passing explanations from the last run, re-checked against
    the database as it is now."""
    with open(results_path) as f:
        results = json.load(f)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    saved = skipped = 0
    for r in results:
        if not r["content"]:
            continue
        row = conn.execute("""SELECT q.correct_answer, s.lines FROM questions q
                              JOIN question_stimuli qs ON qs.question_id = q.id
                              JOIN stimuli s ON s.id = qs.stimulus_id WHERE q.id = ?""", (r["id"],)).fetchone()
        numbers = {line["n"] for line in json.loads(row["lines"]) if line.get("n") is not None} if row else set()
        why = ["question not found"] if not row else problems(r["content"], row["correct_answer"], numbers)
        if why:
            print(f"[apply] id {r['id']} q{r['no']}: not saved, {'; '.join(why)}")
            skipped += 1
            continue
        conn.execute("UPDATE questions SET explanation = ? WHERE id = ?", (r["content"], r["id"]))
        saved += 1
    conn.commit()
    conn.close()
    print(f"[apply] saved {saved} explanations from {results_path}" + (f", skipped {skipped}" if skipped else ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--exam", help="NYSED exam code, e.g. 626")
    parser.add_argument("--id", type=int)
    parser.add_argument("--regenerate", action="store_true", help="also redo questions that have one")
    parser.add_argument("--dry-run", action="store_true", help="write the report, not the database")
    parser.add_argument("--report", default=os.path.join(BASE_DIR, "ela_explanations_review.html"))
    parser.add_argument("--apply", action="store_true",
                        help="save the explanations from the last run's report, without calling the model")
    args = parser.parse_args()
    # Every run saves its results beside the report, so what was reviewed is
    # exactly what --apply stores (a new call would write different text).
    results_path = os.path.splitext(args.report)[0] + ".json"
    if args.apply:
        apply_saved(args.db, results_path)
        return
    if not API_KEY:
        sys.exit("FIREWORKS_API_KEY is not set (backend/.env)")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = select(conn, args)
    usage = {"prompt_tokens": 0, "completion_tokens": 0}
    results, t0 = [], time.time()
    for i, row in enumerate(rows, 1):
        stimulus = conn.execute("SELECT * FROM stimuli WHERE id = ?", (row["stimulus_id"],)).fetchone()
        content, why = explain(row, stimulus, usage)
        results.append({"id": row["id"], "no": row["question_no"], "key": row["correct_answer"],
                        "stem": row["question_text"], "content": content, "problems": why,
                        "hand_check": bool(HAND_CHECK_RE.search(row["question_text"] or ""))})
        print(f"[{i}/{len(rows)}] id {row['id']} q{row['question_no']}: {'ok' if content else 'FAILED ' + '; '.join(why)}")
        if content and not args.dry_run:
            conn.execute("UPDATE questions SET explanation = ? WHERE id = ?", (content, row["id"]))
            conn.commit()
    conn.close()
    write_report(args.report, results)
    with open(results_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"[done] {sum(1 for r in results if r['content'])}/{len(results)} passed in {time.time() - t0:.0f}s; "
          f"tokens in {usage['prompt_tokens']} out {usage['completion_tokens']}; report {args.report}")


if __name__ == "__main__":
    main()
