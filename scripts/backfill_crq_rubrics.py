"""Backfill the `rubric` column for CRQ questions using official NYSED Rating
Guide PDFs (see download_rating_guides.py).

For each exam (subject/month/year):
  1. Render each Rating Guide page to an image and have the local vision
     model transcribe every numbered rubric entry on it (cached to disk per
     exam so re-runs don't redo this).
  2. For each CRQ row in that exam still missing a rubric, ask the vision
     model for the printed question number on its own cropped image, then
     look up the matching rubric text and store it.

Anything that can't be matched (rubric page missing, question number not
found, etc.) is logged to unmatched_rubrics.csv for manual follow-up.

Usage:
  python3 backfill_crq_rubrics.py --limit 5   # test on a few CRQ rows
  python3 backfill_crq_rubrics.py             # process everything pending
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import time

import fitz

from download_rating_guides import rating_guide_path
from vlm_utils import vlm_image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))
RUBRIC_CACHE_DIR = os.path.join(BASE_DIR, "rubric_cache")
UNMATCHED_PATH = os.path.join(BASE_DIR, "unmatched_rubrics.csv")
os.makedirs(RUBRIC_CACHE_DIR, exist_ok=True)

RUBRIC_PAGE_PROMPT = """This is a page from an official NY Regents exam scoring rubric (Rating Guide). \
It contains one or more numbered rubric entries, each starting with a question number in \
parentheses like (31), followed by point-value credit levels in brackets like [2], [1], [0], \
each describing what earns that many points, including exact acceptable answer forms and \
common error types.

IMPORTANT: pages often contain TWO OR MORE separate numbered questions, one after another. \
Scan the entire page from top to bottom before answering, and make sure you transcribe EVERY \
numbered question that appears, not just the first one.

Transcribe every rubric entry on this page completely and exactly, preserving all math notation, \
point values, and alternate acceptable answers/error descriptions (including any lines starting \
with "or"). Do not skip or summarize any credit level, and do not skip any question.

