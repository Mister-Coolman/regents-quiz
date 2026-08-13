import os

from fpdf import FPDF

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static")
OUTPUT_PDF_DIR = os.path.abspath(os.path.join(BASE_DIR, "output_pdf"))

# Created at import rather than assumed to exist: the directory holds only
# generated PDFs, so it is excluded from the Docker image (and git can't track
# an empty dir), which would otherwise make every PDF write fail in production.
os.makedirs(OUTPUT_PDF_DIR, exist_ok=True)


def generate_pdf(questions, filename):
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

    path = os.path.join(OUTPUT_PDF_DIR, filename)
    pdf.output(path)
    return path
