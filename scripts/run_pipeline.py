# run_pipeline.py
import os
from PIL import Image
from ultralytics import YOLO
from surya.layout import LayoutPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
from datetime import datetime
import uuid
import sqlite3
from bs4 import BeautifulSoup
import pandas as pd

import fitz
import pdfplumber
import re

# import `ollama`
import json
import subprocess

DB_PATH = "../backend/regentsqs.db"
MODEL_PATH = "models/best2.pt"
OUTPUT_DIR = "../backend/images"
os.makedirs(OUTPUT_DIR, exist_ok=True)

cluster_map = {
    "N-RN.B": "The Real Number System",
    "N-Q.A": "Quantities",
    "N-QA": "Quantities",
    "A-SSE.A": "Seeing Structure in Expressions",
    "A-SSE.B": "Seeing Structure in Expressions",
    "A-APR.A": "Arithmetic with Polynomials and Rational Expressions",
    "A-APR.B": "Arithmetic with Polynomials and Rational Expressions",
    "A-CED.A": "Creating Equations",
    "A-REI.A": "Reasoning with Equations and Inequalities",
    "A-REI.B": "Solving One Variable Equations",
    "A-REI.C": "Systems of Equations",
    "A-REI.D": "Reasoning with Equations and Inequalities",
    "F-IF.A": "Interpreting Functions",
    "F-IF.B": "Interpreting Functions",
    "F-IF.C": "Interpreting Functions",
    "F-BF.A": "Building Functions",
    "F-BF.B": "Building Functions",
    "F-LE.A": "Linear, Quadratic, and Exponential Models",
    "F-LE.B": "Linear, Quadratic, and Exponential Models",
    "S-ID.A": "Interpreting Categorical and Quantitative Data",
    "S-ID.B": "Interpreting Categorical and Quantitative Data",
    "S-ID.C": "Interpreting Categorical and Quantitative Data"
}

