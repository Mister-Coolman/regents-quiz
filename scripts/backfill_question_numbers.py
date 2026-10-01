"""Record each question's number on its original exam (questions.question_no).

Method
------
Each crop is a sub-image of an exam page rendered at 300 DPI, so it is first
located on its page, then the number is read from the PDF's own text layer.
Nothing is OCR'd or guessed.

Locating. Many crops are *not* byte-identical to a page rendered today: grey
levels differ by 1 wherever text is antialiased (a different MuPDF build, or
an RGB render converted to grey), and embedded photos are resampled
differently. An exact row search misses these -- a whole exam at a time --
and the old unverified fallback then pinned some crops to the wrong place.
Instead:
  1. coarse search: normalised cross-correlation (NCC, via FFT) of the crop
     against every candidate page, both reduced 4x by block averaging. The
     page named in the filename (and its neighbours) is searched first; the
     whole exam only if that fails.
  2. full-resolution confirm: NCC in a small window around the coarse peak,
     and the mean absolute grey difference of the crop's top band (where the
     number is; photos lower down may legitimately differ more).
  3. uniqueness: the best coarse peak on any other page/position must be
     clearly lower, so a crop can't be pinned to one of two similar places.
A match is accepted only if all three hold (see ACCEPT_* below); the score
column records "ncc/head_diff/margin".

Reading the number. The bold question number is the left-margin word
(x0 < 60 pt) that is the topmost number inside the crop (it may start a
little above the top edge, or be partly cut off at the left edge). Digit
glyphs that the text layer split into separate words are joined first. The
number is rejected if the crop holds a second question number, or a line of
body text above it (i.e. the crop starts inside the previous question);
superscripts, fraction numerators and overlines on the number's own line
don't count, since they don't start at the body-text indent.

Safety checks: MCQ numbers must be 1-24 and CRQ numbers 25+, and a number may
be claimed by only one row per exam; anything else is reported, not written.

Usage (run from scripts/, unbuffered so progress shows):
  python -u backfill_question_numbers.py --dry-run     # report only
  python -u backfill_question_numbers.py               # write question_no
"""
import argparse
import csv
import hashlib
import os
import re
import sqlite3
import time
from collections import defaultdict

import numpy as np
import pymupdf as fitz
from numpy.fft import irfft2, rfft2
from PIL import Image

from download_exams import exam_path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))
REPORT_PATH = os.path.join(BASE_DIR, "question_numbers_textlayer.csv")

DPI = 300
SCALE = DPI / 72.0            # PDF points -> pixels at 300 DPI
QNUM_MAX_X_PT = 60            # question numbers sit left of the body text
NUMBER_SLACK_PX = 40          # a number may start just above the crop's top edge
HEAD_PX = 300                 # top band of the crop that holds the number
MCQ_MAX_NO = 24               # every math Regents: Part I is questions 1-24

COARSE = 4                    # block size for the coarse search
REFINE_PX = 2 * COARSE        # full-res search radius around the coarse peak
ACCEPT_NCC = 0.97             # full-res NCC of a genuine match (renderer noise only)
ACCEPT_HEAD_DIFF = 2.0        # mean abs grey difference of the top band
ACCEPT_MARGIN = 0.10          # best coarse peak must beat any rival by this much

# filename: question_[prefix_]Mon_Year_PAGE_BLOCK_hash.png, or the older
# question_PAGE_BLOCK_hash.png. PAGE is the 0-based page index in both.
NAME_RE = re.compile(r'^question_(?:(?:(\w+)_)?([A-Za-z]{3})_(\d{4})_)?(\d+)_(\d+)_([0-9a-f]{8})\.png$')


def page_hint(filename):
    m = NAME_RE.match(filename)
    return int(m.group(4)) if m else None


def reduce(img, k=COARSE):
    """Block-average an image by k (trailing rows/cols dropped)."""
    h, w = img.shape[0] // k * k, img.shape[1] // k * k
    return img[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))


