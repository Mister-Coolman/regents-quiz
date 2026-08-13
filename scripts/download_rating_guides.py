"""Download official NYSED Rating Guide PDFs for every exam that has CRQ
questions in the DB. These contain the real point-by-point scoring rubrics,
used by backfill_crq_rubrics.py.

Usage:
  python3 download_rating_guides.py
"""
import os
import sqlite3

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
OUTPUT_DIR = os.path.join(BASE_DIR, "pdfs", "ratingguides")
os.makedirs(OUTPUT_DIR, exist_ok=True)

MONTH_NUM = {"January": "1", "June": "6", "August": "8"}

# subject -> (URL slug, [filename prefixes to try, most common first])
SUBJECT_INFO = {
    "Algebra I": ("algebraone", ["algone"]),
    "Algebra II": ("algebratwo", ["algtwo"]),
    "Geometry": ("geometryre", ["geom", "geo"]),  # August 2023 used "geo" instead of "geom"
}


def _filename_candidates(prefix, mm, year):
    return [
        f"{prefix}{mm}{year}-rg.pdf",
        f"{prefix}-{mm}{year}-rg.pdf",       # 2025+ exams add a hyphen
        f"{prefix}{mm}{year}-rgrevp.pdf",    # occasionally a "revised" rating guide instead
    ]


def rating_guide_path(subject, month, year):
    """Returns the local path to an already-downloaded rating guide, or None."""
    _, prefixes = SUBJECT_INFO[subject]
    mm = MONTH_NUM[month]
    for prefix in prefixes:
        for filename in _filename_candidates(prefix, mm, year):
            path = os.path.join(OUTPUT_DIR, filename)
            if os.path.exists(path):
                return path
    return None


def download_rating_guide(subject, month, year):
    slug, prefixes = SUBJECT_INFO[subject]
    mm = MONTH_NUM[month]
    yy = str(year)[2:]

    candidates = [f for prefix in prefixes for f in _filename_candidates(prefix, mm, year)]

    for filename in candidates:
        out_path = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(out_path):
            return out_path, "cached"

    last_error = None
    for filename in candidates:
        url = f"https://www.nysedregents.org/{slug}/{mm}{yy}/{filename}"
        out_path = os.path.join(OUTPUT_DIR, filename)
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"):
                with open(out_path, "wb") as f:
                    f.write(r.content)
                return out_path, "downloaded"
            last_error = f"HTTP {r.status_code} for {url}"
        except Exception as e:
            last_error = f"error: {e}"

    return None, last_error


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT subject, month, year FROM questions WHERE type = 'CRQ' ORDER BY subject, year, month")
    exams = cur.fetchall()
    conn.close()

    print(f"[INFO] {len(exams)} distinct exams with CRQ questions")

    ok, failed = 0, []
    for subject, month, year in exams:
        if subject not in SUBJECT_INFO:
            print(f"[WARN] unknown subject '{subject}', skipping")
            continue
        path, status = download_rating_guide(subject, month, year)
        if path:
            print(f"[{status}] {subject} {month} {year} -> {os.path.basename(path)}")
            ok += 1
        else:
            print(f"[FAILED] {subject} {month} {year}: {status}")
            failed.append((subject, month, year, status))

    print(f"\n[DONE] {ok}/{len(exams)} rating guides available. {len(failed)} failed.")
    for f in failed:
        print("  ", f)


if __name__ == "__main__":
    main()
