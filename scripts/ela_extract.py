"""Extract Part 1 (reading comprehension) of an ELA Regents exam.

For each passage: its printed lines with their printed line numbers,
paragraph/stanza breaks, italics, footnote markers and glosses, and the
attribution exactly as printed. For each question: an image crop (the
student-facing display), the stem and choices as text (internal only: line
references, explanations, alt text), the answer key, the learning standard,
and the passage lines the stem cites.

Everything is read from the PDF's text layer by position; nothing is OCR'd.
Hard gates stop the run if anything doesn't add up (see `gate`), and a review
page puts every passage next to its page images for a human check.

The output contains third-party copyrighted passage text, so it goes to
scripts/ela_out/ (git-ignored; the repo is public). Never move it into a
tracked path.

Usage (run from scripts/):
  python ela_extract.py 626 --download   # fetch the exam PDF and scoring key first
  python ela_extract.py 626              # June 2026 -> ela_out/626/
  python ela_extract.py 825 --diagnose   # print the layout facts the parser relies on

Each exam's files live in pdfs/ela/<code>/: the exam PDF (*exam*.pdf) and
the scoring key workbook (*sk*.xlsx). --download tries NYSED's usual names;
if they've changed, save the two files there by hand from
https://www.nysedregents.org/hsela/.
"""
import argparse
import html
import json
import os
import re
import sys
import zipfile
from xml.etree import ElementTree

import glob

import numpy as np
import pymupdf as fitz

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_DIR = os.path.join(BASE_DIR, "pdfs", "ela")
OUT_DIR = os.path.join(BASE_DIR, "ela_out")
MAPS_PATH = os.path.join(BASE_DIR, "..", "docs", "ela", "research", "maps.json")

MONTH_NO = {"January": 1, "June": 6, "August": 8}

# Every Regents Exam in ELA with today's Part 1 (3 passages, 24 multiple-
# choice questions): the Common Core exam from June 2014, then the Next
# Generation exam. The older Comprehensive English exam is a different test.
# Administrations cancelled for COVID-19 are left out; if NYSED has no files
# for a listed code, --download says so.
CANCELLED = {("June", 2020), ("August", 2020), ("January", 2021), ("January", 2022)}
EXAMS = {}
for _year in range(2014, 2027):
    for _month in ("January", "June", "August"):
        if (_year, _month) == (2014, "January") or (_month, _year) in CANCELLED:
            continue
        EXAMS[f"{MONTH_NO[_month]}{_year % 100:02d}"] = {"month": _month, "year": _year}

# Passage types where the usual order (A literary, B poem, C informational)
# doesn't hold and detection gets it wrong. {"code": {"label": "kind"}}.
# Kinds: literary, poem, informational. Check each exam's review page.
KINDS_PATH = os.path.join(BASE_DIR, "ela_kinds.json")
NYSED_BASE = "https://www.nysedregents.org/hsela"


def file_stems(meta):
    """NYSED's file name stems for an administration, most likely first."""
    mmyyyy = f"{MONTH_NO[meta['month']]}{meta['year']}"
    return [f"reela-{mmyyyy}", f"reela{mmyyyy}"]


def exam_files(code):
    """(exam PDF, scoring key) in pdfs/ela/<code>/, whatever they're named.
    The key may be the Excel workbook or, for older exams, a PDF."""
    src = os.path.join(PDF_DIR, code)
    pdfs = sorted(glob.glob(os.path.join(src, "*exam*.pdf")))
    if not pdfs:   # some years' exam file is just reela62015.pdf
        pdfs = sorted(p for p in glob.glob(os.path.join(src, "*.pdf"))
                      if not re.search(r"(sk|rg|rating|conv|key)[^/]*\.pdf$", p, re.I))
    keys = sorted(glob.glob(os.path.join(src, "*sk*.xlsx"))) or sorted(glob.glob(os.path.join(src, "*sk*.pdf")))
    if not pdfs or not keys:
        sys.exit(f"[ela] need the exam PDF and the scoring key (*sk*.xlsx or *sk*.pdf) in {src}; "
                 f"try --download, or save them from {NYSED_BASE}/")
    return pdfs[0], keys[0]


def download(code, meta):
    import requests
    src = os.path.join(PDF_DIR, code)
    os.makedirs(src, exist_ok=True)
    for what, suffixes in (("exam", ("-exam.pdf", ".pdf")), ("scoring key", ("-sk.xlsx", "-sk.pdf"))):
        tried = []
        for suffix in suffixes:
            for stem in file_stems(meta):
                url = f"{NYSED_BASE}/{code}/{stem}{suffix}"
                tried.append(stem + suffix)
                resp = requests.get(url, timeout=60)
                if resp.ok and len(resp.content) > 1000 and not resp.content.lstrip().startswith(b"<"):
                    with open(os.path.join(src, stem + suffix), "wb") as f:
                        f.write(resp.content)
                    print(f"[ela] downloaded {url}")
                    break
            else:
                continue
            break
        else:
            print(f"[ela] couldn't find the {what} for {code} (tried {', '.join(tried)}); "
                  f"save it by hand from {NYSED_BASE}/ into {src}")


def near(a, b, tol=0.6):
    """Font sizes differ by a few tenths between years and PDF exports."""
    return abs((a or 0) - b) <= tol

TEXT_WIDTH = 612 - 2 * 72 # a letter page's text block, in points
BODY_SIZE = 11.5          # passage and question text
HEADING_SIZE = 14.0       # "Reading Comprehension Passage A" and titles
FOOTNOTE_MAX_SIZE = 8.5   # glosses at the foot of the page
FOOTER_TOP = 740          # running footer: "Regents Exam in ELA ... [3] [OVER]"
LINE_NO_MAX_X = 60        # printed line numbers sit in the left margin
COLUMN_SPLIT = 306        # question pages are two columns (612 pt wide)
QUESTION_NO_X = (42, 318) # x of question numbers in each column
CROP_DPI = 150
SUPERSCRIPT_MAX_SIZE = 9  # footnote markers inside body text
NUM_RE = re.compile(r"^\s*(\d{1,2})\s+\S")
CHOICE_RE = re.compile(r"^\(([1-4])\)\s*")
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


