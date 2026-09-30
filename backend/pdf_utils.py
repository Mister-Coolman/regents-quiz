"""Printable practice sets laid out like a Regents exam booklet.

Cover page, Part I (multiple choice, several to a page with room for
computations), Part II (constructed response, with work space), a bubble
answer sheet, and the answer key on the last page so it can be torn off.

Each question is a 300-DPI crop from the original exam. The crop already
carries the question's number on that exam in bold, so the set doesn't
renumber it: every question gets a caption with its place in the set and
the exam it came from.
"""
import os
import re
import struct

from fpdf import FPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static")

MATH_SUBJECTS = {"Algebra I", "Geometry", "Algebra II"}

# US Letter, the size the Regents booklets are printed on.
PAGE_W, PAGE_H = 215.9, 279.4
MARGIN_X = 19.0
MARGIN_TOP = 16.0
MARGIN_BOTTOM = 22.0
CONTENT_W = PAGE_W - 2 * MARGIN_X

CROP_DPI = 300
# Crops print at their true size (about 131 mm for a full-width question).
# Multiple choice keeps a column on the right for computations, as on the
# exam; constructed response may use the full width.
MCQ_MAX_W = 132.0
CRQ_MAX_W = CONTENT_W
MCQ_GAP = 14.0          # least scratch room below a multiple-choice question
CRQ_WORK_SPACE = 55.0   # least work space below a constructed-response question
CAPTION_H = 7.0

INK = (18, 19, 23)
INK_2 = (94, 94, 99)
RULE = (190, 190, 195)


def _text(s):
    """fpdf 1.x core fonts are Latin-1 only."""
    return str(s).encode("latin-1", errors="ignore").decode("latin-1")


def _image_path(q):
    """Resolve a question's crop, refusing anything outside static/."""
    rel = q.get("question_image_path") or ""
    path = os.path.normpath(os.path.join(IMG_DIR, rel))
    if not path.startswith(IMG_DIR + os.sep) or not os.path.isfile(path):
        return None
    return path


def _png_size(path):
    """Pixel size from the PNG header, so a question's height is known
    before it is placed and page breaks never cut through one."""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return None


def _placed_size(path, max_w):
    """Width and height in mm at print size. A crop taller than a page is
    scaled down to fit one."""
    size = _png_size(path) if path else None
    if not size or not size[0]:
        return max_w, 12.0
    px_w, px_h = size
    w = min(px_w * 25.4 / CROP_DPI, max_w)
    max_h = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM - 40
    if w * px_h / px_w > max_h:
        w = max_h * px_w / px_h
    return w, w * px_h / px_w


def _exam_label(q):
    return f"{q.get('month', '')} {q.get('year', '')}".strip()


def _source(q, multi_subject):
    """Where a question came from, e.g. "June 2024" or "Geometry, June 2024"."""
    label = _exam_label(q)
    return f"{q.get('subject', '')}, {label}" if multi_subject else label


def _set_title(questions):
    subjects = []
    for q in questions:
        s = q.get("subject") or ""
        if s and s not in subjects:
            subjects.append(s)
    if not subjects:
        return "Regents"
    if len(subjects) == 1:
        return subjects[0]
    return ", ".join(subjects[:-1]) + " and " + subjects[-1]


def _exams_in_order(questions):
    """Distinct exams, newest first."""
    months = {"January": 1, "June": 6, "August": 8}
    seen = {}
    for q in questions:
        key = (int(q.get("year") or 0), months.get(q.get("month"), 0))
        seen[key] = _exam_label(q)
    return [seen[k] for k in sorted(seen, reverse=True)]


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


