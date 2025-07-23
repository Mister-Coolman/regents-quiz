# Flask backend (query interface + SQLite + PDF generation + Ollama LLM parser)

from flask import Flask, request, jsonify, send_file, url_for, send_from_directory
from flask_cors import CORS
import sqlite3
import json
from fpdf import FPDF
import os
import subprocess
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:5173"}}, supports_credentials=True)
CORS(app, origins=["http://localhost:5173", "https://*.ngrok-free.app"])
CORS(app, origins=["https://aac950645d56.ngrok-free.app"])
CORS(app, resources={r"/*": {"origins": "https://aac950645d56.ngrok-free.app"}})
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
DB_PATH = "/Users/arjunrangarajan/regents-quiz/regents-quiz/backend/regentsqs.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # /regents-quiz/backend
IMG_DIR = os.path.abspath(os.path.join(BASE_DIR, "images")) # /regents-quiz/backend/images
PDF_DIR = os.path.abspath(os.path.join(BASE_DIR, "pdfs"))  # /regents-quiz/backend/pdfs
OUTPUT_PDF_DIR = os.path.abspath(os.path.join(BASE_DIR, "output_pdf")) # /regents-quiz/backend/output_pdf
os.makedirs(PDF_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT NOT NULL,
        topic TEXT NOT NULL,
        month TEXT NOT NULL,
        year INTEGER NOT NULL,
        type TEXT NOT NULL,
        question_image_path TEXT NOT NULL,
        correct_answer TEXT,
        explanation TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()

def parse_query_with_ollama(query_text):
    print(f"[DEBUG] Parsing query with Ollama: {query_text}")
    prompt = f"""
    You are a parsing assistant for a Regents question generator. Given a student's request, extract the following information and return a single-line JSON object with these fields:

    - "subject" (e.g., "Algebra I", "Geometry", "ELA")
    - "topic" (e.g., "linear equations", "exponents", etc.)
    - "type" (must be one of: "MCQ", "CRQ", or "Essay")
    - "limit" (integer number of questions to return)

    ### 🧠 Definitions:
    - MCQ = Multiple Choice Question
    - CRQ = Constructed Response Question
    - SAQ = Short Answer Question (Treat this as CRQ)

    ### 📌 Parsing Rules:
    - If they say **SAQ**, return "CRQ" for "type"
    - If they just say **questions** without a type, leave "type" as an empty string
    - If **type** is not mentioned or not clearly one of ["MCQ", "CRQ", "Essay"], leave it empty
    - If **topic** is not mentioned or unclear, leave it empty
    - If **number of questions** is missing or vague (e.g., “some”, “a few”), set "limit" to 5
    - Accept spelled-out numbers (e.g., "ten" → 10)

    ### ℹ️ For Algebra I, only allow topics from this list:
    - The Real Number System
    - Quantities
    - Seeing Structure in Expressions
    - Arithmetic with Polynomials and Rational Expressions
    - Creating Equations
    - Reasoning with Equations and Inequalities
    - Interpreting Functions
    - Building Functions
    - Linear, Quadratic, and Exponential Models
    - Interpreting categorical and quantitative data

    If the topic for Algebra I does not match one of these, leave it empty.
    If no topic is given, like "5 Algebra I mcqs" or "5 Algebra I questions" then do not have anythign for topic.

    ### 🔄 Input:
    Student Query: "{query_text}"

    ### ✅ Output Format:
    Respond with a single-line **valid JSON** object like this:
    {{"subject": "Algebra I", "topic": "Interpreting Functions", "type": "MCQ", "limit": 5}}

    ⚠️ Do not include any explanations, markdown, or extra text. Only output the raw JSON.
    """



    try:
        result = subprocess.run(
            ["ollama", "run", "llama3"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=15
        )
        response = result.stdout.strip()
        json_start = response.find('{')
        json_str = response[json_start:]
        parsed = json.loads(json_str)
        return (
            parsed.get("subject", ""),
            parsed.get("topic", ""),
            parsed.get("type", ""),
            int(parsed.get("limit", 5))
        )
    except Exception as e:
        print(f"Ollama parsing failed: {e}")
        return ("", "", "", 5)

def fetch_questions(subject, topic, qtype, limit):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    query = "SELECT * FROM questions WHERE 1=1"
    params = []
    if subject:
        query += " AND subject = ?"
        params.append(subject)
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    if qtype:
        query += " AND type = ?"
        params.append(qtype)
    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def generate_pdf(questions, filename):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    answer_key = []
    IMG_DIR = "/Users/arjunrangarajan/regents-quiz/regents-quiz/backend"
    for idx, q in enumerate(questions, start=1):
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        # Build header and force it into Latin‑1
        subject = q.get("subject", "")
        month   = q.get("month", "")
        year    = q.get("year", "")
        header  = f"{subject} - {month} {year}"   # use hyphen instead of em‑dash
        # Strip out any non‑Latin1 characters silently:
        header_safe = header.encode('latin1', errors='ignore').decode('latin1')
        pdf.cell(0, 8, header_safe, ln=True)

        # Insert image…
        image_path = os.path.join(IMG_DIR, q["question_image_path"])
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

    # Answer key page…
    if answer_key:
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, "Answer Key:")
        for i, ans in enumerate(answer_key, start=1):
            pdf.multi_cell(0, 10, f"Page {i}: {ans}")

    path = os.path.join(PDF_DIR, filename)
    pdf.output(path)
    return path

def help_response():
    help_text = """
    🤖 <b>How to Ask a Good Regents Question</b><br><br>

    You can request specific types of questions by including:<br>
    • <b>Subject</b> (e.g., Algebra I, Geometry, ELA)<br>
    • <b>Topic</b> (e.g., linear equations, exponents)<br>
    • <b>Type</b> (MCQ = Multiple Choice, CRQ = Constructed Response, Essay)<br>
    • <b>Number of Questions</b> (e.g., 5, 10)<br><br>

    <b>✅ Examples:</b><br>
    - "Give me 5 Algebra I multiple choice questions on linear equations"<br>
    - "I want 3 Geometry CRQs about volume"<br>
    - "ELA essay questions about character development"<br><br>

    If you're not sure what to ask, just say "help" or "show me examples." <br><br>

    <hr>
    <b>📘 Type Definitions:</b><br>
    • <b>MCQ</b> = Multiple Choice Question<br>
    • <b>CRQ</b> = Constructed Response Question<br>
    • <b>SAQ</b> = Short Answer Question (interpreted as CRQ)<br><br>

    <hr>
    <b>ℹ️ For Algebra I, valid topics include:</b><br>
    <ul>
      <li>The Real Number System</li>
      <li>Quantities</li>
      <li>Seeing Structure in Expressions</li>
      <li>Arithmetic with Polynomials and Rational Expressions</li>
      <li>Creating Equations</li>
      <li>Reasoning with Equations and Inequalities</li>
      <li>Interpreting Functions</li>
      <li>Building Functions</li>
      <li>Linear, Quadratic, and Exponential Models</li>
      <li>Interpreting categorical and quantitative data</li>
    </ul>
    """
    return jsonify({"response": help_text})

@app.route('/query', methods=['POST'])
def query():
    print("inside query endpoint")
    
    data = request.json
    user_query = data.get("query", "").strip()
    print(f"[INFO] Received query: {user_query}")

    # Help trigger
    if not user_query or user_query.lower() in {"help", "?", "how do i ask", "show me examples"}:
        print("[INFO] Help response triggered")
        return help_response()

    subject, topic, qtype, limit = parse_query_with_ollama(user_query)
    print(f"[DEBUG] Parsed query -> Subject: {subject}, Topic: {topic}, Type: {qtype}, Limit: {limit}")

    # If nothing was parsed, fallback to help
    if not any([subject, topic, qtype]):
        print("[WARN] Query parsing returned empty fields")
        return help_response()

    questions = fetch_questions(subject, topic, qtype, limit)
    print(f"[DEBUG] Retrieved {len(questions)} questions from DB")

    if not questions:
        print("[WARN] No questions found for given criteria.")
        return jsonify({"response": "No questions found for your query. Try being more specific, like '5 Algebra I MCQs on exponents'."})

    pdf_path = generate_pdf(questions, "questions_output.pdf")
    print(f"[INFO] PDF generated at {pdf_path}")
    
    download_url = url_for('download', _external=True)
    print(f"[INFO] Download URL: {download_url}")

    summary = f"Here are {len(questions)} {qtype or ''} questions on '{topic or subject}':"
    pdf_link = f"<a href='{download_url}' target='_blank'>📄 Click here to view/download the PDF</a>"
    
    return jsonify({
      "response": summary + "<br><br>" + pdf_link,
      "questions": questions    # 👈 send back the raw question objects
    })

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)


@app.route('/download', methods=['GET'])
def download():
    return send_file(os.path.join(PDF_DIR, "questions_output.pdf"), as_attachment=False)

if __name__ == '__main__':
    print("[INFO] Initializing database...")
    init_db()
    print("[INFO] Starting Flask server on http://localhost:5050")
    app.run(debug=True,port=5050)
