"""Recut question images that YOLO cropped too tightly, using the original
exam PDFs.

The existing crops are pixel-exact sub-images of the source page rendered at
300 DPI, so each one can be located in the page by an exact match rather than
by re-running object detection (which would mean installing torch/ultralytics
and would reproduce the same bad boxes anyway).

Once located, the bottom edge is extended down to just above the next question
number -- read from the PDF's own text layer with coordinates, so the cut is
deterministic -- or to the page's bottom margin when the question is last on
the page. That recovers the answer choices the original box clipped.

Usage:
  python3 recrop_broken.py --dry-run          # report what would change
  python3 recrop_broken.py --limit 5          # recut a few, write files + DB
  python3 recrop_broken.py                    # recut everything in broken_crops.csv
"""
import argparse
import csv
import os
import re
import shutil
import sqlite3

import fitz
import numpy as np
from PIL import Image

from download_exams import exam_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))
BROKEN_CROPS_PATH = os.path.join(BASE_DIR, "broken_crops.csv")
BACKUP_DIR = os.path.join(BASE_DIR, "recrop_backup")

DPI = 300
SCALE = DPI / 72.0            # PDF points -> pixels at 300 DPI
QNUM_MAX_X_PT = 60            # question numbers sit left of the body text
BOTTOM_MARGIN_PX = 260        # keep the page footer ("[8]") out of the crop
GAP_ABOVE_NEXT_PX = 30        # breathing room above the following question
TRAILING_PAD_PX = 24          # whitespace left below the last line of content
SIDE_MARGIN_PX = 150          # page margin to stay inside when widening

# filename: question_[prefix_]Mon_Year_page_index_hash.png
NAME_RE = re.compile(r'^question_(?:(\w+)_)?([A-Za-z]{3})_(\d{4})_(\d+)_(\d+)_([0-9a-f]{8})\.png$')


def page_index_from_name(filename):
    m = NAME_RE.match(filename)
    return int(m.group(4)) if m else None


def render_page(doc, page_num):
    pix = doc.load_page(page_num).get_pixmap(dpi=DPI)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


MATCH_TOLERANCE = 6.0   # mean abs grey difference still considered the same block


def locate(crop_gray, page_gray):
    """Position of the crop inside the page, or None.

    Matches a distinctive row first (cheap), then confirms the whole block so a
    coincidental row hit can't produce a wrong offset. Confirmation allows a
    small average difference: a couple of crops were rendered by a different
    PyMuPDF build and differ from ours by antialiasing alone, which an exact
    comparison rejects even though the position is right.
    """
    ch, cw = crop_gray.shape
    ph, pw = page_gray.shape
    if ch > ph or cw > pw:
        return None

    probe_row = ch // 3
    row = crop_gray[probe_row]
    best = None

    for y in range(ph - ch + 1):
        strip = page_gray[y + probe_row]
        for x in range(pw - cw + 1):
            if strip[x] != row[0] or not np.array_equal(strip[x:x + cw], row):
                continue
            block = page_gray[y:y + ch, x:x + cw]
            if np.array_equal(block, crop_gray):
                return x, y
            diff = float(np.abs(block.astype(np.int16) - crop_gray.astype(np.int16)).mean())
            if best is None or diff < best[0]:
                best = (diff, x, y)

    if best and best[0] <= MATCH_TOLERANCE:
        return best[1], best[2]
    return None


def question_number_rows(page):
    """y positions (in 300-DPI pixels) of question numbers on the page."""
    rows = []
    for x0, y0, _x1, _y1, word, *_ in page.get_text("words"):
        if x0 < QNUM_MAX_X_PT and re.fullmatch(r"\d{1,2}", word):
            rows.append((int(y0 * SCALE), int(word)))
    return sorted(rows)