class ExamPDF(FPDF):
    def __init__(self, title):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.booklet_title = title
        self.show_folio = False      # no page number on the cover
        self.show_continue = False   # "GO RIGHT ON" only between question pages
        self.set_margins(MARGIN_X, MARGIN_TOP, MARGIN_X)
        self.set_auto_page_break(False)
        self.set_text_color(*INK)
        self.set_draw_color(*INK)

    def footer(self):
        # The cover carries no folio; numbering starts at [1] on Part I.
        if not self.show_folio or self.page_no() == 1:
            return
        y = PAGE_H - 14
        self.set_y(y)
        self.set_font("Times", "", 10)
        self.set_text_color(*INK_2)
        self.cell(CONTENT_W / 3, 5, _text(self.booklet_title), 0, 0, "L")
        self.set_text_color(*INK)
        self.set_font("Times", "", 11)
        self.cell(CONTENT_W / 3, 5, f"[{self.page_no() - 1}]", 0, 0, "C")
        if self.show_continue:
            self.set_font("Times", "B", 9)
            self.cell(CONTENT_W / 3, 5, "GO RIGHT ON TO THE NEXT PAGE", 0, 0, "R")

    def room(self):
        return PAGE_H - MARGIN_BOTTOM - self.get_y()

    # ---- building blocks ----

    def rule(self, weight=0.2, color=INK):
        self.set_draw_color(*color)
        self.set_line_width(weight)
        y = self.get_y()
        self.line(MARGIN_X, y, PAGE_W - MARGIN_X, y)
        self.set_draw_color(*INK)

    def write_line(self, label, width=70):
        """A labelled blank to write on, e.g. Name ________."""
        self.set_font("Times", "", 12)
        x, y = self.get_x(), self.get_y()
        self.cell(self.get_string_width(label) + 2, 7, label, 0, 0)
        lx = self.get_x()
        self.set_line_width(0.2)
        self.line(lx, y + 6, lx + width, y + 6)
        self.set_xy(lx + width + 8, y)

    def part_header(self, name, instructions):
        self.set_font("Times", "B", 16)
        self.cell(0, 9, name, 0, 1, "C")
        self.set_font("Times", "I", 11)
        self.multi_cell(0, 5.2, _text(instructions), 0, "L")
        self.ln(3)
        self.rule(0.5)
        self.ln(5)

    def computations_note(self):
        """The exam's right-hand column, repeated at the top of each page."""
        y = self.get_y()
        self.set_font("Times", "I", 9)
        self.set_text_color(*INK_2)
        x = MARGIN_X + MCQ_MAX_W + 6
        self.set_xy(x, y)
        self.multi_cell(PAGE_W - MARGIN_X - x, 4.2, "Use this space for\ncomputations.", 0, "R")
        self.set_text_color(*INK)
        self.set_xy(MARGIN_X, y)

    def caption(self, n, q, multi_subject):
        """Set position and source exam, above the crop."""
        y = self.get_y()
        self.set_font("Times", "B", 10)
        self.cell(self.get_string_width(f"Item {n}") + 1.5, 5, f"Item {n}", 0, 0)
        self.set_font("Times", "", 10)
        self.set_text_color(*INK_2)
        self.cell(0, 5, _text(f"   {_source(q, multi_subject)} Regents"), 0, 0)
        self.set_text_color(*INK)
        self.set_xy(MARGIN_X, y + CAPTION_H)

    def question(self, n, q, multi_subject, size, after):
        path = _image_path(q)
        w, h = size
        self.caption(n, q, multi_subject)
        y = self.get_y()
        if path:
            self.image(path, x=MARGIN_X, y=y, w=w)
        else:
            self.set_font("Times", "I", 11)
            self.cell(0, 8, "This question's image is unavailable.", 0, 0)
        self.set_xy(MARGIN_X, y + h + after)


def _cover(pdf, title, questions, mcqs, crqs):
    pdf.add_page()
    pdf.set_y(30)
    pdf.set_font("Times", "", 12)
    pdf.cell(0, 6, "Practice from past New York State", 0, 1, "C")
    pdf.cell(0, 6, "Regents High School Examinations", 0, 1, "C")
    pdf.ln(10)
    size = 34
    pdf.set_font("Times", "B", size)
    while size > 18 and pdf.get_string_width(_text(title.upper())) > CONTENT_W:
        size -= 2
        pdf.set_font("Times", "B", size)
    pdf.cell(0, 14, _text(title.upper()), 0, 1, "C")
    pdf.ln(4)
    pdf.set_font("Times", "", 13)
    pdf.cell(0, 7, _text(_plural(len(questions), "question")), 0, 1, "C")
    pdf.ln(14)

    pdf.set_x(MARGIN_X + 8)
    pdf.write_line("Name", 88)
    pdf.write_line("Date", 40)
    pdf.ln(18)

    pdf.rule(0.5)
    pdf.ln(6)
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 6, "Notice to the student", 0, 1, "L")
    pdf.ln(1)
    pdf.set_font("Times", "", 11.5)

    notes = []
    if mcqs:
        notes.append(f"Part I has {_plural(len(mcqs), 'multiple-choice question')}. "
                     "Mark each answer on the answer sheet at the back of this booklet.")
    if crqs:
        notes.append(f"Part {'II' if mcqs else 'I'} has "
                     f"{_plural(len(crqs), 'constructed-response question')}. "
                     "Write your work and answer in the space below each question. "
                     "Show all work: a correct answer with no work shown may not receive full credit.")
    notes.append("Each item is labelled with the exam it came from. The bold number printed "
                 "with a question is its number on that exam, not its place in this set.")
    subjects = {q.get("subject") for q in questions}
    if subjects & MATH_SUBJECTS:
        tools = "a graphing calculator and a straightedge (ruler)"
        if "Geometry" in subjects:
            tools = "a graphing calculator, a straightedge (ruler) and a compass"
        notes.append(f"As on the exam, {tools} should be available.")
    notes.append("The answer key is on the last page. Remove it before you begin.")

    for note in notes:
        pdf.set_x(MARGIN_X)
        pdf.cell(6, 5.6, chr(149), 0, 0)  # Latin-1 bullet in fpdf's cp1252 core fonts
        pdf.multi_cell(CONTENT_W - 6, 5.6, _text(note), 0, "L")
        pdf.ln(1.5)

    exams = _exams_in_order(questions)
    pdf.ln(3)
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 6, "Exams in this set", 0, 1, "L")
    pdf.ln(1)
    pdf.set_font("Times", "", 11.5)
    pdf.multi_cell(0, 5.6, _text(", ".join(exams)), 0, "L")

    pdf.set_y(PAGE_H - 30)
    pdf.rule(0.2, RULE)
    pdf.ln(3)
    pdf.set_font("Times", "I", 9)
    pdf.set_text_color(*INK_2)
    pdf.multi_cell(0, 4.2, "Regents Prep practice material. The questions are reproduced from "
                   "past Regents examinations; this booklet is not an official New York State "
                   "Education Department document.", 0, "C")
    pdf.set_text_color(*INK)