Output format -- for EACH question on the page, use exactly this structure:
===QUESTION <number>===
<full rubric text for that question, all credit levels>"""

QUESTION_NUMBER_PROMPT = """Look at the top-left of this exam question image. There is a printed \
question number there. Respond with ONLY that number, digits only, nothing else."""

# The model sometimes follows the "===QUESTION N===" header we ask for, and
# sometimes just preserves the source rubric's own "(N) [2] ..." notation
# instead -- inconsistent between calls even at temperature 0. Match both.
HEADER_RE = re.compile(
    r"^\s*[#=]*\s*QUESTION\s+(\d{1,2})\s*[#=]*\s*$|\((\d{1,2})\)\s*(?=\[)",
    re.IGNORECASE | re.MULTILINE,
)


def parse_rubric_page(text: str) -> dict:
    matches = list(HEADER_RE.finditer(text))
    result = {}
    for i, m in enumerate(matches):
        qnum = m.group(1) or m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            result[qnum] = body
    return result


def exam_cache_key(subject, month, year):
    return f"{subject}_{month}_{year}".replace(" ", "")


# Real rubric entries are always followed by a "[N]" credit bracket; the MCQ
# answer-key page also has "(NN)" rows but never followed by "[", so this
# distinguishes the two rather than false-triggering on the answer key.
EXPECTED_NUMBER_RE = re.compile(r"^\s*\((\d{1,2})\)\s*\n?\s*\[", re.MULTILINE)
MAX_PAGE_ATTEMPTS = 4


def extract_exam_rubrics(subject, month, year) -> dict:
    """Returns {question_number_str: rubric_text} for an exam, using a disk cache."""
    cache_path = os.path.join(RUBRIC_CACHE_DIR, exam_cache_key(subject, month, year) + ".json")
    if os.path.exists(cache_path):
        with open(cache_path) as f:
            return json.load(f)

    rg_path = rating_guide_path(subject, month, year)
    if not rg_path:
        return {}

    doc = fitz.open(rg_path)
    rubrics = {}
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        page_text = page.get_text()
        # Raw text extraction reliably finds "(NN)" markers even though the
        # math *content* inside gets garbled by font encoding -- use it both
        # as a cheap pre-filter and to verify the vision model's output below.
        expected_numbers = set(EXPECTED_NUMBER_RE.findall(page_text))
        if not expected_numbers:
            continue

        pix = page.get_pixmap(dpi=150)
        tmp_path = os.path.join(RUBRIC_CACHE_DIR, "_tmp_page.png")
        pix.save(tmp_path)

        # The local vision model is inconsistent (even at temperature 0) about
        # transcribing every question when a page has more than one -- retry
        # until it covers everything the raw text says should be there.
        parsed = {}
        for attempt in range(1, MAX_PAGE_ATTEMPTS + 1):
            try:
                result = vlm_image(RUBRIC_PAGE_PROMPT, tmp_path)
            except Exception as e:
                print(f"    [WARN] page {page_num + 1} transcription failed: {e}")
                break
            parsed = parse_rubric_page(result)
            if expected_numbers <= set(parsed.keys()):
                break
            if attempt < MAX_PAGE_ATTEMPTS:
                print(f"    [RETRY] page {page_num + 1}: expected {sorted(expected_numbers)}, "
                      f"got {sorted(parsed.keys())} (attempt {attempt}/{MAX_PAGE_ATTEMPTS})")

        missing = expected_numbers - set(parsed.keys())
        if missing and len(expected_numbers) > 1:
            # Full-page attempts exhausted and this page has multiple questions --
            # split top/bottom and retry each half with less content to track.
            print(f"    [SPLIT] page {page_num + 1}: still missing {sorted(missing)}, trying half-page crops")
            rect = page.rect
            for clip in (
                fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + rect.height * 0.6),
                fitz.Rect(rect.x0, rect.y0 + rect.height * 0.4, rect.x1, rect.y1),
            ):
                half_pix = page.get_pixmap(dpi=150, clip=clip)
                half_pix.save(tmp_path)
                try:
                    half_result = vlm_image(RUBRIC_PAGE_PROMPT, tmp_path)
                except Exception as e:
                    print(f"    [WARN] page {page_num + 1} half-crop transcription failed: {e}")
                    continue
                for qnum, body in parse_rubric_page(half_result).items():
                    if qnum in missing:
                        parsed[qnum] = body
            missing = expected_numbers - set(parsed.keys())

        if missing:
            print(f"    [WARN] page {page_num + 1}: still missing question(s) {sorted(missing)}")
        rubrics.update(parsed)

    if os.path.exists(os.path.join(RUBRIC_CACHE_DIR, "_tmp_page.png")):
        os.remove(os.path.join(RUBRIC_CACHE_DIR, "_tmp_page.png"))

    with open(cache_path, "w") as f:
        json.dump(rubrics, f)
    return rubrics


def log_unmatched(qid, subject, topic, month, year, img_rel, reason):
    write_header = not os.path.exists(UNMATCHED_PATH)
    with open(UNMATCHED_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["id", "subject", "topic", "month", "year", "image_path", "reason"])
        writer.writerow([qid, subject, topic, month, year, img_rel, reason])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", type=int, default=None)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if args.id:
        cur.execute(
            "SELECT id, subject, topic, month, year, question_image_path FROM questions WHERE id = ?",
            (args.id,),
        )
    else:
        query = (
            "SELECT id, subject, topic, month, year, question_image_path FROM questions "
            "WHERE type = 'CRQ' AND (rubric IS NULL OR TRIM(rubric) = '') "
            "ORDER BY subject, year, month"
        )
        cur.execute(query)
    rows = cur.fetchall()
    if args.limit:
        rows = rows[:args.limit]

    print(f"[INFO] {len(rows)} CRQ questions to process")

    exam_rubric_cache = {}
    for i, (qid, subject, topic, month, year, img_rel) in enumerate(rows, 1):
        exam_key = (subject, month, year)
        if exam_key not in exam_rubric_cache:
            print(f"[INFO] loading rubrics for {subject} {month} {year}...")
            exam_rubric_cache[exam_key] = extract_exam_rubrics(subject, month, year)
        rubrics = exam_rubric_cache[exam_key]

        if not rubrics:
            log_unmatched(qid, subject, topic, month, year, img_rel, "no rating guide available for this exam")
            print(f"[{i}/{len(rows)}] id={qid} SKIPPED: no rating guide for {subject} {month} {year}")
            continue

        img_path = os.path.join(IMG_ROOT, img_rel)
        if not os.path.exists(img_path):
            print(f"[WARN] id={qid}: image not found at {img_path}, skipping")
            continue

        t0 = time.time()
        try:
            qnum = vlm_image(QUESTION_NUMBER_PROMPT, img_path).strip()
            qnum = re.sub(r"\D", "", qnum)  # strip any stray non-digit characters
        except Exception as e:
            print(f"[ERROR] id={qid}: {e}")
            continue

        rubric_text = rubrics.get(qnum)
        if not rubric_text:
            log_unmatched(qid, subject, topic, month, year, img_rel, f"no rubric found for parsed question number '{qnum}'")
            print(f"[{i}/{len(rows)}] id={qid} UNMATCHED (parsed number: '{qnum}')")
            continue

        cur.execute("UPDATE questions SET rubric = ? WHERE id = ?", (rubric_text, qid))
        conn.commit()
        print(f"[{i}/{len(rows)}] id={qid} matched to question ({qnum}) in {time.time() - t0:.1f}s")

    conn.close()


if __name__ == "__main__":
    main()
