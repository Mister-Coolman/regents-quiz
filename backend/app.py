# Flask backend (query interface + SQLite + PDF generation + LLM parser)
print("✅ Starting app.py — deployed version")

import os
import uuid

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file, send_from_directory, url_for
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

import db
from llm_client import parse_query_with_ollama, clean_topic
from pdf_utils import generate_pdf, OUTPUT_PDF_DIR

app = Flask(__name__, static_folder='static', static_url_path='/static')

CORS(app, resources={r"/api/*": {"origins": [
    "http://localhost:5173",
    "https://*.ngrok-free.app",
    "https://perfectly-knowing-cow.ngrok-free.app",
    "https://nystateregentsprep.netlify.app"
]}}, supports_credentials=True)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

IMG_DIR = os.path.join(app.static_folder, 'images')


@app.get("/healthz")
def healthz():
    return {"status": "alive"}, 200


def help_response():
    help_text = """
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


@app.route('/api/query', methods=['POST'])
def query():
    data = request.json
    user_query = data.get("query", "").strip()
    sess_id = data.get("session_id")

    db.touch_session(sess_id)

    print(f"[INFO] Received query: {user_query}")

    if not user_query or user_query.lower() in {"help", "how do i ask", "show me examples"}:
        print("[INFO] Help response triggered")
        return help_response()

    intent, subject, topic, qtype, limit = parse_query_with_ollama(user_query)
    print(f"[DEBUG] Parsed query -> Subject: {subject}, Topic: {clean_topic(topic)}, Type: {qtype}, Limit: {limit}")

    if intent == "list_topics":
        if not subject:
            return jsonify({"response": "No topics found for that subject.<br>Try something like 'List topics for Algebra I'"})
        topics = db.list_topics(subject)
        if topics:
            title = f"Available topics for <b>{subject}</b>:" if subject else "Available topics:"
            items = "".join(f"<li>{t}</li>" for t in topics)
            bot_resp = f"{title}<ul style='margin-top:0.5rem'>{items}</ul>"
            return jsonify({"response": bot_resp})
        else:
            return jsonify({"response": "No topics found for that subject."})

    if intent == "count_questions":
        cnt = db.count_questions(subject, topic, qtype)
        parts = [p for p in (subject, topic, qtype) if p]
        label = " ".join(parts) or "all questions"
        bot_resp = f"There are {cnt} {label} in the database."
        return jsonify({"response": bot_resp})

    if not any([subject, topic, qtype]):
        print("[WARN] Query parsing returned empty fields")
        return help_response()

    questions = db.fetch_questions(subject, topic, qtype, limit)
    print(f"[DEBUG] Retrieved {len(questions)} questions from DB")

    if not questions:
        print("[WARN] No questions found for given criteria.")
        return jsonify({"response": "No questions found for your query. Try being more specific, like '5 Algebra I MCQs on exponents'."})

    unique_filename = f"questions_{uuid.uuid4().hex}.pdf"
    pdf_path = generate_pdf(questions, unique_filename)
    print(f"[INFO] PDF generated at {pdf_path}")

    download_url = url_for('download', file=unique_filename, _external=True)
    print(f"[INFO] Download URL: {download_url}")

    label = topic or subject
    type_part = f"{qtype} " if qtype else ""
    topic_part = f" on '{label}'" if label else ""
    summary = f"Here are {len(questions)} {type_part}questions{topic_part}:"
    pdf_link = f"<a href='{download_url}' target='_blank'>📄 Click here to view/download the PDF</a>"
    bot_resp = f"{summary}<br><br>{pdf_link}"

    db.save_exchange(sess_id, user_query, bot_resp, questions)

    return jsonify({
        "response": bot_resp,
        "pdf_url": download_url,
        "questions": questions
    })


@app.route('/debug/image')
def debug_image():
    rel = request.args.get('path', '')
    rel = rel.lstrip('/')
    if rel.startswith('static/'):
        rel = rel[len('static/'):]
    if rel.startswith('images/'):
        rel = rel[len('images/'):]

    root = os.path.join(app.static_folder or os.path.join(os.path.dirname(__file__), "static"), "images")
    abs_path = os.path.join(root, rel)

    info = {
        "cwd": os.getcwd(),
        "static_folder": app.static_folder,
        "images_root": root,
        "requested_rel": rel,
        "abs_path": abs_path,
        "images_root_exists": os.path.exists(root),
        "file_exists": os.path.exists(abs_path),
        "env_VITE_API_BASE_URL": os.environ.get("VITE_API_BASE_URL"),
    }

    try:
        info["siblings"] = sorted(os.listdir(os.path.dirname(abs_path)))[:50]
    except Exception as e:
        info["siblings_error"] = str(e)

    return jsonify(info)


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

    return send_file(
        abs_path,
        as_attachment=False,
        download_name=safe_name,
        mimetype="application/pdf",
        max_age=3600
    )


@app.route('/api/history/<session_id>')
def history(session_id):
    return jsonify(db.get_history(session_id))


@app.route('/api/end_session', methods=['POST'])
def end_session_route():
    sess_id = request.json.get("session_id")
    if not sess_id:
        return jsonify({"error": "session_id required"}), 400
    db.end_session(sess_id)
    return jsonify({"status": "ok"})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    if path != "" and os.path.exists(os.path.join("dist", path)):
        return send_from_directory("dist", path)
    else:
        return send_from_directory("dist", "index.html")


if __name__ == '__main__':
    print("[INFO] Initializing database...")
    db.init_db()
    print("[INFO] Starting Flask server on http://localhost:8080")
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
