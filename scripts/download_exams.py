"""Download the original NYSED exam PDFs for exams that have broken question
crops, so those crops can be recut from the source page.

Reuses the subject/filename conventions worked out in download_rating_guides.py
(including the 2025+ hyphen and the one Geometry exam that uses a "geo" prefix).

Usage:
  python3 download_exams.py            # every exam listed in broken_crops.csv
  python3 download_exams.py --all      # every exam that has questions in the DB
"""
import argparse
import csv
import os
import sqlite3

import requests

from download_rating_guides import MONTH_NUM, SUBJECT_INFO

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
BROKEN_CROPS_PATH = os.path.join(BASE_DIR, "broken_crops.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "pdfs", "exams")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _filename_candidates(prefix, mm, year):
    return [
        f"{prefix}{mm}{year}-exam.pdf",
        f"{prefix}-{mm}{year}-exam.pdf",    # 2025+ exams add a hyphen
        # A few 2017-18 sittings suffix the paper edition differently.
        f"{prefix}{mm}{year}-examp.pdf",
        f"{prefix}{mm}{year}-exama.pdf",
    ]


def exam_path(subject, month, year):
    """Local path to an already-downloaded exam PDF, or None."""
    _, prefixes = SUBJECT_INFO[subject]
    mm = MONTH_NUM[month]
    for prefix in prefixes:
        for filename in _filename_candidates(prefix, mm, year):
            path = os.path.join(OUTPUT_DIR, filename)
            if os.path.exists(path):
                return path
    return None


def download_exam(subject, month, year):
    slug, prefixes = SUBJECT_INFO[subject]
    mm = MONTH_NUM[month]
    yy = str(year)[2:]
    candidates = [f for prefix in prefixes for f in _filename_candidates(prefix, mm, year)]

    existing = exam_path(subject, month, year)
    if existing:
        return existing, "cached"

    last_error = None
    for filename in candidates:
        url = f"https://www.nysedregents.org/{slug}/{mm}{yy}/{filename}"
        out_path = os.path.join(OUTPUT_DIR, filename)
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"):
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path, "downloaded"
            last_error = f"HTTP {r.status_code} for {url}"
        except Exception as e:
            last_error = f"error: {e}"
    return None, last_error


def exams_needed(use_all):
    if use_all:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute(
            "SELECT DISTINCT subject, month, year FROM questions ORDER BY subject, year, month"
        ).fetchall()
        conn.close()
        return rows
    seen = {}
    for r in csv.DictReader(open(BROKEN_CROPS_PATH)):
        seen[(r["subject"], r["month"], int(r["year"]))] = None
    return sorted(seen)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    exams = exams_needed(args.all)
    print(f"[INFO] {len(exams)} exams to fetch")

    ok, failed = 0, []
    for subject, month, year in exams:
        if subject not in SUBJECT_INFO:
            continue
        path, status = download_exam(subject, month, year)
        if path:
            ok += 1
            print(f"[{status}] {subject} {month} {year} -> {os.path.basename(path)}")
        else:
            failed.append((subject, month, year, status))
            print(f"[FAILED] {subject} {month} {year}: {status}")

    print(f"\n[DONE] {ok}/{len(exams)} exam PDFs available. {len(failed)} failed.")
    for f in failed:
        print("  ", f)


if __name__ == "__main__":
    main()