def recut(pdf_path, page_num, crop_path):
    """Returns (new_image, note) or (None, reason)."""
    doc = fitz.open(pdf_path)
    if page_num >= len(doc):
        return None, f"page {page_num} beyond end of pdf ({len(doc)} pages)"

    page = doc.load_page(page_num)
    page_img = render_page(doc, page_num)
    page_gray = np.array(page_img.convert("L"))
    crop_gray = np.array(Image.open(crop_path).convert("L"))

    pos = locate(crop_gray, page_gray)
    if pos is None:
        return None, "crop not found on that page"
    x, y = pos
    h, w = crop_gray.shape

    # Extend down to just above the next question, else to the bottom margin.
    below = [ry for ry, _num in question_number_rows(page) if ry > y + 40]
    limit = (min(below) - GAP_ABOVE_NEXT_PX) if below else (page_gray.shape[0] - BOTTOM_MARGIN_PX)
    new_bottom = max(y + h, min(limit, page_gray.shape[0]))

    # Regents lays answer choices in two columns -- (1)(3) on one row, (2)(4)
    # below -- so a box that is too narrow loses choices 3 and 4 off the right
    # edge rather than off the bottom. Widen to the page margin as well.
    new_right = max(x + w, min(page_gray.shape[1] - SIDE_MARGIN_PX, page_gray.shape[1]))

    if new_bottom <= y + h and new_right <= x + w:
        return None, "nothing to gain -- already extends to the limit"

    # Extending to fixed limits leaves blank margins when the content ends well
    # short of them; trim back to the last row and column containing ink.
    band = page_gray[y:new_bottom, x:new_right]
    ink_rows = np.where((band < 200).any(axis=1))[0]
    if len(ink_rows):
        new_bottom = max(y + h, min(new_bottom, y + int(ink_rows[-1]) + TRAILING_PAD_PX))
    ink_cols = np.where((band < 200).any(axis=0))[0]
    if len(ink_cols):
        new_right = max(x + w, min(new_right, x + int(ink_cols[-1]) + TRAILING_PAD_PX))

    note = f"+{new_bottom - (y + h)}px down, +{new_right - (x + w)}px right"
    return page_img.crop((x, y, new_right, new_bottom)), note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = list(csv.DictReader(open(BROKEN_CROPS_PATH)))
    if args.id:
        rows = [r for r in rows if int(r["id"]) == args.id]
    if args.limit:
        rows = rows[:args.limit]
    print(f"[INFO] {len(rows)} crops to recut" + (" (dry run)" if args.dry_run else ""))

    os.makedirs(BACKUP_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    fixed = skipped = 0

    for i, r in enumerate(rows, 1):
        qid = int(r["id"])
        crop_rel = r["image_path"]
        crop_path = os.path.join(IMG_ROOT, crop_rel)
        page_num = page_index_from_name(os.path.basename(crop_rel))
        pdf = exam_path(r["subject"], r["month"], int(r["year"]))

        if not pdf or page_num is None or not os.path.exists(crop_path):
            print(f"[{i}/{len(rows)}] id={qid} SKIP (missing pdf/page/crop)")
            skipped += 1
            continue

        try:
            new_img, note = recut(pdf, page_num, crop_path)
        except Exception as e:
            print(f"[{i}/{len(rows)}] id={qid} ERROR {e}")
            skipped += 1
            continue

        if new_img is None:
            print(f"[{i}/{len(rows)}] id={qid} SKIP ({note})")
            skipped += 1
            continue

        if not args.dry_run:
            backup = os.path.join(BACKUP_DIR, os.path.basename(crop_path))
            if not os.path.exists(backup):
                shutil.copy2(crop_path, backup)
            new_img.save(crop_path)
            # The recut image supersedes whatever explanation was stored.
            conn.execute("UPDATE questions SET explanation = NULL WHERE id = ?", (qid,))
            conn.commit()

        fixed += 1
        print(f"[{i}/{len(rows)}] id={qid} recut {note}")

    conn.close()
    print(f"\n[DONE] recut {fixed}, skipped {skipped}")
    if not args.dry_run:
        print(f"originals backed up to {BACKUP_DIR}")


if __name__ == "__main__":
    main()
