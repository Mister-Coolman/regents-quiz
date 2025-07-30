# Flask backend (query interface + SQLite + PDF generation + Ollama LLM parser)

from flask import Flask, request, jsonify, send_file, url_for, send_from_directory
from flask_cors import CORS
import sqlite3
import json
from fpdf import FPDF
import os
import subprocess
from werkzeug.middleware.proxy_fix import ProxyFix
import re

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "http://localhost:5173"}}, supports_credentials=True)
CORS(app, origins=["http://localhost:5173", "https://*.ngrok-free.app"])
CORS(app, origins=["https://perfectly-knowing-cow.ngrok-free.app"])
CORS(app, resources={r"/*": {"origins": "https://perfectly-knowing-cow.ngrok-free.app"}})
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
        You are a precise JSON‑only parser for Regents practice questions. Given a student’s raw request, extract exactly these fields and nothing else in a single‑line JSON object:

        • intent: one of "generate", "list_topics", or "count_questions"  
            - "generate": return actual practice questions  
            - "list_topics": list all available topics (optionally filtered by subject)  
            - "count_questions": return the count of questions matching the filters  

        • subject: string, e.g. "Algebra I", "Geometry", or "ELA" (empty if unspecified)  
        • topic: string, exactly one of the valid topics (empty if no match)  
        • type: one of "MCQ", "CRQ", or "Essay" (treat "SAQ" or "Short Answer" as "CRQ"; empty if unspecified)  
        • limit: integer number of questions (default to 5 for "generate"; must be 0 for other intents)  

        ### Default rules & error‐proofing
        - If the user’s text clearly asks to “list topics” or “what topics”, set intent="list_topics"; subject may still be filled.  
        - If the user’s text asks “how many” or “count”, set intent="count_questions"; ignore limit.  
        - Otherwise default intent="generate".  
        - If the user specifies a non‑numeric count (“some”, “a few”), default limit to 5.  
        - Accept spelled‑out numbers up to “twenty” (e.g. “ten” → 10); otherwise default limit=5.  
        - Always output valid JSON; do not include any extra text, explanations, or markdown.

        ### Algebra I topic white‑list (choose exactly one if intent is "generate")
        1. The Real Number System  
        2. Quantities  
        3. Seeing Structure in Expressions  
        4. Arithmetic with Polynomials and Rational Expressions  
        5. Creating Equations  
        6. Reasoning with Equations and Inequalities  
        7. Solving One Variable Equations  
        8. Systems of Equations  
        9. Interpreting Functions  
        10. Building Functions  
        11. Linear, Quadratic, and Exponential Models  
        12. Interpreting categorical and quantitative data

        ### JSON schema (exactly these keys; no extras)
        {{  
        "intent":    "<generate|list_topics|count_questions>",  
        "subject":   "<subject or empty string>",  
        "topic":     "<one of the above topics or empty string>",  
        "type":      "<MCQ|CRQ|Essay or empty string>",  
        "limit":     <integer: number of questions or 0>  
        }}

        Student Query: "{query_text}"
    """

    try:
        result = subprocess.run(
            ["ollama", "run", "llama3"],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=15
        )
        raw = result.stdout.strip()
        print(f"[DEBUG] Ollama raw output:\n{raw}")

        # 1) Find the first "{" and the last "}"
        start = raw.find('{')
        end   = raw.rfind('}')
        if start == -1 or end == -1 or end < start:
            raise ValueError("Could not locate JSON object in Ollama output")

        json_str = raw[start:end+1]
        parsed   = json.loads(json_str)

        return (
            parsed.get("intent",       "generate"),
            parsed.get("subject",      ""),
            clean_topic(parsed.get("topic",        "")),
            parsed.get("type",         ""),
            int(parsed.get("limit",     5))
        )

    except Exception as e:
        print(f"Ollama parsing failed: {e}")
        # Always return exactly five elements:
        return ("generate", "", "", "", 5)

def clean_topic(raw_topic: str) -> str:
    """
    Remove any leading number + punctuation (e.g. "8. ", "3) ", "12: ")
    and trim whitespace.
    """
    # regex:  ^     start of string
    #         \d+   one or more digits
    #         [\.\)\:]  a dot, parenthesis or colon
    #         \s*   any number of spaces
    return re.sub(r'^\d+[\.\)\:]\s*', '', raw_topic).strip()

def fetch_questions(subject, topic, qtype, limit):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    print(f"Topic: {topic}")
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

def list_topics(subject):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    if subject:
        cur.execute("SELECT DISTINCT topic FROM questions WHERE subject = ?", (subject,))
    else:
        cur.execute("SELECT DISTINCT topic FROM questions")
    topics = [row[0] for row in cur.fetchall() if row[0]]
    conn.close()
    return topics

def count_questions(subject, topic, qtype):
    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    query = "SELECT COUNT(*) FROM questions WHERE 1=1"
    params = []
    if subject:
        query += " AND subject = ?"; params.append(subject)
    if topic:
        query += " AND topic = ?"; params.append(topic)
    if qtype:
        query += " AND type = ?";  params.append(qtype)
    cur.execute(query, params)
    (count,) = cur.fetchone()
    conn.close()
    return count

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
    help_text ="""
    🤖 <b>How to Use the Regents Chatbot</b><br><br>
    You can ask me to do three things:
    <ul style="margin-top:0.5rem">
      <li><b>List Topics</b> – e.g. “What topics are there?” or “List Algebra I topics”</li>
      <li><b>Count Questions</b> – e.g. “How many MCQs on systems of equations?” or “Count Algebra I CRQs on real numbers</li>
      <li><b>Generate Practice Questions</b> – e.g. “Give me 5 Algebra I MCQs on interpreting functions</li>
    </ul>
    <br>
    After you generate questions, you’ll see:
    <ul>
      <li>📄 A PDF link to download your questions</li>
      <li>▶️ A “Take Interactive Quiz” button so you can answer them right here!</li>
    </ul>
    <br>

    <b>✅ More Examples:</b><br>
    – “List topics for Algebra I”<br>
    – “Count CRQs on systems of equations in Algebra I”<br><br>

    <hr>
    <b>📘 Type Definitions:</b>
    <ul>
      <li><b>MCQ</b> = Multiple Choice Question</li>
      <li><b>CRQ</b> = Constructed Response Question</li>
      <li><b>Essay</b> = Long‑form written response</li>
    </ul>
    <hr>
    <b>ℹ️ Valid Algebra I topics:</b>
    <ul>
      <li>The Real Number System</li>
      <li>Quantities</li>
      <li>Seeing Structure in Expressions</li>
      <li>Arithmetic with Polynomials and Rational Expressions</li>
      <li>Creating Equations</li>
      <li>Reasoning with Equations and Inequalities</li>
      <li>Solving One Variable Equations</li>
      <li>Systems of Equations</li>
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
    if not user_query or user_query.lower() in {"help", "how do i ask", "show me examples"}:
        print("[INFO] Help response triggered")
        return help_response()

    intent, subject, topic, qtype, limit = parse_query_with_ollama(user_query)
    print(f"[DEBUG] Parsed query -> Subject: {subject}, Topic: {clean_topic(topic)}, Type: {qtype}, Limit: {limit}")

    # If nothing was parsed, fallback to help

    if intent == "list_topics":
        if not subject:
            return jsonify({"response": "No topics found for that subject.<br>Try something like 'List topics for Algebra I'"})
        topics = list_topics(subject)
        if topics:
            # Build an HTML bullet list
            title = f"Available topics for <b>{subject}</b>:" if subject else "Available topics:"
            items = "".join(f"<li>{t}</li>" for t in topics)
            html = f"{title}<ul style='margin-top:0.5rem'>{items}</ul>"
            return jsonify({"response": html})
        else:
            return jsonify({"response": "No topics found for that subject."})

    
    if intent == "count_questions":
        cnt = count_questions(subject, topic, qtype)
        parts = []
        if subject: parts.append(subject)
        if topic:   parts.append(topic)
        if qtype:   parts.append(qtype)
        label = " ".join(parts) or "all questions"
        resp = f"There are {cnt} {label} in the database."
        return jsonify({"response": resp})
    
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
