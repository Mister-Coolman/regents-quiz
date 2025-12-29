# Flask backend (query interface + SQLite + PDF generation + Ollama LLM parser)
print("✅ Starting app.py — deployed version")

from flask import Flask, request, jsonify, send_file, url_for, send_from_directory, abort
from flask_cors import CORS
import sqlite3
import json
from fpdf import FPDF
import os
import subprocess
import uuid
from werkzeug.middleware.proxy_fix import ProxyFix
import re
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv

app = Flask(__name__, static_folder='static', static_url_path='/static')
FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
load_dotenv()
api_key = os.getenv("FIREWORKS_API_KEY")
if not api_key:
    print("[WARN] FIREWORKS_API_KEY not set; parsing will fail on first request")
FIREWORKS_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
session = requests.Session()
session.headers.update({"Connection": "keep-alive"})

adapter = HTTPAdapter(
    pool_connections=20,
    pool_maxsize=20,
    max_retries=Retry(total=2, backoff_factor=0.2, status_forcelist=(502, 503, 504))
)

session.mount("http://", adapter)
session.mount("https://", adapter)

CORS(app, resources={r"/api/*": {"origins": [
    "http://localhost:5173",
    "https://*.ngrok-free.app",
    "https://perfectly-knowing-cow.ngrok-free.app",
    "https://nystateregentsprep.netlify.app"
]}}, supports_credentials=True)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # /regents-quiz/backend
DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "regentsqs.db"))
IMG_DIR = os.path.join(os.path.dirname(__file__), "static") # /regents-quiz/backend/static/images
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
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        session_id   TEXT PRIMARY KEY,
        started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_active  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );)
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS session_messages (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id   TEXT    NOT NULL,
        sender       TEXT    NOT NULL,
        text         TEXT    NOT NULL,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES sessions(session_id)
            ON DELETE CASCADE
        );
    """)
    cursor.execute("""
    CREATE TABLE session_questions (
        session_id    TEXT    NOT NULL,
        message_idx   INTEGER NOT NULL,
        question_idx  INTEGER NOT NULL,
        question_id   INTEGER NOT NULL,
        question_data TEXT    NOT NULL,
        PRIMARY KEY (session_id, message_idx, question_idx),
        FOREIGN KEY (session_id, message_idx)
            REFERENCES session_messages(session_id, id)
            ON DELETE CASCADE
    );