def _paginate(items, max_w, gap, first_room, room):
    """Group questions into pages so none is split and each keeps at least
    `gap` of space below it."""
    pages, page, left = [], [], first_room
    for n, q in items:
        size = _placed_size(_image_path(q), max_w)
        need = CAPTION_H + size[1] + gap
        if page and need > left:
            pages.append(page)
            page, left = [], room
        page.append((n, q, size))
        left -= need
    if page:
        pages.append(page)
    return pages


def _questions(pdf, items, multi_subject, part, instructions, max_w, gap, computations):
    """Lay out one part. The space left on each page is shared out below its
    questions, the way the exam spreads questions down the page."""
    pdf.add_page()
    pdf.part_header(part, instructions)
    bottom = PAGE_H - MARGIN_BOTTOM
    pages = _paginate(items, max_w, gap, bottom - pdf.get_y(), bottom - MARGIN_TOP)
    for i, page in enumerate(pages):
        if i:
            pdf.add_page()
        if computations:
            pdf.computations_note()
        used = sum(CAPTION_H + h for _, _, (_, h) in page)
        # Share the page's spare room out, but don't stretch a page that
        # ends a part: a lone question keeps a sensible gap below it.
        spare = max(pdf.room() - used, 0) / len(page)
        after = spare if i < len(pages) - 1 or len(page) > 1 else max(gap, min(spare, 90))
        for n, q, size in page:
            pdf.question(n, q, multi_subject, size, min(after, max(pdf.room() - CAPTION_H - size[1], 0)))


