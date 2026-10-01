"""Read each question's original exam number off its crop image with a vision
model on Fireworks, as an independent check for the question-number backfill.

Model: fireworks_explanations.py uses qwen3p7-plus, but that model now returns
404 "not deployed" on chat completions. The default here is deepseek-v4p1-flash,
the multimodal model backend/llm_client.py now uses; --model overrides it.

Every crop in backend/static/ is a 300-DPI cut of one question from the exam,
and should begin with the question's number in bold at the top-left
("21 When babysitting, ..."). Only that corner is sent, not the whole image:

  read1  the top-left 500x220 px of the crop, as-is.
  read2  a differently-cropped second look: the first line of ink found by
         scanning for dark pixels (so a crop with extra whitespace on top still
         works), trimmed to its left 320 px and upscaled 2x.

read2 is only made when read1 is null, outside 1-40, or inconsistent with the
DB question type (MCQ are numbered 1-24, CRQ 25+), plus a fixed random 5%
sample of all rows to measure self-consistency.

A wrong number is worse than a missing one, so question_no is filled only when:
  - read1 is an integer 1-40 and consistent with the row's type, and
  - read2, if made, agrees exactly.
Everything else is left blank with a note. Numbers repeated within one exam
are flagged in the note too, but never "fixed".

This script never writes to the database. API responses are cached in
question_numbers_vlm_cache.json, so reruns are free and resumable.

Usage:
  python -u read_question_numbers_vlm.py --limit 20   # test on the first 20 rows
  python -u read_question_numbers_vlm.py              # everything
  --workers N   parallel requests (default 8)
  --model NAME  Fireworks model id (default deepseek-v4p1-flash)
"""
import argparse
import base64
import csv
import io
import json
import os
import random
import re
import sqlite3
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests
from dotenv import load_dotenv
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", "backend", ".env"))

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))
OUT_PATH = os.path.join(BASE_DIR, "question_numbers_vlm.csv")
CACHE_PATH = os.path.join(BASE_DIR, "question_numbers_vlm_cache.json")

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = "accounts/fireworks/models/deepseek-v4p1-flash"
API_KEY = os.getenv("FIREWORKS_API_KEY")

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

PROMPT = """This image is the top-left corner of a cropped math exam question. \
Exam questions begin with the question number printed in bold at the very start \
of the first line, immediately followed by the question text (for example \
"21 When babysitting, ...").

What is the bold question number at the start of the first line? Reply with \
strict JSON only, no other text: {"number": 21}
If no bold question number is visible at the start of the first line (the crop \
begins mid-question, with a diagram, with answer choices like "(1)", or the \
number is cut off), reply {"number": null}. Do not guess."""

SAMPLE_RATE = 0.05
SAMPLE_SEED = 1234
MAX_ATTEMPTS = 4

cache_lock = threading.Lock()


def to_b64(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def crop_read1(img):
    """Plain top-left corner."""
    return img.crop((0, 0, min(500, img.width), min(220, img.height)))


def crop_read2(img):
    """First line of ink, left part only, upscaled 2x."""
    gray = np.asarray(img.convert("L"))
    rows = np.where((gray < 128).sum(axis=1) > 2)[0]
    top = max(int(rows[0]) - 20, 0) if len(rows) else 0
    box = (0, top, min(320, img.width), min(top + 110, img.height))
    region = img.crop(box)
    return region.resize((region.width * 2, region.height * 2), Image.LANCZOS)


def ask(img, model):
    """Returns the raw model reply for one image."""
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{to_b64(img)}"}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 20,
        "reasoning_effort": "none",
    }
    for attempt in range(MAX_ATTEMPTS):
        try:
            resp = requests.post(FIREWORKS_URL, headers=HEADERS, json=payload, timeout=60)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (requests.RequestException, KeyError, ValueError) as e:
            if attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(2 ** attempt + random.random())


def parse(reply):
    """Returns an int 1-40, or None. Anything else (prose, out of range) -> None,
    plus a short reason string."""
    m = re.search(r"\{.*?\}", reply or "", re.S)
    if not m:
        return None, "unparseable"
    try:
        n = json.loads(m.group(0)).get("number")
    except (ValueError, AttributeError):
        return None, "unparseable"
    if n is None:
        return None, "null"
    if isinstance(n, str) and n.strip().isdigit():
        n = int(n.strip())
    if not isinstance(n, int) or isinstance(n, bool):
        return None, "non-integer"
    if not 1 <= n <= 40:
        return None, f"out of range ({n})"
    return n, ""


def type_ok(n, qtype):
    return (n <= 24) if qtype == "MCQ" else (n >= 25)