# ---------------------------------------------------------------- text layer

class Line:
    """One printed line: its text, position, italic ranges and the footnote
    markers inside it (as character offsets into `text`)."""

    def __init__(self, page, bbox, size, runs):
        self.page = page
        self.x0, self.y0, self.x1, self.y1 = bbox
        self.size = size
        text, italic, notes = "", [], []
        bold_flags = []
        for run_text, is_italic, is_super, *rest in runs:
            if is_super and run_text.strip().isdigit():
                notes.append({"n": int(run_text.strip()), "at": len(text.rstrip())})
                continue
            if run_text.strip():
                bold_flags.append(bool(rest and rest[0]))
            if is_italic and run_text.strip():
                italic.append([len(text), len(text) + len(run_text)])
            text += run_text
        self.text = text.rstrip()
        self.italic = [[a, min(b, len(self.text))] for a, b in italic if a < len(self.text)]
        self.notes = notes
        self.bold = bool(bold_flags) and all(bold_flags)

    def __repr__(self):
        return f"<p{self.page} {self.x0:.0f},{self.y0:.0f} {self.text[:40]!r}>"


def page_lines(page, pno):
    """Lines rebuilt from characters. PyMuPDF inserts a space after every
    ligature glyph ("fi guring", "infl uences"); those spaces overlap the
    glyph before them, while real spaces start after it, so overlapping spaces
    are dropped."""
    out = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            runs, size, prev_x1 = [], None, None
            for span in line["spans"]:
                chars = []
                for c in span["chars"]:
                    if c["c"] == " " and prev_x1 is not None and c["bbox"][0] < prev_x1 - 0.5:
                        continue
                    chars.append(c["c"])
                    if c["c"] != " ":
                        prev_x1 = c["bbox"][2]
                if not chars:
                    continue
                is_super = span["size"] < SUPERSCRIPT_MAX_SIZE and line["spans"][0]["size"] >= 10
                runs.append(("".join(chars), bool(span["flags"] & 2), is_super, bool(span["flags"] & 16)))
                if not is_super and size is None:
                    size = round(span["size"], 1)
            if runs and "".join(r[0] for r in runs).strip():
                out.append(Line(pno, line["bbox"], size or 0, runs))
    out.sort(key=lambda l: (round(l.y0), l.x0))
    return [l for l in out if l.y0 < FOOTER_TOP]


# ---------------------------------------------------------------- passages

def join_title(lines):
    return join_with_notes(lines)[0]


def join_with_notes(lines):
    """Printed lines joined into one string, and their footnote markers with
    offsets into that string."""
    out, notes = "", []
    for l in lines:
        lead = len(l.text) - len(l.text.lstrip())
        t = l.text.strip()
        if out and not (out.endswith("—") or t.startswith("—")):
            out += " "
        base = len(out)
        notes += [{"n": n["n"], "at": max(0, min(len(t), n["at"] - lead)) + base} for n in l.notes]
        out += t
    return out, notes


def parse_footnotes(lines):
    """Glosses like '2transient — passing or temporary', possibly wrapped."""
    notes = []
    for l in lines:
        m = re.match(r"^(\d+)\s*(.+)$", l.text.strip())
        if m and " — " in m.group(2):
            term, gloss = m.group(2).split(" — ", 1)
            notes.append({"n": int(m.group(1)), "term": term.strip(), "gloss": gloss.strip()})
        elif notes:
            notes[-1]["gloss"] += " " + l.text.strip()
    return notes


def extract_passages(doc, part1_pages):
    """Walk Part 1 page by page, splitting it into passages and question areas."""
    passages, questions_area = [], []
    cur, state = None, "intro"
    for pno in part1_pages:
        lines = page_lines(doc[pno], pno)
        for l in lines:
            t = l.text.strip()
            if near(l.size, HEADING_SIZE) and t.startswith("Reading Comprehension Passage"):
                cur = {"label": t.rsplit(" ", 1)[-1], "heading": [], "body": [], "numbers": [],
                       "foot": [], "attribution": [], "pages": [pno], "questions_area": []}
                passages.append(cur)
                state = "title"
                continue
            if cur is None:
                continue
            if pno not in cur["pages"]:
                cur["pages"].append(pno)
            if l.size <= FOOTNOTE_MAX_SIZE:
                cur["foot"].append(l)
                continue
            if state == "title":
                if near(l.size, HEADING_SIZE):
                    cur["heading"].append(l)
                    continue
                state = "body"
            if state == "body":
                if l.x0 < LINE_NO_MAX_X and t.isdigit():
                    cur["numbers"].append(l)
                    continue
                if l.x0 > 300 and t.startswith("—"):
                    state = "attribution"
                else:
                    cur["body"].append(l)
                    continue
            if state == "attribution":
                if l.x0 > 300 and (not cur["attribution"] or l.y0 - cur["attribution"][-1].y0 < 20):
                    cur["attribution"].append(l)
                    continue
                state = "questions"
            if state == "questions":
                cur["questions_area"].append(l)
    return passages


def looks_like_poem(body, lines):
    """Many lines end well short of the margin without a paragraph break
    after them: verse, not prose."""
    widths = sorted(b.x1 - b.x0 for b in body)
    if len(widths) < 4:
        return False
    # Measured against the page's text width too: every line of a poem may
    # be short, so its own longest lines are no guide.
    full = max(widths[int(len(widths) * 0.9)], 0.85 * TEXT_WIDTH)
    short = 0
    for i, (b, ln) in enumerate(zip(body, lines)):
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        paragraph_end = nxt is None or nxt.get("indent") or nxt.get("gap_before")
        if (b.x1 - b.x0) < 0.75 * full and not paragraph_end:
            short += 1
    return short > 0.3 * len(body)