def _answer_sheet(pdf, mcqs, has_crqs, multi_subject):
    pdf.add_page()
    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 9, "Answer Sheet", 0, 1, "C")
    pdf.ln(2)
    pdf.set_x(MARGIN_X + 8)
    pdf.write_line("Name", 88)
    pdf.write_line("Date", 40)
    pdf.ln(12)
    pdf.set_font("Times", "B", 13)
    pdf.cell(0, 7, "Part I", 0, 1, "L")
    pdf.set_font("Times", "I", 10.5)
    pdf.cell(0, 5, "Fill in the bubble for your answer to each item.", 0, 1, "L")
    pdf.ln(4)
    pdf.rule(0.5)
    pdf.ln(5)

    row_h, r, col_w = 9.5, 2.9, CONTENT_W / 2
    label_w = 36 if multi_subject else 26
    bottom = PAGE_H - MARGIN_BOTTOM - 12
    top = pdf.get_y()
    per_col = int((bottom - top) // row_h)
    last_y = top
    slot = 0
    # Fill the left column, then the right, then continue on a new page.
    for n, q in mcqs:
        if slot == per_col * 2:
            pdf.add_page()
            top = last_y = pdf.get_y()
            per_col = int((bottom - top) // row_h)
            slot = 0
        col, row = divmod(slot, per_col)
        slot += 1
        x = MARGIN_X + col * col_w
        y = top + row * row_h
        last_y = max(last_y, y + row_h)
        pdf.set_xy(x, y)
        pdf.set_font("Times", "B", 12)
        pdf.cell(12, 2 * r, str(n), 0, 0, "R")
        pdf.set_font("Times", "", 8)
        pdf.set_text_color(*INK_2)
        pdf.cell(label_w, 2 * r, _text("  " + _source(q, multi_subject)), 0, 0, "L")
        pdf.set_text_color(*INK)
        pdf.set_line_width(0.3)
        for k in range(4):
            cx = x + 14 + label_w + k * 9
            pdf.ellipse(cx, y, 2 * r, 2 * r)
            pdf.set_xy(cx, y)
            pdf.set_font("Times", "", 9)
            pdf.cell(2 * r, 2 * r, str(k + 1), 0, 0, "C")

    if has_crqs:
        pdf.set_xy(MARGIN_X, last_y + 6)
        pdf.set_font("Times", "I", 10.5)
        pdf.cell(0, 5, "Answer Part II in the space below each question in the booklet.", 0, 1, "L")


def _answer_key(pdf, numbered, multi_subject):
    pdf.show_continue = False
    pdf.add_page()
    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 9, "Answer Key", 0, 1, "C")
    pdf.set_font("Times", "I", 10.5)
    pdf.cell(0, 5, "Constructed-response items are scored with the rubric from their exam.", 0, 1, "C")
    pdf.ln(5)

    widths = (18, 76, 48, CONTENT_W - 142)
    heads = ("Item", "Exam", "Type", "Answer")

    def header_row():
        pdf.set_font("Times", "B", 11)
        for w, h in zip(widths, heads):
            pdf.cell(w, 7, h, "B", 0, "L")
        pdf.ln()

    header_row()
    for n, q in numbered:
        if pdf.room() < 8:
            pdf.add_page()
            header_row()
        if q.get("type") == "MCQ":
            kind, answer = "Multiple choice", f"({q.get('correct_answer', '')})"
        else:
            kind, answer = "Constructed response", "Rubric"
        pdf.set_font("Times", "B", 11)
        pdf.cell(widths[0], 7, str(n), 0, 0, "L")
        pdf.set_font("Times", "", 11)
        pdf.cell(widths[1], 7, _text(_source(q, multi_subject) + " Regents"), 0, 0, "L")
        pdf.cell(widths[2], 7, kind, 0, 0, "L")
        pdf.set_font("Times", "B" if q.get("type") == "MCQ" else "I", 11)
        pdf.cell(widths[3], 7, _text(answer), 0, 1, "L")
        pdf.set_draw_color(*RULE)
        pdf.set_line_width(0.1)
        pdf.line(MARGIN_X, pdf.get_y(), PAGE_W - MARGIN_X, pdf.get_y())
        pdf.set_draw_color(*INK)


def pdf_filename(questions):
    slug = re.sub(r"[^a-z0-9]+", "-", _set_title(questions).lower().replace(" and ", " ")).strip("-")
    return f"{slug}-practice.pdf"


def generate_pdf(questions):
    """Build the PDF in memory and return it as bytes.

    Nothing is written to disk. Fly machines have no mounted volume, so a
    PDF written to the container would (a) accumulate forever -- roughly
    1.4 MB per request with nothing pruning it -- and (b) vanish on every
    restart, breaking the download links already sitting in chat history.
    Questions live permanently in the database, so the download endpoint
    rebuilds the file on demand instead.
    """
    title = _set_title(questions)
    multi_subject = " and " in title

    # Multiple choice first, as on the exam; the set order is kept within each part.
    ordered = [q for q in questions if q.get("type") == "MCQ"] + \
              [q for q in questions if q.get("type") != "MCQ"]
    numbered = list(enumerate(ordered, start=1))
    mcqs = [(n, q) for n, q in numbered if q.get("type") == "MCQ"]
    crqs = [(n, q) for n, q in numbered if q.get("type") != "MCQ"]

    pdf = ExamPDF(title)
    pdf.set_title(_text(f"{title} Practice"))
    pdf.set_creator("Regents Prep")

    _cover(pdf, title, questions, mcqs, crqs)
    pdf.show_folio = True
    pdf.show_continue = True

    if mcqs:
        _questions(
            pdf, mcqs, multi_subject, "Part I",
            f"Answer all {_plural(len(mcqs), 'question')} in this part. For each question, "
            "choose the number of the choice that best completes the statement or answers "
            "the question, and fill in its bubble on the answer sheet.",
            MCQ_MAX_W, MCQ_GAP, computations=True,
        )
    if crqs:
        _questions(
            pdf, crqs, multi_subject, "Part II" if mcqs else "Part I",
            f"Answer all {_plural(len(crqs), 'question')} in this part. Clearly indicate the "
            "necessary steps, including appropriate formula substitutions, diagrams, graphs "
            "and charts. Write your answer in the space below the question.",
            CRQ_MAX_W, CRQ_WORK_SPACE, computations=False,
        )
    if mcqs:
        pdf.show_continue = False
        _answer_sheet(pdf, mcqs, bool(crqs), multi_subject)
    _answer_key(pdf, numbered, multi_subject)

    # fpdf 1.x returns the document as a latin-1 string when dest="S".
    return pdf.output(dest="S").encode("latin-1")
