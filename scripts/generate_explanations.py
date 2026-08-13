"""Batch-generate explanations for questions missing one, using a local Ollama model.

Single model (qwen2.5vl:7b) does both steps per question, so it never has to be
swapped out of memory:
  1. transcribe the question image (text, choices, diagram description)
  2. turn that transcript + correct_answer into a step-by-step explanation

(We tried deepseek-r1:14b for step 2 for stronger reasoning, but it's a
"thinking" model that silently generates a large hidden <think> block we
then discard -- 5-8x slower for no benefit once stripped. qwen2.5vl:7b
produces an equally solid, correct explanation directly and is much faster.)

Also does double duty as a broken-crop detector: for MCQ questions, the same
transcript is checked for all 4 numbered answer choices (and that the known
correct_answer is among them). This is a deterministic text check, not a
second "does this look cut off" vision judgment call -- that was tried and
gave false positives on clean images. Anything flagged is logged to
broken_crops.csv and skipped (no explanation generated for a question whose
crop might be missing content) rather than double-transcribing every image
in a separate pass.

Usage:
  python3 generate_explanations.py --limit 3   # test on the first 3 pending rows
  python3 generate_explanations.py --id 42     # (re)process a single question
  python3 generate_explanations.py             # process everything pending
"""
import argparse
import base64
import csv
import os
import re
import sqlite3
import time
from typing import Optional

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))
BROKEN_CROPS_PATH = os.path.join(BASE_DIR, "broken_crops.csv")

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5vl:7b"

TRANSCRIBE_PROMPT = """Transcribe this Regents exam question image exactly as it appears. Include:
- The full question text
- Any answer choices (numbered 1-4), verbatim
- A plain-language description of any diagram, graph, table, or figure shown (axes, labeled points, shape, given values)
Do not answer the question. Do not add commentary. Just transcribe/describe what's on the page."""

CHOICE_MARKER_RE = re.compile(r"[\(\[]?\s*([1-4])\s*[\)\].:]")


def _post_ollama(payload: dict, timeout: int) -> dict:
    resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    if not resp.ok:
        raise RuntimeError(f"{resp.status_code} from Ollama: {resp.text[:300]}")
    return resp.json()


def transcribe_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")
    data = _post_ollama({
        "model": MODEL,
        "prompt": TRANSCRIBE_PROMPT,
        "images": [img_b64],
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192},
    }, timeout=300)
    return data["response"].strip()


def check_crop(transcript: str, qtype: str, correct_answer: str) -> Optional[str]:
    """Returns a reason string if the crop looks broken, else None. MCQ only."""
    if qtype != "MCQ":
        return None

    found_choices = {int(m.group(1)) for m in CHOICE_MARKER_RE.finditer(transcript)}
    missing = sorted(set(range(1, 5)) - found_choices)
    if missing:
        return f"missing choice marker(s) {missing} in transcript"

    try:
        if int(correct_answer) not in found_choices:
            return f"correct_answer={correct_answer} not found among transcribed choices"
    except (TypeError, ValueError):
        pass

    return None


def load_flagged_ids() -> set[int]:
    if not os.path.exists(BROKEN_CROPS_PATH):
        return set()
    with open(BROKEN_CROPS_PATH, newline="") as f:
        return {int(row["id"]) for row in csv.DictReader(f)}


def log_broken_crop(qid, subject, topic, month, year, img_rel, reason):
    write_header = not os.path.exists(BROKEN_CROPS_PATH)
    with open(BROKEN_CROPS_PATH, "a", newline="") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["id", "subject", "topic", "month", "year", "image_path", "reason"])
        writer.writerow([qid, subject, topic, month, year, img_rel, reason])


def generate_explanation(transcript: str, qtype: str, correct_answer: str) -> str:
    if qtype == "MCQ" and correct_answer and correct_answer != "N/A":
        prompt = f"""You are a patient math tutor. Below is a transcribed NY Regents exam multiple-choice question.

{transcript}

The correct answer is choice {correct_answer}.

Write a clear, step-by-step explanation of how to solve this problem and arrive at choice {correct_answer}. \
Explain the reasoning a student should use, not just the arithmetic. Keep it under 200 words. \
Do not restate these instructions or start with "the correct answer is" -- just teach it."""
    else:
        prompt = f"""You are a patient math tutor. Below is a transcribed NY Regents exam constructed-response question.

{transcript}

Solve this problem yourself and write a clear, step-by-step worked solution a student could follow, \
ending in the final answer. Keep it concise and show the key steps."""

    data = _post_ollama({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_ctx": 8192},
    }, timeout=300)
    return data["response"].strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", type=int, default=None, help="(re)process a single question id")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    select_cols = "id, subject, topic, month, year, type, correct_answer, question_image_path"

    if args.id:
        cur.execute(f"SELECT {select_cols} FROM questions WHERE id = ?", (args.id,))
        rows = cur.fetchall()
        print(f"[INFO] {len(rows)} questions to process")
    else:
        flagged_ids = load_flagged_ids()
        cur.execute(
            f"SELECT {select_cols} FROM questions "
            "WHERE explanation IS NULL OR TRIM(explanation) = '' ORDER BY id"
        )
        rows = [r for r in cur.fetchall() if r[0] not in flagged_ids]
        if args.limit:
            rows = rows[:args.limit]
        skipped_note = f" ({len(flagged_ids)} previously flagged broken crops skipped)" if flagged_ids else ""
        print(f"[INFO] {len(rows)} questions to process{skipped_note}")

    for i, (qid, subject, topic, month, year, qtype, correct_answer, img_rel) in enumerate(rows, 1):
        img_path = os.path.join(IMG_ROOT, img_rel)
        if not os.path.exists(img_path):
            print(f"[WARN] id={qid}: image not found at {img_path}, skipping")
            continue

        t0 = time.time()
        try:
            transcript = transcribe_image(img_path)

            broken_reason = check_crop(transcript, qtype, correct_answer)
            if broken_reason:
                log_broken_crop(qid, subject, topic, month, year, img_rel, broken_reason)
                print(f"[{i}/{len(rows)}] id={qid} ({qtype}) FLAGGED broken crop: {broken_reason}")
                continue

            explanation = generate_explanation(transcript, qtype, correct_answer)
        except Exception as e:
            print(f"[ERROR] id={qid}: {e}")
            continue

        cur.execute("UPDATE questions SET explanation = ? WHERE id = ?", (explanation, qid))
        conn.commit()
        dt = time.time() - t0
        print(f"[{i}/{len(rows)}] id={qid} ({qtype}) done in {dt:.1f}s")

    conn.close()


if __name__ == "__main__":
    main()