DEFAULT_KINDS = {"A": "literary", "B": "poem", "C": "informational"}
KIND_OVERRIDES = {}


def passage_kind(label, body, lines):
    """literary, poem or informational. An entry in ela_kinds.json wins;
    otherwise verse is detected from the layout and prose falls back on the
    usual order (A literary, C informational; a B that isn't verse, literary)."""
    override = KIND_OVERRIDES.get(label)
    if override:
        return override
    if looks_like_poem(body, lines):
        return "poem"
    default = DEFAULT_KINDS.get(label, "literary")
    return "literary" if default == "poem" else default


def fully_italic(l):
    """Every visible character of the line is italic."""
    covered = set()
    for a, b in l.italic:
        covered.update(range(a, b))
    return bool(l.text.strip()) and all(i in covered for i, ch in enumerate(l.text) if not ch.isspace())


def build_stimulus(p):
    """Number the body lines and check them against the printed numbers.

    Some exams open a passage with an italic introduction ("In this excerpt,
    ...") that isn't part of the numbered text. Leading all-italic lines are
    set aside as the intro when that makes the printed numbers line up."""
    body = p["body"]
    lead = 0
    while lead < len(body) and fully_italic(body[lead]):
        lead += 1
    # Simplest reading first: every line numbered; then the same without an
    # italic intro; then anchored on the printed numbers, which lets a few
    # lines (subheadings, captions) go unnumbered.
    attempts = [(0, False)] + ([(lead, False)] if lead else []) + ([(lead, True)] if lead else []) + [(0, True)]
    best = None
    for skip, anchored in attempts:
        lines, mismatches = number_lines(body[skip:], p["numbers"], anchored)
        if best is None or len(mismatches) < len(best[2]):
            best = (skip, lines, mismatches)
        if not mismatches:
            break
    skip, lines, mismatches = best
    intro = body[:skip]
    title_line = p["heading"]
    title, title_notes = join_with_notes(title_line)
    intro_text, intro_notes = join_with_notes(intro)
    kind = passage_kind(p["label"], body[skip:], lines)
    return {
        "label": p["label"],
        "kind": kind,
        "title": title,
        "title_notes": title_notes,
        "intro": intro_text or None,
        "intro_notes": intro_notes,
        "lines": lines,
        "line_count": sum(1 for ln in lines if ln["n"] is not None),
        "printed_numbers": [int(n.text) for n in p["numbers"]],
        "attribution": [{"text": l.text.strip(),
                         "italic": [[a - (len(l.text) - len(l.text.lstrip())), b - (len(l.text) - len(l.text.lstrip()))]
                                    for a, b in l.italic]}
                        for l in p["attribution"]],
        "footnotes": parse_footnotes(p["foot"]),
        "pages": p["pages"],
    }, mismatches


def row_of(body, num):
    """Index of the body line printed on the same row as a margin number."""
    hits = [i for i, b in enumerate(body) if b.page == num.page and abs(b.y0 - num.y0) < 4]
    return hits[0] if len(hits) == 1 else None


