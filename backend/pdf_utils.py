import os

from fpdf import FPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static")


def generate_pdf(questions):
    """Build the PDF in memory and return it as bytes.

    Nothing is written to disk. Fly machines have no mounted volume, so a
    PDF written to the container would (a) accumulate forever -- roughly
    1.4 MB per request with nothing pruning it -- and (b) vanish on every
    restart, breaking the download links already sitting in chat history.
    Questions live permanently in the database, so the download endpoint
    rebuilds the file on demand instead.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    answer_key = []
    for q in questions:
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        subject = q.get("subject", "")
        month = q.get("month", "")
        year = q.get("year", "")
        header = f"{subject} - {month} {year}"
        header_safe = header.encode('latin1', errors='ignore').decode('latin1')
        pdf.cell(0, 8, header_safe, ln=True)

        image_path = os.path.join(IMG_DIR.rstrip("images/"), q["question_image_path"])
        try:
            if os.path.exists(image_path):
                page_w = pdf.w - 2 * pdf.l_margin
                img_w = 180
                x = pdf.l_margin + (page_w - img_w) / 2
                y = pdf.get_y() + 5
                pdf.image(image_path, x=x, y=y, w=img_w)
                pdf.ln(h=(img_w * 0.75) + 10)
                answer_key.append(q["correct_answer"])
            else:
                pdf.multi_cell(0, 10, f"Image not found: {image_path}")
        except Exception as e:
            pdf.multi_cell(0, 10, f"Error loading image: {image_path}\n{e}")

    if answer_key:
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, "Answer Key:")
        for i, ans in enumerate(answer_key, start=1):
            pdf.multi_cell(0, 10, f"Page {i}: {ans}")

    # fpdf 1.x returns the document as a latin-1 string when dest="S".
    return pdf.output(dest="S").encode("latin-1")
