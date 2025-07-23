# extract_questions.py
import os
import sqlite3
from PIL import Image
from pdf2image import convert_from_path
from pix2tex.cli import LatexOCR

ocr_model = LatexOCR()

def init_db(db_path="questions.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_pdf TEXT,
            page_number INTEGER,
            image_path TEXT,
            math_latex TEXT,
            topic TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    return conn

def extract_full_pages_with_ocr(pdf_path, image_dir, conn):
    if not os.path.exists(image_dir):
        os.makedirs(image_dir)

    base_filename = os.path.splitext(os.path.basename(pdf_path))[0]
    pages = convert_from_path(pdf_path, dpi=300)

    for i, page in enumerate(pages):
        try:
            image_filename = f"{base_filename}_page{i+1}.png"
            image_path = os.path.join(image_dir, image_filename)
            page.save(image_path, "PNG")

            # Run pix2tex on full page image
            latex = ocr_model(Image.open(image_path))

            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO questions (source_pdf, page_number, image_path, math_latex)
                VALUES (?, ?, ?, ?)
            ''', (base_filename, i + 1, image_path, latex))
            conn.commit()

            print(f"[Page {i+1}] Saved {image_filename} → LaTeX: {latex}")

        except Exception as e:
            print(f"Failed page {i+1}: {e}")