def heading_score(body, i):
    """How much line i looks like a printed line that carries no number: a
    subheading or caption. 0 means it reads as ordinary text."""
    l = body[i]
    prev = body[i - 1] if i > 0 else None
    nxt = body[i + 1] if i + 1 < len(body) else None
    widths = sorted(b.x1 - b.x0 for b in body)
    full = widths[len(widths) * 3 // 4] if widths else 1
    gap_before = prev is None or prev.page != l.page or l.y0 - prev.y0 > 20
    gap_after = nxt is None or nxt.page != l.page or nxt.y0 - l.y0 > 20
    score = 0
    if l.bold:
        score += 3
    if l.size and abs(l.size - BODY_SIZE) > 0.6:
        score += 3
    if fully_italic(l):
        score += 1
    if (l.x1 - l.x0) < 0.6 * full and gap_before and gap_after:
        score += 2
    return score


def unnumbered_lines(body, numbers):
    """Indices of body lines that carry no line number, worked out from the
    printed margin numbers: between two printed numbers k1 and k2 there are
    exactly k2 - k1 numbered lines, so any extra lines there are unnumbered,
    and the most heading-like ones are taken. Returns (indices, problems)."""
    anchors = sorted((row_of(body, n), int(n.text)) for n in numbers if row_of(body, n) is not None)
    if not anchors:
        return set(), ["no printed line number lines up with a text line"]
    skip, problems = set(), []
    spans = [(-1, 0)] + anchors
    for (i1, k1), (i2, k2) in zip(spans, spans[1:]):
        extra = (i2 - i1) - (k2 - k1)
        if extra < 0:
            problems.append(f"fewer text lines than numbers between printed {k1 or 'start'} and {k2}")
            continue
        if extra:
            pool = sorted(range(i1 + 1, i2), key=lambda i: -heading_score(body, i))[:extra]
            if any(heading_score(body, i) == 0 for i in pool):
                problems.append(f"{extra} unnumbered line(s) between printed {k1 or 'start'} and {k2}, "
                                f"but none looks like a heading; check the review page")
            skip.update(pool)
    # After the last printed number only clear headings go unnumbered.
    skip.update(i for i in range(anchors[-1][0] + 1, len(body)) if heading_score(body, i) >= 3)
    return skip, problems


def number_lines(body, numbers, anchored=False):
    """Body lines numbered 1, 2, 3..., and where that disagrees with the
    numbers printed in the margin. Anchored, lines the printed numbers show
    to be unnumbered get n = None (and heading = True if set in bold)."""
    skip, problems = unnumbered_lines(body, numbers) if anchored else (set(), [])
    lines, prev, n = [], None, 0
    for idx, l in enumerate(body):
        gap = prev is not None and l.page == prev.page and l.y0 - prev.y0 > 20
        if idx not in skip:
            n += 1
        lines.append({
            "n": None if idx in skip else n,
            **({"heading": True} if idx in skip and l.bold else {}),
            "text": l.text,
            "indent": l.x0 > 80,              # first line of a prose paragraph
            "gap_before": bool(gap),          # stanza break or section break
            "italic": l.italic,
            "notes": l.notes,
            "page": l.page,
            "y": round(l.y0, 1),
        })
        prev = l
    mismatches = []
    for num in numbers:
        same_row = [ln for ln, b in zip(lines, body) if b.page == num.page and abs(b.y0 - num.y0) < 4]
        if len(same_row) != 1 or same_row[0]["n"] != int(num.text):
            mismatches.append(f"printed {num.text} on page {num.page} y={num.y0:.0f} "
                              f"matches {[x['n'] for x in same_row]}")
    return lines, mismatches + problems


# ---------------------------------------------------------------- questions

def merge_bare_numbers(lines):
    """Join a question number printed as its own piece of text ("17") to the
    stem beside it on the same row, so it reads "17 The description...".
    Only bare numbers are joined: choices side by side stay separate."""
    import copy
    used, out = set(), []
    for i, l in enumerate(lines):
        if i in used:
            continue
        if l.text.strip().isdigit():
            partner = min((j for j, m in enumerate(lines) if j > i and j not in used and m.page == l.page
                           and abs(m.y0 - l.y0) < 3 and 0 <= m.x0 - l.x1 < 40),
                          key=lambda j: lines[j].x0, default=None)
            if partner is not None:
                m = copy.copy(l)
                m.text = f"{l.text.strip()}  {lines[partner].text.strip()}"
                m.x1, m.y1 = lines[partner].x1, max(l.y1, lines[partner].y1)
                used.add(partner)
                out.append(m)
                continue
        out.append(l)
    return out


def question_blocks(doc, passage, first_no):
    """Split the question area into questions, in reading order.

    A question starts at the line beginning with the next expected number
    (first_no, first_no + 1, ...) at the left edge of its column. Matching
    the sequence, rather than fixed x positions, copes with layouts that
    shift between years and with right-aligned two-digit numbers. A page
    whose question area spans the full width is read as one column."""
    lines = merge_bare_numbers(passage["questions_area"])
    # One column only if nothing on the page starts in the right-hand column
    # (a single wide line, like the directions, doesn't make a page one column).
    pages = {l.page for l in lines}
    full_width = {pg for pg in pages
                  if not any(l.page == pg and l.x0 >= COLUMN_SPLIT for l in lines)
                  and any(l.page == pg and l.x1 > COLUMN_SPLIT + 40 for l in lines)}

    def col(l):
        return 0 if l.page in full_width or l.x0 < COLUMN_SPLIT else 1

    ordered = sorted(lines, key=lambda l: (l.page, col(l), round(l.y0), l.x0))
    # The left edge of each column, from lines that start with a number only:
    # a caption or figure further left mustn't move it.
    left = {}
    for l in ordered:
        if NUM_RE.match(l.text):
            key = (l.page, col(l))
            left[key] = min(left.get(key, 1e9), l.x0)

    def at_question_x(l):
        c = col(l)
        known = abs(l.x0 - QUESTION_NO_X[c if c in (0, 1) else 0]) < 3   # the June 2026 layout
        return known or l.x0 - left.get((l.page, c), l.x0) < 15

    starts, expect = [], first_no
    for i, l in enumerate(ordered):
        m = NUM_RE.match(l.text)
        if m and int(m.group(1)) == expect and at_question_x(l):
            starts.append(i)
            expect += 1

    blocks = []
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(ordered)
        head = ordered[i]
        own = ordered[i:end]
        segment = [l for l in own if (l.page, col(l)) == (head.page, col(head))]
        block = {
            "no": int(NUM_RE.match(head.text).group(1)),
            "page": head.page,
            "col": "full" if head.page in full_width else col(head),
            "lines": segment,
            "crop_lines": segment,
            "spills": False,
        }
        # A question normally ends with its column. Whatever follows in the
        # next column before the next question (a caption, a photo credit,
        # "Go on") isn't part of it. Only when its own column lacks one of
        # the four choices does the question really continue there; then
        # the crop would be incomplete, and the gate stops on it.
        if not all(parse_question(block)[1]) and len(segment) != len(own):
            block["lines"], block["spills"] = own, True
        blocks.append(block)
    return blocks


EMBEDDED_CHOICE_RE = re.compile(r"\s+(?=\([1-4]\)\s)")


def split_choice_row(line, text):
    """A row of side-by-side choices ("(3) the cost  (4) the risk") can come
    out of the PDF as one line. Split it at each inner "(n)", giving every
    piece an x estimated from where it falls in the line."""
    parts = EMBEDDED_CHOICE_RE.split(text)
    if len(parts) == 1:
        return [(line.x0, text)]
    out, pos = [], 0
    width = max(1.0, line.x1 - line.x0)
    for part in parts:
        at = text.index(part, pos)
        # A little to the left of the estimate, so a wrapped line under this
        # choice (which starts at its true x) still counts as right of it.
        out.append((line.x0 + width * at / max(1, len(text)) - (10 if at else 0), part))
        pos = at + len(part)
    return out


def choices_started(pieces):
    return any(CHOICE_RE.match(t) for _, t in pieces)


def parse_question(block):
    """Stem and choices from the lines, in reading order. Choices may sit in
    two sub-columns ((1)(3) / (2)(4)) and wrap onto indented lines."""
    stem, choices, anchors = [], {}, {}
    pieces = []
    for i, l in enumerate(block["lines"]):     # already in reading order
        t = l.text.strip()
        if i == 0:
            t = re.sub(r"^\d{1,2}\s+", "", t)   # the question number
        pieces.extend(split_choice_row(l, t) if (CHOICE_RE.match(t) or choices_started(pieces)) else [(l.x0, t)])
    for x0, t in pieces:
        m = CHOICE_RE.match(t)
        if m:
            k = int(m.group(1))
            choices[k] = t[m.end():].strip()
            anchors[k] = x0
        elif choices:
            # Continuation of the nearest choice to its left. When choices share
            # an x (one choice per row), that's the latest one above: a
            # wrapped "(4) concern over the coyote's declining / population"
            # belongs to (4), not (1). anchors keeps the order choices appeared.
            left_of = [k for k in anchors if anchors[k] <= x0]
            nearest = max((anchors[k] for k in left_of), default=None)
            # Within 25pt counts as the same column: x for split rows is an estimate.
            k = [k for k in left_of if anchors[k] >= nearest - 25][-1] if left_of else None
            if k is not None:
                choices[k] = (choices[k] + " " + t).strip()
        else:
            stem.append(t)
    return " ".join(stem).strip(), [choices.get(k, "") for k in (1, 2, 3, 4)]


def crop_question(doc, block, out_path):
    """Render the question's column band at CROP_DPI and trim to the ink."""
    page = doc[block["page"]]
    crop_lines = block.get("crop_lines") or block["lines"]
    xs = [l.x0 for l in crop_lines] + [l.x1 for l in crop_lines]
    ys = [l.y0 for l in crop_lines] + [l.y1 for l in crop_lines]
    col_x0, col_x1 = {0: (30, COLUMN_SPLIT), 1: (COLUMN_SPLIT, 590), "full": (30, 590)}[block["col"]]
    rect = fitz.Rect(max(col_x0, min(xs) - 4), min(ys) - 4, min(col_x1, max(xs) + 4), max(ys) + 4)
    pix = page.get_pixmap(clip=rect, dpi=CROP_DPI, colorspace=fitz.csGRAY)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width)
    ink = np.argwhere(img < 200)
    pad = 12
    if len(ink):
        (y0, x0), (y1, x1) = ink.min(0), ink.max(0)
        y0, x0 = max(0, y0 - pad), max(0, x0 - pad)
        y1, x1 = min(img.shape[0], y1 + pad), min(img.shape[1], x1 + pad)
        scale = 72 / CROP_DPI
        rect = fitz.Rect(rect.x0 + x0 * scale, rect.y0 + y0 * scale, rect.x0 + x1 * scale, rect.y0 + y1 * scale)
        pix = page.get_pixmap(clip=rect, dpi=CROP_DPI)
    pix.save(out_path)
    return [round(v, 1) for v in rect], pix.width, pix.height