def cached_read(cache, key, img_fn, model):
    key = f"{model.rsplit('/', 1)[-1]}:{key}"
    with cache_lock:
        if key in cache:
            return cache[key]
    reply = ask(img_fn(), model)
    with cache_lock:
        cache[key] = reply
    return reply


def process(row, cache, sampled, model):
    qid, subject, month, year, qtype, path = row
    img = Image.open(os.path.join(IMG_ROOT, path)).convert("RGB")

    raw1 = cached_read(cache, f"{qid}:r1", lambda: crop_read1(img), model)
    n1, why1 = parse(raw1)

    need2 = n1 is None or not type_ok(n1, qtype) or qid in sampled
    n2, why2, raw2 = None, "", None
    if need2:
        raw2 = cached_read(cache, f"{qid}:r2", lambda: crop_read2(img), model)
        n2, why2 = parse(raw2)

    notes = []
    final = None
    if n1 is None:
        notes.append(f"read1 {why1}")
        if n2 is not None:
            notes.append("only read2 has a number")
    elif not type_ok(n1, qtype):
        notes.append(f"type-inconsistent ({qtype} numbered {n1})")
    elif need2 and n2 != n1:
        notes.append(f"read2 disagrees ({n2 if n2 is not None else why2})")
    else:
        final = n1
    if qid in sampled:
        notes.append("sampled")

    return {
        "id": qid, "subject": subject, "month": month, "year": year, "type": qtype,
        "question_no": final,
        "read1": n1 if n1 is not None else (raw1.strip()[:30] if why1 != "null" else ""),
        "read2": "" if raw2 is None else (n2 if n2 is not None else (raw2.strip()[:30] if why2 != "null" else "null")),
        "note": "; ".join(notes),
        "_n1": n1, "_n2": n2, "_sampled": qid in sampled, "_did2": raw2 is not None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--model", default=FIREWORKS_MODEL)
    args = parser.parse_args()
    model = args.model if "/" in args.model else f"accounts/fireworks/models/{args.model}"

    if not API_KEY:
        raise SystemExit("FIREWORKS_API_KEY not set (backend/.env)")

    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    rows = conn.execute(
        "SELECT id, subject, month, year, type, question_image_path FROM questions ORDER BY id"
    ).fetchall()
    conn.close()

    # Sample drawn over all ids so it is stable regardless of --limit.
    rng = random.Random(SAMPLE_SEED)
    sampled = set(rng.sample([r[0] for r in rows], round(len(rows) * SAMPLE_RATE)))
    if args.limit:
        rows = rows[:args.limit]

    cache = {}
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cache = json.load(f)
    calls_before = len(cache)

    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(process, row, cache, sampled, model): row for row in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                r = fut.result()
            except Exception as e:
                print(f"[ERROR] id={futures[fut][0]}: {type(e).__name__}")
                continue
            results.append(r)
            if r["note"] and r["note"] != "sampled":
                print(f"[{i}/{len(rows)}] id={r['id']} {r['type']} read1={r['read1']} read2={r['read2']}  {r['note']}")
            if i % 100 == 0:
                print(f"[{i}/{len(rows)}] {time.time() - start:.0f}s")
                with cache_lock, open(CACHE_PATH, "w") as f:
                    json.dump(cache, f)

    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f)

    # Flag (don't fix) numbers that appear twice within one exam.
    by_exam = defaultdict(list)
    for r in results:
        if r["question_no"] is not None:
            by_exam[(r["subject"], r["month"], r["year"], r["question_no"])].append(r)
    for group in by_exam.values():
        if len(group) > 1:
            for r in group:
                others = ",".join(str(o["id"]) for o in group if o is not r)
                r["note"] = "; ".join(filter(None, [r["note"], f"duplicate number in exam (also id {others})"]))

    results.sort(key=lambda r: r["id"])
    cols = ["id", "subject", "month", "year", "type", "question_no", "read1", "read2", "note"]
    with open(OUT_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow({**r, "question_no": "" if r["question_no"] is None else r["question_no"]})

    # Summary.
    confident = sum(r["question_no"] is not None for r in results)
    samp = [r for r in results if r["_sampled"]]
    agree = sum(r["_n1"] is not None and r["_n1"] == r["_n2"] for r in samp)
    inconsistent = sum("type-inconsistent" in r["note"] for r in results)
    dups = sum("duplicate" in r["note"] for r in results)
    print(f"\nRows: {len(results)}  confident: {confident}  blank: {len(results) - confident}")
    print(f"Sampled self-consistency: {agree}/{len(samp)}")
    print(f"Type-inconsistent read1: {inconsistent}   in duplicate groups: {dups}")
    print(f"New API calls: {len(cache) - calls_before}  (cache total {len(cache)})")
    print(f"Model: {model}")
    print(f"Runtime: {time.time() - start:.0f}s  -> {OUT_PATH}")


if __name__ == "__main__":
    main()