def classify_topic(text):
    prompt = f"""Classify the following Algebra I question into only one of the following topics: The Real Number System, Quantities, Seeing Structure in Expressions, Arithmetic with Polynomials and Rational
Expressions, Creating Equations, Reasoning with Equations and Inequalities, Interpreting Functions, Building Functions, 'Linear, Quadratic, and Exponential Models', Interpreting categorical and quantitative data. 
Questions in the The Real Number System topic involve the usage properties of rational and irrational numbers.
Questions in the Quantities topic involve quantitative reasoning and use of units to solve problems.
Questions in Seeing Structure in Expressions involve either interpreting the structure of expressions or writing expressions in equivalent forms to reveal their characteristics.
Questions in Arithmetic with Polynomials and Rational Expressions involve performing arithmetic operations on polynomials or understanding the relationship between zeros and factors of polynomials. 
Questions in Creating Equations involve creating equations that describe numbers or relationships.
Questions in Reasoning with Equations and Inequalities involve understanding solving equations as a process of reasoning and explain the reasoning, solving equations and inequalities in one variable, solving systems of equations in two variables, or representing and solve equations and inequalities graphically
Questions in Interpreting Functions involve understanding the concept of a function and usage of function notation, interpreting functions that arise in applications in terms of the context, or analyzing functions using different representations
Questions in Building Functions involve building a function that models a relationship between two quantities or building new functions from existing functions. 
Questions in Linear, Quadratic, and Expontential Models involve comparing linear, quadratic, and exponential models and solve problems or interpreting expressions for functions in terms of the situation they model.
Questions in Interpreting Categorical and Quantitative Data involve summarizing, representing, and interpreting data on a single count or measurement variable; summarizing, representing, and interpreting data on two categorical and quantitative variables; or interpreting linear models.
If the question text contains the word "function" or "f(x)" at any point, its topic must be either Interpreting Functions or Building Functions.
If a question has a frequency table or box plot or discusses means, medians or other measures of statistics it's Interpreting categorical and quantitative data.
Try and match each question to the topic above with description that most closely matches the question. If the answer choices have equals signs, then it's either creating equations or building functions.

{text}

Respond with only the topic."""
    
    try:
        result = subprocess.run(
            ["ollama", "run", "llama3"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=15
        )
        return result.stdout.strip().split('\n')[0]
    except Exception as e:
        print(f"Ollama classification failed: {e}")
        return "unknown"

def extract_topic_table(PDF_PATH, pgs=[12, 13]):
    with pdfplumber.open(PDF_PATH) as f:
        if (len(f.pages) < 6):
            return {}
        starting_pg = -1
        for idx, pg in enumerate(f.pages):
            txt = pg.extract_text()
            if ("Map to the Common Core Learning" in txt or "Map to the Learning Standards" in txt or "Map to the Core Learning Standards" in txt):
                starting_pg = idx
        page = f.pages[starting_pg]
        raw_table = page.extract_table()
        rows = raw_table[1:]
        page2 = f.pages[starting_pg + 1]
        rows.extend(page2.extract_table())
        df = pd.DataFrame(rows, columns=raw_table[0])
        df['Topic'] = df['Cluster'].map(cluster_map)
        return dict(df[['Question', 'Topic']].values)

def grabKeyAnswers(PDF_PATH):
    scoringKeyDict = {}
    doc = fitz.open(PDF_PATH)
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    entries = full_text.splitlines()
    if "examination" in entries[0].lower():
        current = 1
        while (current < len(entries)):
            if (entries[current] == "MC"):
                scoringKeyDict[entries[current - 2]] = entries[current - 1]
            current += 1
        print(scoringKeyDict)
        return scoringKeyDict
    elif "FOR TEACHERS ONLY" in entries[0].upper():
        pattern = r"\((\d{1,2})\)\s+(?:\.\s+){5}([1-4])"
        matches = re.findall(pattern, full_text)
        answer_key = {}
        for num, ans in matches:
            answer_key[num] = ans
        return answer_key

def extract_question_text(ocr_results) -> str:
    all_lines = []
    for ocr in ocr_results:
        for line in ocr.text_lines:
            if line.text:
                all_lines.append(line.text.strip())
    return "\n".join(all_lines).strip()

def strip_html_tags(text):
    soup = BeautifulSoup(text, "html.parser")
    for sup in soup.find_all("sup"):
        sup.replace_with("^" + sup.get_text())
    return soup.get_text()

# def run_pipeline():
#     model = YOLO(MODEL_PATH)
#     results = model.predict(source=INPUT_IMAGE, conf=0.85, save=False)
#     full_image = Image.open(INPUT_IMAGE)
#     # predictor = TexifyPredictor()

#     question_data = []
#     key = grabKeyAnswers(KEY_PDF_PATH)
#     for i, r in enumerate(results):
#         boxes = r.boxes.xyxy.cpu().numpy()  # x1, y1, x2, y2
#         class_ids = r.boxes.cls.cpu().numpy().astype(int)
#         class_names = r.names
#         for j, (box, class_id) in enumerate(zip(boxes, class_ids)):
#             x1, y1, x2, y2 = map(int, box)
#             cropped = full_image.crop((x1, y1, x2, y2))
#             label = class_names[class_id]
#             LABEL_DIR = os.path.join(OUTPUT_DIR, label)
#             os.makedirs(LABEL_DIR, exist_ok=True)
#             # Save each cropped question image
#             cropped_path = os.path.join(LABEL_DIR, f"question_{i}_{j}.png")
#             cropped.save(cropped_path)

#             # === STEP 3: Run Surya OCR on each cropped image ===
#             recognition_predictor = RecognitionPredictor()
#             detection_predictor = DetectionPredictor()
#             try:
#                 predictions = recognition_predictor([cropped], det_predictor=detection_predictor)
#             except:
#                 cropped.save(os.path.join(LABEL_DIR, f"untranslatedq_{i}_{j}.png"))
#             # tex_result = predictor([cropped])
#             print(predictions)
#             question_text = extract_question_text(predictions)
#             print(question_text)
#             topic = classify_topic(question_text)
#             if len(question_text) == 0 or not question_text.split(' ')[0].isdigit():
#                 continue
#             question_data.append({
#                 "image": cropped_path,
#                 "text": question_text,
#                 "type": label[:3],
#                 "topic": topic,
#                 "answer": key[question_text.split(' ')[0]]
#             })
    

#     print(question_data)
def insert_question_into_db(subject, topic, month, year, qtype, question_image_path, correct_answer=None, explanation=None):
    """Insert a question into the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO questions (
            subject, topic, month, year, type,
            question_image_path, correct_answer,
            explanation, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        subject,
        topic,
        month,
        year,
        qtype,
        question_image_path,
        correct_answer,
        explanation,
        datetime.now()
    ))

    conn.commit()
    conn.close()

def extract_questions_from_pdf(PDF_PATH, KEY_PATH, RG_PATH, month, year):
    alldata = []

    model = YOLO(MODEL_PATH)
    predictor = RecognitionPredictor()
    detector = DetectionPredictor()
    scoring_key = grabKeyAnswers(KEY_PATH)
    topics = extract_topic_table(RG_PATH)
    pdf = fitz.open(PDF_PATH)
    for page_num in range(len(pdf)):
        if page_num == 0:
            continue
        if page_num > 21:
            break
        if "algone82024" in PDF_PATH and page_num < 4:
            continue
        print(f"Processing page {page_num + 1}/{len(pdf)}")
        page = pdf.load_page(page_num)
        pix = page.get_pixmap(dpi=300)
        image_path = os.path.join(OUTPUT_DIR, f"page_{page_num}.png")
        pix.save(image_path)

        full_image = Image.open(image_path)
        results = model.predict(source=image_path, conf=0.6, save=False)
        if not results:
            break
        boxes = results[0].boxes.xyxy.cpu().numpy()
        classes = results[0].boxes.cls.cpu().numpy().astype(int)
        names = results[0].names
        months = {1: "January", 6: "June", 8: "August"}
        for i, (box, cls_id) in enumerate(zip(boxes, classes)):
            label = names[cls_id]  # 'mcqQuestion' or 'saqQuestion'
            if label == "diagram":
                continue
            x1, y1, x2, y2 = map(int, box)
            cropped = full_image.crop((x1, y1, x2, y2))

            img_filename = f"question_{months[month][:3]}_{year}_{page_num}_{i}_{uuid.uuid4().hex[:8]}.png"
            if page_num == 3 and i == 0:
                continue
            LABEL_DIR = os.path.join(OUTPUT_DIR, label)
            os.makedirs(LABEL_DIR, exist_ok=True)
            # Save each cropped question image
            cropped_path = os.path.join(LABEL_DIR, img_filename)
            cropped.save(cropped_path)
            # Run OCR
            try:
                ocr_results = predictor([cropped], det_predictor=detector)
                question_text = strip_html_tags(extract_question_text(ocr_results))
            except:
                question_text = ""

            if len(question_text) == 0 or not question_text.split(' ')[0].isdigit():
                continue
            if (num := question_text.split(' ')[0]) in alldata:
                continue
            alldata.append(num)
            topic = topics[num]
            if label == "mcqQuestionBlock":
                correct_answer = scoring_key[question_text.split(' ')[0]]
            elif label == "saqQuestionBlock":
                correct_answer = "N/A"
            else:
                continue
            # Save to file or database
            # print(f"Extracted: {question_text} (Type: {label}, Topic: {topic}, Answer: {correct_answer})")
            insert_question_into_db(
                subject="Algebra I",
                topic=topic,
                month=months[month],
                year=year,
                qtype="MCQ" if label == "mcqQuestionBlock" else "CRQ",
                question_image_path=cropped_path[11:],
                correct_answer=correct_answer,
                explanation=None
            )
        if (PG_PATH := os.path.join(OUTPUT_DIR, f"page_{page_num}.png")) and os.path.exists(PG_PATH):
            os.remove(PG_PATH)
    #         alldata.append(f"Subject: Algebra I\nTopic: {topic}\nYear: 2025\nType: {label[:3]}\nNumber: {question_text.split(' ')[0]}\nImage Path: {cropped_path}\nCorrect Answer: {correct_answer}\n\n")
    # with open("questiontext.txt", "w", encoding="utf-8") as f:
    #     f.writelines(alldata)


if __name__ == "__main__":
    months = [8]
    years = range(2018, 2020)
    for y in years:
        for m in months:
            m_str = f"{m}"
            y_str = str(y)

            exam_filename = f"algone{m_str}{y_str}-exam.pdf"
            key_filename = f"algone{m_str}{y_str}-sk.pdf"

            exam_path = os.path.join("../pdfs/exams", exam_filename)
            key_path = os.path.join("../pdfs/keys", key_filename)

            if os.path.exists(exam_path) and os.path.exists(key_path):
                print(f"Processing pair: {exam_path}, {key_path}")
                extract_questions_from_pdf(exam_path, key_path, key_path, m, y)
            else:
                print(f"Missing file(s) for {m_str}{y_str}")