LINE_REF_PATTERNS = [
    (re.compile(r"\blines?\s+(\d+)(?:\s+(?:through|to)\s+|\s*[-–]\s*)(\d+)", re.I), "range"),
    (re.compile(r"\blines?\s+(\d+)\s+and\s+(\d+)", re.I), "pair"),
    (re.compile(r"\blines?\s+(\d+)\b", re.I), "single"),
]


def line_refs(stem, stimulus):
    """Passage lines cited by the STEM only. Choices of 'which lines best
    support' items cite lines too, and highlighting those would hand the
    student the answer."""
    refs, taken = [], []
    for pat, kind in LINE_REF_PATTERNS:
        for m in pat.finditer(stem):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            a = int(m.group(1))
            if kind == "range":
                refs.append({"start": a, "end": int(m.group(2)), "source": m.group(0)})
            elif kind == "pair":
                # "lines 33 and 35" cites two lines, not the span between them.
                b = int(m.group(2))
                refs += [{"start": a, "end": a, "source": m.group(0)}, {"start": b, "end": b, "source": m.group(0)}]
            else:
                refs.append({"start": a, "end": a, "source": m.group(0)})
    m = re.search(r"\bthe (" + "|".join(ORDINALS) + r") (stanza|paragraph)\b", stem, re.I)
    if m:
        unit_no = ORDINALS.index(m.group(1).lower()) + 1
        span = unit_span(stimulus, m.group(2).lower(), unit_no)
        if span:
            refs.append({"start": span[0], "end": span[1], "source": m.group(0)})
    return refs


def unit_span(stimulus, unit, k):
    """First and last line of the k-th stanza (gap-separated) or paragraph
    (indent-started) of a passage."""
    starts = [ln["n"] for ln in stimulus["lines"] if ln["n"] is not None and
              (ln["n"] == 1 or (unit == "stanza" and ln["gap_before"]) or (unit == "paragraph" and ln["indent"]))]
    if k > len(starts):
        return None
    end = starts[k] - 1 if k < len(starts) else stimulus["line_count"]
    return starts[k - 1], end


# ---------------------------------------------------------------- key, standards

def read_key(path):
    return read_key_pdf(path) if path.lower().endswith(".pdf") else read_key_xlsx(path)


def read_key_pdf(pdf_path):
    """{question number: answer} from a PDF scoring key, whose table rows
    read like "June '15   7   3   MC   1   1"."""
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)
    key = {}
    for m in re.finditer(r"(?m)^\D*?\b(\d{1,2})\s+([1-4])\s+MC\b", text):
        key.setdefault(int(m.group(1)), m.group(2))
    if len(key) < 24:
        # Some PDFs put each cell on its own line: number, answer, "MC".
        cells = [t.strip() for t in text.split("\n") if t.strip()]
        for i in range(len(cells) - 2):
            if cells[i].isdigit() and cells[i + 1] in "1234" and cells[i + 2] == "MC":
                key.setdefault(int(cells[i]), cells[i + 1])
    return {n: k for n, k in key.items() if 1 <= n <= 24}