def ncc_map(page, tmpl):
    """NCC of tmpl at every valid offset in page (float arrays)."""
    ph, pw = page.shape
    th, tw = tmpl.shape
    t = tmpl - tmpl.mean()
    tn = np.sqrt((t * t).sum())
    if tn == 0:
        return None
    corr = irfft2(rfft2(page) * rfft2(t[::-1, ::-1], (ph, pw)), (ph, pw))[th - 1:, tw - 1:]
    ii = np.pad(page, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    ii2 = np.pad(page * page, ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def box(s):
        return s[th:, tw:] - s[:-th, tw:] - s[th:, :-tw] + s[:-th, :-tw]

    n = th * tw
    var = np.maximum(box(ii2) - box(ii) ** 2 / n, 1e-3)
    return corr / (np.sqrt(var) * tn)


class Exam:
    """An exam PDF with its pages rendered on demand and cached."""

    def __init__(self, path):
        self.doc = fitz.open(path)
        self._gray = {}
        self._small = {}
        self._numbers = {}

    def __len__(self):
        return len(self.doc)

    def gray(self, n):
        if n not in self._gray:
            pix = self.doc.load_page(n).get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
            self._gray[n] = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width).astype(np.float64)
        return self._gray[n]

    def small(self, n):
        if n not in self._small:
            self._small[n] = reduce(self.gray(n))
        return self._small[n]

    def numbers(self, n):
        """(y_px, x0_px, x1_px, number) for each left-margin number on page n.

        Adjacent digit words on one line are joined, since some PDFs set
        "1" and "7" of "17" as separate words."""
        if n in self._numbers:
            return self._numbers[n]
        words = sorted((w for w in self.doc.load_page(n).get_text("words")
                        if re.fullmatch(r"\d+", w[4])), key=lambda w: (round(w[1]), w[0]))
        groups = []
        for x0, y0, x1, _y1, word, *_ in words:
            g = groups[-1] if groups else None
            if g and abs(g[1] - y0) < 3 and 0 <= x0 - g[2] < 2.5:
                g[2], g[3] = x1, g[3] + word
            else:
                groups.append([x0, y0, x1, word])
        out = [(y0 * SCALE, x0 * SCALE, x1 * SCALE, int(word))
               for x0, y0, x1, word in groups
               if x0 < QNUM_MAX_X_PT and len(word) <= 2]
        self._numbers[n] = out
        return out


def locate(exam, crop, pages):
    """Best placement of the crop on any of pages.

    Returns dict(page, x, y, ncc, mean_diff, head_diff, margin) or None.
    """
    ch, cw = crop.shape
    small_c = reduce(crop)
    peaks = []          # (coarse ncc, page, sx, sy)
    for p in pages:
        sp = exam.small(p)
        if small_c.shape[0] > sp.shape[0] or small_c.shape[1] > sp.shape[1]:
            continue
        m = ncc_map(sp, small_c)
        if m is None:
            return None
        sy, sx = np.unravel_index(int(np.argmax(m)), m.shape)
        best = float(m[sy, sx])
        # Rival on the same page: the best peak away from this one.
        ry0, ry1 = max(0, sy - small_c.shape[0] // 2), sy + small_c.shape[0] // 2 + 1
        rx0, rx1 = max(0, sx - small_c.shape[1] // 2), sx + small_c.shape[1] // 2 + 1
        m[ry0:ry1, rx0:rx1] = -1
        rival = float(m.max()) if m.size else -1
        peaks.append((best, p, sx, sy, rival))
    if not peaks:
        return None
    peaks.sort(reverse=True)
    best, p, sx, sy, rival = peaks[0]
    others = [pk[0] for pk in peaks[1:]] + [rival]
    margin = best - max(others) if others else 1.0

    # Full-resolution confirm in a small window around the coarse peak.
    page = exam.gray(p)
    ph, pw = page.shape
    x0 = max(0, sx * COARSE - REFINE_PX)
    y0 = max(0, sy * COARSE - REFINE_PX)
    x1 = min(pw, sx * COARSE + REFINE_PX + cw)
    y1 = min(ph, sy * COARSE + REFINE_PX + ch)
    window = page[y0:y1, x0:x1]
    if window.shape[0] < ch or window.shape[1] < cw:
        return None
    m = ncc_map(window, crop)
    if m is None:
        return None
    dy, dx = np.unravel_index(int(np.argmax(m)), m.shape)
    x, y = x0 + int(dx), y0 + int(dy)
    diff = np.abs(page[y:y + ch, x:x + cw] - crop)
    return dict(page=p, x=x, y=y, ncc=float(m[dy, dx]), mean_diff=float(diff.mean()),
                head_diff=float(diff[:HEAD_PX].mean()), margin=margin)


def accepted(loc):
    return (loc is not None and loc["ncc"] >= ACCEPT_NCC
            and loc["head_diff"] <= ACCEPT_HEAD_DIFF and loc["margin"] >= ACCEPT_MARGIN)


def number_in_crop(exam, loc, ch, cw):
    """(number, note) for the question number at the top of the crop."""
    x, y = loc["x"], loc["y"]
    cands = sorted((ny, nx0, nx1, num) for ny, nx0, nx1, num in exam.numbers(loc["page"])
                   if y - NUMBER_SLACK_PX <= ny < y + ch and nx1 > x and nx0 < x + cw)
    if not cands:
        return None, "no question number inside the crop"
    if len(cands) > 1:
        return None, "crop holds several question numbers: " + " ".join(str(c[3]) for c in cands)
    ny, nx0, nx1, num = cands[0]

    words = [(w[0] * SCALE, w[1] * SCALE, w[2] * SCALE, w[3] * SCALE)
             for w in exam.doc.load_page(loc["page"]).get_text("words") if w[4].strip()]
    inside = [w for w in words
              if x <= (w[0] + w[2]) / 2 < x + cw and y <= (w[1] + w[3]) / 2 < y + ch]
    on_line = [w[0] for w in inside if abs(w[1] - ny) < 15 and w[0] > nx1]
    indent = min(on_line) if on_line else nx1 + 20
    above = [w for w in inside if w[3] < ny and w[0] < indent + 10]
    if above:
        return None, "text above the number (crop starts inside another question)"

    notes = []
    if nx0 < x:
        notes.append("number partly cut off at the crop's left edge")
    if ny < y - 10:
        notes.append("number's top cut off at the crop's top edge")
    return num, "; ".join(notes)


def find_number(exam, crop, hint):
    """(question_no, loc, method, note) for one crop."""
    near = [p for p in (hint, hint - 1, hint + 1) if hint is not None and 0 <= p < len(exam)]
    loc = locate(exam, crop, near) if near else None
    method = "ncc-hint"
    if not accepted(loc):
        # Search the whole exam; this also measures rivals on every page.
        loc = locate(exam, crop, list(range(len(exam))))
        method = "ncc-all"
    if loc is None:
        return None, None, "none", "crop not found in exam"
    if not accepted(loc):
        return None, loc, method, "weak or ambiguous match"
    num, note = number_in_crop(exam, loc, *crop.shape)
    return num, loc, method, note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", type=str, default=None, help="comma-separated ids to process")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(questions)")}
    if "question_no" not in cols and not args.dry_run:
        conn.execute("ALTER TABLE questions ADD COLUMN question_no INTEGER")

    rows = conn.execute(
        "SELECT id, subject, month, year, type, question_image_path FROM questions ORDER BY subject, year, month, id"
    ).fetchall()
    if args.ids:
        wanted = {int(i) for i in args.ids.split(",") if i.strip()}
        rows = [r for r in rows if r[0] in wanted]
    if args.limit:
        rows = rows[:args.limit]

    start = time.time()
    exams = {}
    results = []
    placed = {}     # id -> (image digest, page, x, y, w, h), to explain clashes
    for i, (qid, subject, month, year, qtype, rel) in enumerate(rows, 1):
        key = (subject, month, year)
        pdf = exam_path(subject, month, year)
        crop_path = os.path.join(IMG_ROOT, rel)
        if not pdf or not os.path.exists(crop_path):
            results.append((qid, key, qtype, None, None, "none", "", "missing pdf or crop"))
            continue
        if key not in exams:
            exams.clear()   # one exam's pages in memory at a time (rows are grouped by exam)
            exams[key] = Exam(pdf)
        crop = np.asarray(Image.open(crop_path).convert("L"), dtype=np.float64)
        num, loc, method, note = find_number(exams[key], crop, page_hint(os.path.basename(rel)))
        # A multiple-choice question numbered past Part I (or the reverse)
        # means the crop was matched to the wrong place.
        if num is not None and (num > MCQ_MAX_NO) != (qtype != "MCQ"):
            note, num = f"number {num} doesn't fit a {qtype}", None
        page = loc["page"] if loc else None
        if loc:
            placed[qid] = (hashlib.md5(crop.tobytes()).hexdigest(), page,
                           loc["x"], loc["y"], crop.shape[1], crop.shape[0])
        score = f"{loc['ncc']:.4f}/{loc['head_diff']:.2f}/{loc['margin']:.2f}" if loc else ""
        results.append((qid, key, qtype, num, page, method, score, note))
        if i % 50 == 0 or i == len(rows):
            print(f"[{i}/{len(rows)}] {subject} {month} {year}  {time.time() - start:.0f}s", flush=True)

    # Two rows claiming the same number on one exam means one of them is
    # wrong (or a duplicate crop); leave both unset and report them.
    by_exam = defaultdict(list)
    for r in results:
        if r[3] is not None:
            by_exam[(r[1], r[3])].append(r[0])
    clash_of = {qid: ids for ids in by_exam.values() if len(ids) > 1 for qid in ids}

    def clash_kind(a, b):
        """Why rows a and b claim the same number: the same image stored
        twice, two crops of the same spot on the page, or a genuine conflict."""
        da, pa, xa, ya, wa, ha = placed[a]
        db, pb, xb, yb, wb, hb = placed[b]
        if da == db:
            return "duplicate row, identical image"
        if pa == pb and xa < xb + wb and xb < xa + wa and ya < yb + hb and yb < ya + ha:
            return "overlapping crop of the same question"
        return "conflicting match"

    found = 0
    with open(REPORT_PATH, "w", newline="") as f:
        out = csv.writer(f)
        out.writerow(["id", "subject", "month", "year", "type", "question_no", "page",
                      "method", "score", "note"])
        for qid, (subject, month, year), qtype, num, page, method, score, note in results:
            if qid in clash_of:
                others = "; ".join(f"id {o} ({clash_kind(qid, o)})" for o in clash_of[qid] if o != qid)
                note, num = f"number {num} also claimed by {others}", None
            if num is not None:
                found += 1
                if not args.dry_run:
                    conn.execute("UPDATE questions SET question_no = ? WHERE id = ?", (num, qid))
            out.writerow([qid, subject, month, year, qtype, num, page, method, score, note])
    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"[DONE] {found}/{len(results)} numbered, {len(clash_of)} in clashes, "
          f"{time.time() - start:.0f}s" + (" (dry run)" if args.dry_run else "")
          + f". Report: {REPORT_PATH}")


if __name__ == "__main__":
    main()