""")
    conn.commit()
    conn.close()

@app.get("/healthz")
def healthz():
    return {"status": "alive"}, 200

def parse_query_with_ollama(query_text):
    subject_topics = {
        "Algebra I": [
            "The Real Number System",
            "Quantities",
            "Seeing Structure in Expressions",
            "Arithmetic with Polynomials and Rational Expressions",
            "Creating Equations",
            "Reasoning with Equations and Inequalities",
            "Solving One Variable Equations",
            "Systems of Equations",
            "Interpreting Functions",
            "Building Functions",
            "Linear, Quadratic, and Exponential Models",
            "Interpreting categorical and quantitative data"
        ],
        "Algebra II": [
            "Exponents and Radicals",
            "Quantities in Modeling",
            "Complex Numbers",
            "Seeing Structure in Expressions",
            "Factoring Polynomials",
            "Polynomial Identities",
            "Rational Expressions",
            "Creating Equations",
            "Reasoning with Equations and Inequalities",
            "Solving equations and inequalities in one variable",
            "Solving systems of equations",
            "Graphically solving equations and inequalities",
            "Interpreting Functions",
            "Building Functions",
            "Linear, Quadratic, and Exponential Models",
            "Trigonometric Functions",
            "Modeling with Trigonometric Functions",
            "Trigonometric Identities",
            "Interpreting Categorical and Quantitative Data",
            "Making Inferences and Justifying Conclusions",
            "Conditional Probability and the Rules of Probability",
            "Equations of Parabolas with Focus and Directrix"
        ],
        "Geometry": [
            'Transformations in the Plane',
            'Rigid Motions and Triangle Congruence',
            'Proving Geometric Theorems',
            'Constructions',
            'Similarity Transformations',
            'Proving Theorems Using Similarity',
            'Right Triangle Trigonometry',
            'Theorems with Circles',
            'Arc Lengths and Areas of Circles',
            'Equations of Circles',
            'Coordinate Geometry',
            'Volume',
            'Cross Sections',
            'Modeling with Geometry'
        ]
    }
    topic_whitelist_md = []
    for subject, topics in subject_topics.items():
        topic_whitelist_md.append(f"#### {subject} topics")
        for t in topics:
            topic_whitelist_md.append(f"- {t}")
    topic_whitelist_section = "\n".join(topic_whitelist_md)
    print(f"[DEBUG] Parsing query with Ollama: {query_text}")
    prompt = f"""
        You are a precise JSON-only parser for Regents practice questions. Given a student’s raw request, extract exactly these fields and nothing else in a single-line JSON object:

        • intent: one of "generate", "list_topics", or "count_questions"  
        • "generate": return actual practice questions  
        • "list_topics": list all available topics (optionally filtered by subject)  
        • "count_questions": return the count of questions matching the filters  

        • subject: one of "Algebra I", "Algebra II", "Geometry", or "ELA" (empty if unspecified)  
        • topic: string; if intent="generate", must be exactly one of the valid topics for the chosen subject (empty otherwise)  
        • type: one of "MCQ", "CRQ", or "Essay" (treat "SAQ" or "Short Answer" as "CRQ"; empty if unspecified)  
        • limit: integer number of questions (default to 5 for "generate"; must be 0 for "list_topics" or "count_questions")  

        ### Default rules & error-proofing  
        - If the text asks to “list topics” or “what topics”, set intent="list_topics" (subject may still be filled).  
        - If it asks “how many” or “count”, set intent="count_questions" (ignore or zero out limit).  
        - Otherwise default intent="generate".  
        - Non-numeric counts (“some”, “a few”) → limit=5.  
        - Accept spelled-out numbers up to “twenty” (e.g. “ten”→10); else default limit=5.  
        - Always output valid JSON; do not include any extra text, explanations, or markdown.

        ### Subject → Topic Whitelist  
        {topic_whitelist_section}

        ### JSON schema (exactly these keys; no extras)
        {{  
        "intent":  "<generate|list_topics|count_questions>",  
        "subject": "<subject or empty string>",  
        "topic":   "<one valid topic for that subject or empty string>",  
        "type":    "<MCQ|CRQ|Essay or empty string>",  
        "limit":   <integer number of questions or 0>  
        }}

        Student Query: "{query_text}"
            """.strip()
    try:
        response = session.post(
                FIREWORKS_URL,
                headers=FIREWORKS_HEADERS,
                json={
                    "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0,
                    "max_tokens": 120,
                    "response_format": {"type": "json_object"}
                }
            )
        
        response.raise_for_status()


        raw = response.json()["choices"][0]["message"]["content"]
        print(f"[DEBUG] Ollama raw output:\n{raw}")

        parsed = json.loads(raw)

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

    # Answer key page…
    if answer_key:
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, "Answer Key:")
        for i, ans in enumerate(answer_key, start=1):
            pdf.multi_cell(0, 10, f"Page {i}: {ans}")

    path = os.path.join(OUTPUT_PDF_DIR, filename)
    pdf.output(path)
    return path

def help_response():
    help_text ="""
    🤖 <b>How to Use the Chatbot</b><br><br>
    Right now, I support three subjects: Algebra I, Geometry, and Algebra II <br>
    You can ask me to do three things:
    <ul style="margin-top:0.5rem">
      <li><b>List Topics</b> – e.g. “List Algebra I topics”</li>
      <li><b>Count Questions</b> – e.g. “How many MCQs on one variable equations?”</li>
      <li><b>Generate Practice Questions</b> – e.g. “Give me 5 Algebra I MCQs on interpreting functions</li>
    </ul>
    <hr>
    After you generate questions, you’ll see:
    <ul>
      <li>📄 A PDF link to download your questions</li>
      <li>▶️ A “Take Interactive Quiz” button so you can answer them right here!</li>
    </ul>
    <hr>
    <b>📘 Type Definitions:</b>
    <ul>
      <li><b>MCQ</b> = Multiple Choice Question</li>
      <li><b>CRQ</b> = Constructed Response Question</li>
    </ul>
    """
    return jsonify({"response": help_text})

@app.route('/debug/image')
def debug_image():
    rel = request.args.get('path', '')
    # normalize: allow “images/…” or “static/images/…”
    rel = rel.lstrip('/')
    if rel.startswith('static/'):
        rel = rel[len('static/'):]
    if rel.startswith('images/'):
        rel = rel[len('images/'):]

    root = os.path.join(app.static_folder or os.path.join(BASE_DIR, "static"), "images")
    abs_path = os.path.join(root, rel)

    info = {
        "cwd": os.getcwd(),
        "base_dir": BASE_DIR,
        "static_folder": app.static_folder,
        "images_root": root,
        "requested_rel": rel,
        "abs_path": abs_path,
        "images_root_exists": os.path.exists(root),
        "file_exists": os.path.exists(abs_path),
        "env_VITE_API_BASE_URL": os.environ.get("VITE_API_BASE_URL"),
    }

    # include small listing for context
    try:
        info["siblings"] = sorted(os.listdir(os.path.dirname(abs_path)))[:50]
    except Exception as e:
        info["siblings_error"] = str(e)

    return jsonify(info)

@app.route('/api/query', methods=['POST'])
def query():
    print("inside query endpoint")
    data = request.json
    user_query = data.get("query", "").strip()
    sess_id = data.get("session_id")

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("""
    INSERT INTO sessions(session_id, last_active)
        VALUES (?, CURRENT_TIMESTAMP)
    ON CONFLICT(session_id) DO
        UPDATE SET last_active = CURRENT_TIMESTAMP
    """, (sess_id,))
    conn.commit()

    print(f"[INFO] Received query: {user_query}")

    # Help trigger
    if not user_query or user_query.lower() in {"help", "how do i ask", "show me examples"}:
        print("[INFO] Help response triggered")
        return help_response()

    intent, subject, topic, qtype, limit = parse_query_with_ollama(user_query)
    print(f"[DEBUG] Parsed query -> Subject: {subject}, Topic: {clean_topic(topic)}, Type: {qtype}, Limit: {limit}")

    # If nothing was parsed, fallback to help
    bot_resp = ""
    if intent == "list_topics":
        if not subject:
            return jsonify({"response": "No topics found for that subject.<br>Try something like 'List topics for Algebra I'"})
        topics = list_topics(subject)
        if topics:
            # Build an HTML bullet list
            title = f"Available topics for <b>{subject}</b>:" if subject else "Available topics:"
            items = "".join(f"<li>{t}</li>" for t in topics)
            bot_resp = f"{title}<ul style='margin-top:0.5rem'>{items}</ul>"
            return jsonify({"response": bot_resp})
        else:
            return jsonify({"response": "No topics found for that subject."})

    
    if intent == "count_questions":
        cnt = count_questions(subject, topic, qtype)
        parts = []
        if subject: parts.append(subject)
        if topic:   parts.append(topic)
        if qtype:   parts.append(qtype)
        label = " ".join(parts) or "all questions"
        bot_resp = f"There are {cnt} {label} in the database."
        return jsonify({"response": bot_resp})
    
    if not any([subject, topic, qtype]):
        print("[WARN] Query parsing returned empty fields")
        return help_response()

    questions = fetch_questions(subject, topic, qtype, limit)
    print(f"[DEBUG] Retrieved {len(questions)} questions from DB")

    if not questions:
        print("[WARN] No questions found for given criteria.")
        return jsonify({"response": "No questions found for your query. Try being more specific, like '5 Algebra I MCQs on exponents'."})
    cur.execute("""
      INSERT INTO session_messages(session_id, sender, text)
      VALUES (?, 'student', ?)
    """, (sess_id, user_query))
    conn.commit()

    unique_filename = f"questions_{uuid.uuid4().hex}.pdf"
    pdf_path = generate_pdf(questions, unique_filename)
    print(f"[INFO] PDF generated at {pdf_path}")
    
    download_url = url_for('download', file=unique_filename, _external=True)
    print(f"[INFO] Download URL: {download_url}")

    summary = f"Here are {len(questions)} {qtype or ''} questions on '{topic or subject}':"
    pdf_link = f"<a href='{download_url}' target='_blank'>📄 Click here to view/download the PDF</a>"
    bot_resp = f"{summary}<br><br>{pdf_link}"

    cur.execute("""
      INSERT INTO session_messages(session_id, sender, text)
      VALUES (?, 'bot', ?)
    """, (sess_id, bot_resp))
    conn.commit()

    bot_msg_id = cur.lastrowid
    print(f"Message_ID: {bot_msg_id}")
    print(questions)
    for i, q in enumerate(questions):
        cur.execute("""
        INSERT INTO session_questions
            (session_id, message_idx, question_idx, question_id, question_data)
        VALUES (?, ?, ?, ?, ?)
        """, (
        sess_id,
        bot_msg_id,
        i,
        q["id"],
        json.dumps(q, ensure_ascii=False)
        ))
        conn.commit()
    conn.close()
    return jsonify({
      "response": summary + "<br><br>" + pdf_link,
      "pdf_url": download_url,
      "questions": questions    # 👈 send back the raw question objects
    })

# @app.route('/images/<path:filename>')
# def serve_image(filename):
#     return send_from_directory(os.path.join(IMG_DIR, "images"), filename)

IMG_DIR = os.path.join(app.static_folder, 'images')

@app.route('/images/<path:filename>')
def serve_images(filename):
    abs_path = os.path.join(IMG_DIR, filename)
    if not os.path.exists(abs_path):
        abort(404)
    return send_from_directory(IMG_DIR, filename)

@app.route('/api/download', methods=['GET'])
def download():
    filename = request.args.get('file', '').strip()
    if not filename:
        return jsonify({"error": "missing ?file=<filename>.pdf"}), 400

    # Security: prevent path traversal
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        return jsonify({"error": "invalid filename"}), 400

    abs_path = os.path.join(OUTPUT_PDF_DIR, safe_name)
    if not os.path.exists(abs_path):
        return jsonify({"error": "file not found"}), 404

    # Let it open inline in the browser; set a download name
    return send_file(
        abs_path,
        as_attachment=False,
        download_name=safe_name,
        mimetype="application/pdf",
        max_age=3600
    )

@app.route('/api/history/<session_id>')
def history(session_id):

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
      SELECT
        sm.id        AS id,
        sm.sender    AS sender,
        sm.text      AS text,
        GROUP_CONCAT(sq.question_data, '||') AS questions_concat
      FROM session_messages sm
      LEFT JOIN session_questions sq
        ON sm.session_id = sq.session_id
       AND sm.id         = sq.message_idx
      WHERE sm.session_id = ?
      GROUP BY sm.id
      ORDER BY sm.created_at
    """, (session_id,))

    rows = []
    for r in cur.fetchall():
        row = dict(r)
        qc = row.pop('questions_concat')
        row['questions'] = qc.split('||') if qc else []
        # parse each JSON string back into dict
        row['questions'] = [json.loads(q) for q in row['questions']]
        rows.append(row)

    conn.close()
    return jsonify(rows)
@app.route('/api/end_session', methods=['POST'])
def end_session():
    sess_id = request.json.get("session_id")
    if not sess_id:
        return jsonify({"error": "session_id required"}), 400

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()
    cur.execute("DELETE FROM session_messages WHERE session_id = ?", (sess_id,))
    cur.execute("DELETE FROM sessions         WHERE session_id = ?", (sess_id,))
    cur.execute("DELETE FROM session_questions WHERE session_id = ?", (sess_id,))  
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_vue(path):
    if path != "" and os.path.exists(os.path.join("dist", path)):
        return send_from_directory("dist", path)
    else:
        return send_from_directory("dist", "index.html")

if __name__ == '__main__':
    print("[INFO] Initializing database...")
    init_db()
    print("[INFO] Starting Flask server on http://localhost:8080")
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