def read_key_xlsx(xlsx_path):
    """{question number: answer} from the scoring-key workbook (column C is
    the question number, D the key), read without openpyxl."""
    z = zipfile.ZipFile(xlsx_path)
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    sheet = ElementTree.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.iter(f"{{{ns['m']}}}row"):
        vals = {}
        for c in row.findall("m:c", ns):
            v = c.find("m:v", ns)
            if v is None:
                continue
            val = shared[int(v.text)] if c.get("t") == "s" else v.text
            vals[re.sub(r"\d", "", c.get("r"))] = val.strip()
        rows.append(vals)
    key = {}
    for r in rows:
        q, k, kind = r.get("C", ""), r.get("D", ""), r.get("E", "")
        if q.replace(".0", "").isdigit() and kind == "MC":
            key[int(float(q))] = k.replace(".0", "")
    return key


def normalise_standard(raw):
    """'R.4(11-12)' -> 'R.4'; the grade band is the same for every item."""
    return re.sub(r"\s*\(.*$", "", raw or "").strip()


# ---------------------------------------------------------------- gates

def gate(stimuli, questions, mismatches, key):
    errors, warnings = list(mismatches), []
    nos = [q["no"] for q in questions]
    if nos != list(range(1, 25)):
        errors.append(f"expected questions 1-24, got {nos}; the next one wasn't found at the left edge of a "
                      f"column after question {nos[-1] if nos else 0} (run --diagnose)")
    for s in stimuli:
        if s["printed_numbers"] != list(range(5, s["line_count"] + 1, 5))[:len(s["printed_numbers"])]:
            errors.append(f"passage {s['label']}: printed numbers {s['printed_numbers']} aren't every 5th line")
        if s["line_count"] - (s["printed_numbers"][-1] if s["printed_numbers"] else 0) >= 5:
            errors.append(f"passage {s['label']}: {s['line_count']} lines but last printed number is {s['printed_numbers'][-1:]}")
        markers = sorted({n["n"] for ln in s["lines"] for n in ln["notes"]} | {n["n"] for n in s["title_notes"]}
                         | {n["n"] for n in s.get("intro_notes", [])})
        glosses = sorted(f["n"] for f in s["footnotes"])
        if markers != glosses:
            errors.append(f"passage {s['label']}: footnote markers {markers} != glosses {glosses}")
        if not s["attribution"]:
            errors.append(f"passage {s['label']}: no attribution")
        for ln in s["lines"]:
            # '$' is fine here (prices in an article): passages render as
            # plain text. '||' was the old session-snapshot separator.
            if "||" in ln["text"]:
                errors.append(f"passage {s['label']} line {ln['n']}: contains '||'")
    for q in questions:
        if not all(q["choices"]):
            errors.append(f"Q{q['no']}: missing choice text {q['choices']}")
        if str(q["key"]) not in ("1", "2", "3", "4"):
            errors.append(f"Q{q['no']}: key {q['key']!r}")
        stim = next(s for s in stimuli if s["label"] == q["passage"])
        for r in q["line_refs"]:
            if not (1 <= r["start"] <= r["end"] <= stim["line_count"]):
                errors.append(f"Q{q['no']}: cites lines {r['start']}-{r['end']} outside passage {q['passage']} (1-{stim['line_count']})")
        for t in [q["stem"]] + q["choices"]:
            if "||" in t:
                errors.append(f"Q{q['no']}: contains '||'")
        if not q["standard"]:
            warnings.append(f"Q{q['no']}: no standard in maps.json")
        if re.search(r"\b(photograph|image|graphic|illustration|picture)\b", q["stem"], re.I):
            warnings.append(f"Q{q['no']}: stem refers to an image; hold the set unless the figure ships")
    if len(key) != 24:
        errors.append(f"scoring key has {len(key)} MC answers")
    return errors, warnings


# ---------------------------------------------------------------- review page

def spans_with_italic(text, italic):
    """[(start, end, is_italic)] covering the whole text."""
    out, last = [], 0
    for a, b in sorted(italic):
        if a > last:
            out.append((last, a, False))
        out.append((a, b, True))
        last = b
    if last < len(text):
        out.append((last, len(text), False))
    return out


def with_marks(text, notes, e):
    """Escaped text with footnote markers as superscripts at their offsets."""
    out, last = [], 0
    for n in sorted(notes, key=lambda n: n["at"]):
        out.append(e(text[last:n["at"]]) + f"<sup>{n['n']}</sup>")
        last = n["at"]
    return "".join(out) + e(text[last:])


