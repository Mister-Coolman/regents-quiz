# Flask backend (query interface + SQLite + PDF generation + LLM parser)
print("✅ Starting app.py — deployed version")

import io
import os
import re
from html import escape

from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file, send_from_directory, url_for
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

import db
from answers import check_answer, public_question
from llm_client import parse_query_with_ollama, clean_topic
from pdf_utils import generate_pdf, pdf_filename

app = Flask(__name__, static_folder='static', static_url_path='/static')

# No cookies or auth headers are used, so credentials stay off.
CORS(app, resources={r"/api/*": {"origins": [
    "https://nystateregentsprep.netlify.app",
    "http://localhost:5173",
    "http://localhost:5174",
]}})

# Trust exactly one proxy hop (Fly's edge) for the client IP and scheme. The
# Host header is deliberately NOT taken from X-Forwarded-Host: it is built into
# the PDF link, and a forwarded value would let a request choose that link.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Every /api/query costs a Fireworks call, so an open endpoint is an open tab on
# the bill. Per-IP limits in memory: fine for the single gunicorn worker here.
limiter = Limiter(
    get_remote_address,
    app=app,
    storage_uri="memory://",
    headers_enabled=True,
)

# A single request can ask for at most this many questions, however the
# model parses it ("give me 2000 questions" otherwise dumps a subject's bank).
MAX_QUIZ_QUESTIONS = 20
MAX_QUERY_CHARS = 500
# Session ids are client-generated UUIDs; anything else is rejected before it
# can reach the database or grow a table.
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def valid_session_id(sid):
    return isinstance(sid, str) and bool(SESSION_ID_RE.match(sid))


@app.after_request
def security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return resp


@app.errorhandler(429)
def too_many_requests(e):
    return jsonify({"error": "Too many requests in a short time. Wait a minute, then try again."}), 429

IMG_DIR = os.path.join(app.static_folder, 'images')

# Guards the download endpoint against absurdly long id lists.
MAX_PDF_QUESTIONS = 50

db.init_db()


@app.get("/healthz")
@limiter.exempt
def healthz():
    return {"status": "alive"}, 200


def help_response():
    help_text = """
    <b>What you can ask</b><br>
    I have past questions for Algebra I, Geometry and Algebra II. Ask me to:
    <ul>
      <li><b>List topics</b>, like “List Algebra I topics”</li>
      <li><b>Count questions</b>, like “How many MCQs on one-variable equations?”</li>
      <li><b>Make a practice set</b>, like “Give me 5 Algebra I MCQs on interpreting functions”</li>
    </ul>
    <hr>
    Each practice set comes with a PDF to download and a quiz you can take right here.
    MCQ means multiple choice; CRQ means constructed response, where you write the answer.
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
                    f"but there are <b>{other}</b> of other types. Try asking without the "
                    f"{escape(qtype)} filter.")

    if topic:
        broader = db.count_questions(subject, "", qtype)
        if broader:
            where = escape(subject) if subject else "that subject"
            return (f"Nothing stored for {escape(topic)} yet. There are <b>{broader}</b> questions "
                    f"in {where} overall. Ask me to list topics to pick a different one.")

    return (f"I couldn't find questions for {escape(asked)}. Try naming a subject and topic, "
            f"like '5 Algebra I MCQs on exponents', or ask me to list topics.")


@app.route('/api/query', methods=['POST'])
@limiter.limit("10 per minute;150 per day")
def query():
    data = request.get_json(silent=True) or {}
    user_query = str(data.get("query", "")).strip()
    sess_id = data.get("session_id")

    if not valid_session_id(sess_id):
        return jsonify({"error": "Missing or invalid session. Reload the page to start a new one."}), 400
    if len(user_query) > MAX_QUERY_CHARS:
        return jsonify({"error": f"That request is too long. Keep it under {MAX_QUERY_CHARS} characters."}), 400

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
            return jsonify({"response": "I can list topics for Algebra I, Algebra II or Geometry. Which one?"})
        topics = db.list_topics(subject)
        if topics:
            title = lead or f"Available topics for <b>{escape(subject)}</b>:<br>"
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

    limit = max(1, min(limit, MAX_QUIZ_QUESTIONS))
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
    pdf_link = (f"<a href='{escape(download_url, quote=True)}' target='_blank' rel='noopener'>"
                f"Open as PDF<span class='sr-only'> (opens in a new tab)</span></a>")

    opener = safe_reply(reply, len(questions))
    if opener:
        # The opener carries the voice, so the facts collapse to a compact line
        # rather than repeating the same sentence back at the student.
        facts = f"{len(questions)} {type_part}question{'s' if len(questions) != 1 else ''}{topic_part}"
        bot_resp = f"{escape(opener)}<br><br>{facts}.<br>{pdf_link}"
    else:
        summary = f"Here are {len(questions)} {type_part}questions{topic_part}:"
        bot_resp = f"{summary}<br><br>{pdf_link}"

    db.save_exchange(sess_id, user_query, bot_resp, questions)

    return jsonify({
        "response": bot_resp,
        "pdf_url": download_url,
        # Answers stay on the server until /api/check.
        "questions": [public_question(q) for q in questions]
    })


@app.route('/api/check', methods=['POST'])
@limiter.limit("60 per minute")
def check():
    """Grade one attempt and release that question's answer and explanation."""
    data = request.get_json(silent=True) or {}
    sess_id = data.get("session_id")
    answer = data.get("answer")
    try:
        question_id = int(data.get("question_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "question_id must be an integer"}), 400

    if not valid_session_id(sess_id):
        return jsonify({"error": "Missing or invalid session. Reload the page to start a new one."}), 400
    if answer is None or not str(answer).strip() or len(str(answer)) > 200:
        return jsonify({"error": "Choose or type an answer first."}), 400

    q = db.fetch_served_question(sess_id, question_id)
    if not q:
        return jsonify({"error": "That question isn't part of this chat. Ask for a new set."}), 404
    return jsonify(check_answer(q, answer))


@app.route('/images/<path:filename>')
def serve_images(filename):
    abs_path = os.path.join(IMG_DIR, filename)
    if not os.path.exists(abs_path):
        abort(404)
    return send_from_directory(IMG_DIR, filename)


@app.route('/api/download', methods=['GET'])
@limiter.limit("30 per minute")
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
        download_name=pdf_filename(questions),
        mimetype="application/pdf",
        max_age=3600,
    )


@app.route('/api/history/<session_id>')
@limiter.limit("60 per minute")
def history(session_id):
    if not valid_session_id(session_id):
        return jsonify([])
    rows = db.get_history(session_id)
    for row in rows:
        row["questions"] = [public_question(q) for q in row["questions"]]
    return jsonify(rows)


@app.route('/api/end_session', methods=['POST'])
@limiter.limit("30 per minute")
def end_session_route():
    sess_id = (request.get_json(silent=True) or {}).get("session_id")
    if not valid_session_id(sess_id):
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
