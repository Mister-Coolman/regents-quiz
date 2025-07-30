import pdfplumber
import pandas as pd
import sqlite3
from PIL import Image
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
from run_pipeline import extract_question_text, strip_html_tags

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
DB_PATH = "../backend/regentsqs.db"

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
        try:
            return dict(df[['Question', 'Topic']].values)
        except:
            return dict(df[['Question(cid:1)', 'Topic']].values)

def execute():
    months = [1, 6, 8]
    month_names = {1: "January", 6: "June", 8: "August"}
    years = range(2015, 2021)
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    predictor = RecognitionPredictor()
    detector = DetectionPredictor()
    for month in months:
        for year in years:
            if month == 8 and year == 2016:
                continue
            cur.execute("""
                SELECT id, question_image_path
                FROM questions
                WHERE month = ? AND year = ?
            """, (month_names[month], year))
            questions = cur.fetchall()
            if len(questions) == 0:
                continue
            topics = extract_topic_table(f"../pdfs/keys/algone{month}{year}-sk.pdf")
            if len(topics) == 0:
                print(f"{month_names[month]} {year}")
                break
            for qid, img_path in questions:
                img = Image.open(f"../backend/{img_path}")
                print(img_path)
                try:
                    ocr_results = predictor([img], det_predictor=detector)
                    question_text = strip_html_tags(extract_question_text(ocr_results))
                except:
                    question_text = ""
                if not question_text.split(' ')[0].isdigit():
                    continue
                new_topic = topics[question_text.split(' ')[0]]
                print(f"#: {question_text.split(' ')[0]}, Topic: {new_topic}")
                cur.execute("""
                    UPDATE questions
                    SET topic = ?
                    WHERE id = ?
                """, (new_topic, qid))
                conn.commit()
if __name__ == "__main__":
    execute()