def review_html(meta, stimuli, questions, page_pngs, errors, warnings):
    e = html.escape
    out = [f"""<!doctype html><meta charset="utf-8"><title>ELA review: {e(meta['month'])} {meta['year']}</title>
<style>
body {{ font: 15px -apple-system, system-ui, sans-serif; margin: 24px; background: #EEF0F2; color: #121317; }}
section {{ background: #fff; border-radius: 12px; padding: 20px; margin: 0 0 20px; }}
.pair {{ display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 20px; align-items: start; }}
.pages img {{ width: 100%; border: 1px solid #ccc; margin-bottom: 8px; }}
/* One printed line per row, never wrapped, so rows match the page image
   one to one; a long line scrolls sideways instead. */
.text {{ overflow-x: auto; }}
.ln {{ display: grid; grid-template-columns: 3em max-content; font-family: Georgia, serif;
       font-size: 13px; line-height: 1.6; white-space: pre; }}
.ln span:first-child {{ color: #5E5E63; text-align: right; padding-right: .8em; }}
.ln.gap {{ margin-top: 1em; }} .ln.indent span:last-child {{ padding-left: 1.5em; }}
.ln.cited span:first-child {{ color: #121317; font-weight: 600; }}
sup {{ color: #0066CC; }} .q img {{ max-width: 100%; border: 1px solid #ddd; }}
.q {{ border-top: 1px solid #ddd; padding: 14px 0; }} .meta {{ color: #5E5E63; font-size: 13px; }}
.err {{ color: #C8281E; }} .warn {{ color: #8a5a00; }}
.intro {{ font-family: Georgia, serif; font-size: 13px; line-height: 1.6; margin: 0 0 12px 3em; max-width: 60ch; }}
</style>
<h1>{e(meta['month'])} {meta['year']} ELA Part 1: extraction review</h1>
<p>Check each passage against its page images line by line (text, line numbers, italics, footnotes,
breaks), then each question crop against its parsed stem, key and cited lines.</p>"""]
    out.append("<section><h2>Gates</h2>" + ("".join(f"<p class=err>{e(x)}</p>" for x in errors) or "<p>All hard gates pass.</p>")
               + "".join(f"<p class=warn>{e(x)}</p>" for x in warnings) + "</section>")
    for s in stimuli:
        cited = {n for q in questions if q["passage"] == s["label"] for r in q["line_refs"] for n in range(r["start"], r["end"] + 1)}
        rows = []
        for ln in s["lines"]:
            text = ln["text"]
            pieces, last = [], 0
            marks = sorted([(a, b, "i") for a, b in ln["italic"]] + [(n["at"], n["at"], n["n"]) for n in ln["notes"]])
            for a, b, kind in marks:
                pieces.append(e(text[last:a]))
                if kind == "i":
                    pieces.append(f"<i>{e(text[a:b])}</i>")
                    last = b
                else:
                    pieces.append(f"<sup>{kind}</sup>")
                    last = a
            pieces.append(e(text[last:]))
            cls = " ".join(c for c, on in (("gap", ln["gap_before"]), ("indent", ln["indent"]), ("cited", ln["n"] in cited)) if on)
            num = "" if ln["n"] is None else (ln["n"] if ln["n"] % 5 == 0 or ln["n"] in cited else "")
            if ln.get("heading"):
                pieces = ["<b>", *pieces, "</b>"]
            rows.append(f"<div class='ln {cls}'><span>{num}</span><span>{''.join(pieces)}</span></div>")
        notes = "".join(f"<p class=meta><sup>{f['n']}</sup> {e(f['term'])}: {e(f['gloss'])}</p>" for f in s["footnotes"])
        attr = "<br>".join(
            "".join(f"<i>{e(a['text'][x:y])}</i>" if k else e(a['text'][x:y])
                    for x, y, k in spans_with_italic(a["text"], a["italic"]))
            for a in s["attribution"])
        imgs = "".join(f"<img src='{e(page_pngs[p])}' alt='page {p + 1}'>" for p in s["pages"])
        # Shown above the passage in italics, unnumbered, as the reader shows it.
        intro = f"<p class=intro><i>{with_marks(s['intro'], s.get('intro_notes', []), e)}</i></p>" if s.get("intro") else ""
        out.append(f"""<section><h2>Passage {e(s['label'])} ({e(s['kind'])}): {with_marks(s['title'], s['title_notes'], e)}</h2>
<p class=meta>{s['line_count']} lines; printed numbers {s['printed_numbers']}; pages {[p + 1 for p in s['pages']]}</p>
<div class=pair><div class=text>{intro}{''.join(rows)}<p style="text-align:right">{attr}</p>{notes}</div><div class=pages>{imgs}</div></div></section>""")
    out.append("<section><h2>Questions</h2>")
    for q in questions:
        refs = ", ".join(f"{r['start']}-{r['end']} ({e(r['source'])})" for r in q["line_refs"]) or "none"
        choices = "".join(f"<li>{e(c)}</li>" for c in q["choices"])
        out.append(f"""<div class=q><p class=meta>Q{q['no']} &middot; passage {q['passage']} &middot; key ({q['key']}) &middot;
{e(q['standard'] or '?')} &middot; cited lines: {refs}</p><div class=pair><img src='{e(q['crop'])}' alt=''>
<div><p>{e(q['stem'])}</p><ol>{choices}</ol></div></div></div>""")
    out.append("</section>")
    return "\n".join(out)


# ---------------------------------------------------------------- main

