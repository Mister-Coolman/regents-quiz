# Flask backend (query interface + SQLite + PDF generation + LLM parser)
print("✅ Starting app.py — deployed version")

import io
import os
import re
from html import escape

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file, send_from_directory, url_for
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

import db
from llm_client import parse_query_with_ollama, clean_topic
from pdf_utils import generate_pdf

app = Flask(__name__, static_folder='static', static_url_path='/static')

CORS(app, resources={r"/api/*": {"origins": [
    "http://localhost:5173",
    "https://*.ngrok-free.app",
    "https://perfectly-knowing-cow.ngrok-free.app",
    "https://nystateregentsprep.netlify.app"
]}}, supports_credentials=True)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

IMG_DIR = os.path.join(app.static_folder, 'images')

# Guards the download endpoint against absurdly long id lists.
MAX_PDF_QUESTIONS = 50

db.init_db()


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


# A count the model wrote next to a question word, e.g. "here are 5 questions".
CLAIMED_COUNT_RE = re.compile(
    r"\b(\d{1,3})\s+(?:\w+[- ]){0,3}(?:question|questions|problem|problems|mcqs?|crqs?)\b",
    re.IGNORECASE,
)


def safe_reply(reply, actual_count):
    """Drop the model's reply if it claims a question count that contradicts
    what was actually retrieved.

    The prompt tells it never to state a count -- it doesn't know one at parse
    time -- but it does so intermittently, usually echoing the number the
    student asked for. That's wrong whenever the database holds fewer.
    """
    if not reply:
        return ""
    for match in CLAIMED_COUNT_RE.finditer(reply):
        if int(match.group(1)) != actual_count:
            print(f"[WARN] reply claimed {match.group(1)} questions but {actual_count} were found; dropping reply")
            return ""
    return reply


def no_results_message(subject, topic, qtype):
    """Explain an empty result by saying what IS available, rather than just
    telling the student to be more specific."""
    asked = " ".join(p for p in (subject, topic, qtype) if p) or "that"

    # Relaxing the question type is the most common near-miss: plenty of topics
    # have MCQs but no constructed-response questions, or vice versa.
    if qtype:
        other = db.count_questions(subject, topic, "")
        if other:
            return (f"I don't have any {escape(qtype)} questions for {escape(topic or subject)}, "
                    f"but there are <b>{other}</b> of other types — try asking without the "
                    f"{escape(qtype)} filter.")

    if topic:
        broader = db.count_questions(subject, "", qtype)
        if broader:
            where = escape(subject) if subject else "that subject"
            return (f"Nothing stored for {escape(topic)} yet. There are <b>{broader}</b> questions "
                    f"in {where} overall — want a different topic? Ask me to list topics.")

    return (f"I couldn't find questions for {escape(asked)}. Try naming a subject and topic, "
            f"like '5 Algebra I MCQs on exponents', or ask me to list topics.")


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

    last_query = db.get_last_query(sess_id)
    intent, subject, topic, qtype, limit, reply = parse_query_with_ollama(user_query, last_query)
    print(f"[DEBUG] Parsed query -> Subject: {subject}, Topic: {clean_topic(topic)}, Type: {qtype}, Limit: {limit}")

    if intent in ("generate", "count_questions") and any([subject, topic, qtype, limit]):
        db.set_last_query(sess_id, subject, topic, qtype, limit)

    # The model writes the conversational voice; every fact below is templated
    # from real query results, so a reply can never assert a wrong count.
    lead = f"{escape(reply)}<br><br>" if reply else ""

    if intent == "chitchat":
        return jsonify({"response": escape(reply) if reply else help_response().get_json()["response"]})

    if intent == "list_topics":
        if not subject:
            return jsonify({"response": "I can list topics for Algebra I, Algebra II, or Geometry — which one?"})
        topics = db.list_topics(subject)
        if topics:
            title = lead or f"Available topics for <b>{subject}</b>:<br>"
            items = "".join(f"<li>{escape(t)}</li>" for t in topics)
            return jsonify({"response": f"{title}<ul style='margin-top:0.5rem'>{items}</ul>"})
        return jsonify({"response": f"I don't have any topics stored for {escape(subject)} yet."})

    if intent == "count_questions":
        cnt = db.count_questions(subject, topic, qtype)
        parts = [p for p in (subject, topic, qtype) if p]
        label = " ".join(parts) or "questions"
        return jsonify({"response": f"{lead}There are <b>{cnt}</b> {escape(label)} in the database."})

    if not any([subject, topic, qtype]):
        print("[WARN] Query parsing returned empty fields")
        return help_response()

    questions = db.fetch_questions(subject, topic, qtype, limit, sess_id)
    print(f"[DEBUG] Retrieved {len(questions)} questions from DB")

    if not questions:
        print("[WARN] No questions found for given criteria.")
        return jsonify({"response": no_results_message(subject, topic, qtype)})

    # The link carries the question ids rather than a generated filename, so the
    # PDF is rebuilt on demand at download time. Nothing is stored on disk, and
    # the link keeps working across restarts and redeploys.
    download_url = url_for('download', ids=",".join(str(q["id"]) for q in questions), _external=True)
    print(f"[INFO] Download URL: {download_url}")

    label = topic or subject
    type_part = f"{qtype} " if qtype else ""
    topic_part = f" on '{escape(label)}'" if label else ""
    pdf_link = f"<a href='{download_url}' target='_blank'>📄 Click here to view/download the PDF</a>"

    opener = safe_reply(reply, len(questions))
    if opener:
        # The opener carries the voice, so the facts collapse to a compact line
        # rather than repeating the same sentence back at the student.
        facts = f"{len(questions)} {type_part}question{'s' if len(questions) != 1 else ''}{topic_part}"
        bot_resp = f"{escape(opener)}<br><br>{facts} &middot; {pdf_link}"
    else:
        summary = f"Here are {len(questions)} {type_part}questions{topic_part}:"
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
    """Rebuild the PDF from the question ids in the link.

    Ids are plain integers looked up in the questions table, so there is no
    filesystem path to traverse and no stored file to go missing.
    """
    raw = request.args.get('ids', '').strip()
    if not raw:
        return jsonify({"error": "missing ?ids=<comma-separated question ids>"}), 400

    try:
        ids = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        return jsonify({"error": "ids must be integers"}), 400

    if not ids or len(ids) > MAX_PDF_QUESTIONS:
        return jsonify({"error": f"between 1 and {MAX_PDF_QUESTIONS} ids required"}), 400

    questions = db.fetch_questions_by_ids(ids)
    if not questions:
        return jsonify({"error": "no matching questions"}), 404

    pdf_bytes = generate_pdf(questions)
    return send_file(
        io.BytesIO(pdf_bytes),
        as_attachment=False,
        download_name="regents_questions.pdf",
        mimetype="application/pdf",
        max_age=3600,
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
    print("[INFO] Starting Flask server on http://localhost:8080")
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