def diagnose(doc, part1_pages):
    """The layout facts the parser depends on, for an exam it can't read.
    No passage text is printed beyond headings and the first words of lines."""
    from collections import Counter
    print(f"[diag] {len(doc)} pages; Part 1 pages (0-based): {part1_pages}")
    if not part1_pages:
        for pno, page in enumerate(doc):
            heads = [l.strip() for l in page.get_text().splitlines() if l.strip().startswith("Part")]
            if heads:
                print(f"[diag] page {pno}: {heads[:4]}")
        return
    sizes, margin_nums, qnum_x, choice_x = Counter(), [], Counter(), Counter()
    for pno in part1_pages:
        for l in page_lines(doc[pno], pno):
            sizes[l.size] += 1
            t = l.text.strip()
            if l.size >= 12.5:
                print(f"[diag] p{pno} heading size {l.size} x={l.x0:.0f}: {t[:60]!r}")
            if t.isdigit() and l.x0 < 120:
                margin_nums.append((pno, round(l.x0), t))
            if NUM_RE.match(t) and not t.isdigit():
                qnum_x[round(l.x0)] += 1
            if CHOICE_RE.match(t):
                choice_x[round(l.x0)] += 1
    print(f"[diag] font sizes (size: lines): {dict(sorted(sizes.items()))}")
    print(f"[diag] expected: heading {HEADING_SIZE}, body {BODY_SIZE}, footnotes <= {FOOTNOTE_MAX_SIZE}")
    print(f"[diag] margin numbers (page, x, n), first 12: {margin_nums[:12]}; parser wants x < {LINE_NO_MAX_X}")
    print(f"[diag] x of lines starting with a number (top 6): {qnum_x.most_common(6)}; parser wants {QUESTION_NO_X}")
    print(f"[diag] x of choice lines '(1)'... (top 6): {choice_x.most_common(6)}")
    print(f"[diag] page width {doc[part1_pages[0]].rect.width:.0f}, footer cut at y={FOOTER_TOP}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("code", help="administration code, e.g. 626 for June 2026")
    parser.add_argument("--download", action="store_true", help="fetch the exam PDF and scoring key first")
    parser.add_argument("--diagnose", action="store_true", help="print the layout facts the parser relies on")
    args = parser.parse_args()
    if args.code not in EXAMS:
        sys.exit(f"[ela] unknown code {args.code}; add it to EXAMS (known: {', '.join(EXAMS)})")
    meta = EXAMS[args.code]
    if os.path.exists(KINDS_PATH):
        KIND_OVERRIDES.update(json.load(open(KINDS_PATH)).get(args.code, {}))
    if args.download:
        download(args.code, meta)
    exam_pdf, key_xlsx = exam_files(args.code)
    out = os.path.join(OUT_DIR, args.code)
    os.makedirs(os.path.join(out, "crops"), exist_ok=True)
    os.makedirs(os.path.join(out, "pages"), exist_ok=True)

    doc = fitz.open(exam_pdf)
    part1_pages, started = [], False
    for pno, page in enumerate(doc):
        text = page.get_text()
        if re.search(r"^Part 1\s*$", text, re.M):
            started = True
        if started and re.search(r"^Part 2\s*$", text, re.M):
            break
        if started:
            part1_pages.append(pno)

    if args.diagnose:
        diagnose(doc, part1_pages)
        return
    if not part1_pages:
        sys.exit("[ela] no page with a 'Part 1' heading; run with --diagnose and share the output")

    raw = extract_passages(doc, part1_pages)
    stimuli, mismatches = [], []
    for p in raw:
        s, mm = build_stimulus(p)
        stimuli.append(s)
        mismatches += [f"passage {p['label']}: {m}" for m in mm]

    key = read_key(key_xlsx)
    standards = {}
    if os.path.exists(MAPS_PATH):
        standards = json.load(open(MAPS_PATH)).get(args.code, {}).get("qs", {})

    questions = []
    next_no, spilled = 1, []
    for p, s in zip(raw, stimuli):
        blocks = question_blocks(doc, p, next_no)
        if blocks:
            next_no = blocks[-1]["no"] + 1
        for b in blocks:
            if b["spills"]:
                spilled.append(b["no"])
            stem, choices = parse_question(b)
            crop_name = f"crops/q{b['no']:02d}.png"
            rect, w, h = crop_question(doc, b, os.path.join(out, crop_name))
            questions.append({
                "no": b["no"],
                "passage": s["label"],
                "stem": stem,
                "choices": choices,
                "key": key.get(b["no"]),
                "standard_raw": standards.get(str(b["no"])),
                "standard": normalise_standard(standards.get(str(b["no"]))),
                "line_refs": line_refs(stem, s),
                "crop": crop_name,
                "crop_px": [w, h],
                "crop_rect": {"page": b["page"], "rect": rect},
            })
    questions.sort(key=lambda q: q["no"])

    figures = []
    for pno in part1_pages:
        for info in doc[pno].get_image_info():
            owner = next((s["label"] for s in stimuli if pno in s["pages"]), None)
            figures.append({"page": pno, "bbox": [round(v) for v in info["bbox"]], "passage": owner})

    errors, warnings = gate(stimuli, questions, mismatches, key)
    for s in stimuli:
        if s["kind"] != DEFAULT_KINDS.get(s["label"]) and s["label"] not in KIND_OVERRIDES:
            warnings.append(f"passage {s['label']}: read as {s['kind']}, not the usual "
                            f"{DEFAULT_KINDS.get(s['label'])}; check it, and set it in ela_kinds.json if wrong")
    for no in spilled:
        errors.append(f"Q{no}: continues into the next column or page; its crop would be incomplete")
    for f in figures:
        warnings.append(f"passage {f['passage']}: image on page {f['page'] + 1} at {f['bbox']}; decide whether it is decorative")

    page_pngs = {}
    for pno in part1_pages:
        name = f"pages/p{pno + 1:02d}.png"
        doc[pno].get_pixmap(dpi=110).save(os.path.join(out, name))
        page_pngs[pno] = name

    bundle = {"exam": {"subject": "ELA", **{k: meta[k] for k in ("month", "year")}, "code": args.code,
                       "source": f"{NYSED_BASE}/{args.code}/{os.path.basename(exam_pdf)}"},
              "stimuli": stimuli, "questions": questions, "figures": figures,
              "gates": {"errors": errors, "warnings": warnings}}
    with open(os.path.join(out, "bundle.json"), "w") as f:
        json.dump(bundle, f, indent=1, ensure_ascii=False)
    with open(os.path.join(out, "review.html"), "w") as f:
        f.write(review_html(meta, stimuli, questions, page_pngs, errors, warnings))

    for s in stimuli:
        print(f"[ela] passage {s['label']} ({s['kind']}): {s['title']!r}, {s['line_count']} lines, "
              f"{len(s['footnotes'])} footnotes, pages {[p + 1 for p in s['pages']]}")
    print(f"[ela] {len(questions)} questions, {sum(bool(q['line_refs']) for q in questions)} cite lines")
    for w in warnings:
        print(f"[warn] {w}")
    for e in errors:
        print(f"[error] {e}")
    print(f"[ela] review: {os.path.join(out, 'review.html')}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
