import json
import os
import re

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from topics import (
    build_topic_whitelist_markdown,
    is_valid_subject,
    is_valid_topic,
    is_valid_type,
)

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = "accounts/fireworks/models/qwen3p7-plus"

api_key = os.getenv("FIREWORKS_API_KEY")
if not api_key:
    print("[WARN] FIREWORKS_API_KEY not set; parsing will fail on first request")

FIREWORKS_HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
}

session = requests.Session()
session.headers.update({"Connection": "keep-alive"})

adapter = HTTPAdapter(
    pool_connections=20,
    pool_maxsize=20,
    max_retries=Retry(total=2, backoff_factor=0.2, status_forcelist=(502, 503, 504)),
)
session.mount("http://", adapter)
session.mount("https://", adapter)


def clean_topic(raw_topic: str) -> str:
    """Remove any leading number + punctuation (e.g. "8. ", "3) ", "12: ") and trim whitespace."""
    return re.sub(r'^\d+[\.\)\:]\s*', '', raw_topic).strip()


def parse_query_with_ollama(query_text, last_query=None):
    topic_whitelist_section = build_topic_whitelist_markdown()
    print(f"[DEBUG] Parsing query with Fireworks: {query_text} (last_query={last_query})")

    if last_query and any(last_query.values()):
        context_section = f"""
        ### Previous turn's resolved query (for follow-ups only)
        subject={last_query.get('subject') or '(none)'}, topic={last_query.get('topic') or '(none)'}, \
type={last_query.get('type') or '(none)'}, limit={last_query.get('limit') or '(none)'}

        If the student's new message is clearly a follow-up to that previous request (e.g. "make it 10",
        "give me 5 more", "now do CRQs instead", "same topic but harder", "how many of those are there"),
        carry over any fields the new message doesn't explicitly restate or change. If the new message
        clearly starts a new, unrelated request (names a different subject/topic, or doesn't relate to
        the previous one at all), ignore the previous turn entirely and parse it fresh.
        """
    else:
        context_section = ""

    prompt = f"""
        You are a precise JSON-only parser for Regents practice questions. Given a student’s raw request, extract exactly these fields and nothing else in a single-line JSON object:

        • intent: one of "generate", "list_topics", "count_questions", or "chitchat"
        • "generate": return actual practice questions
        • "list_topics": list all available topics (optionally filtered by subject)
        • "count_questions": return the count of questions matching the filters
        • "chitchat": the message isn't a request for questions at all -- a greeting,
          a thank-you, a question about what you can do, or something you can't act on

        • subject: one of "Algebra I", "Algebra II", "Geometry", or "ELA" (empty if unspecified)
        • topic: string; must exactly match one entry in the Subject → Topic Whitelist below (empty if it doesn't match anything)
        • type: one of "MCQ", "CRQ", or "Essay" (treat "SAQ" or "Short Answer" as "CRQ"; empty if unspecified)
        • limit: integer number of questions (default to 5 for "generate"; must be 0 for "list_topics" or "count_questions")
        • reply: one short, friendly sentence in a tutor's voice, addressed to the student

        ### Writing the reply
        The application appends the real results itself -- counts, topic names, the PDF link,
        the list of topics. Your reply is only the conversational opener that precedes them.
        - NEVER state a number of questions, a count, or claim what the database contains.
          You are reading the request before it has been looked up, so you do not know.
        - For "generate": acknowledge what they asked for and hand off, e.g.
          "Sure -- here's a set on quadratic functions:" or "Happy to help with exponents:".
          End with a colon so the results read as a continuation.
        - If this is a follow-up that changes the previous request (a different count, type,
          or topic), acknowledge the change: "Got it, switching to constructed-response:".
        - For "list_topics" / "count_questions": a brief lead-in, e.g. "Here's what I have for
          Algebra II:".
        - For "chitchat": answer them directly and warmly in one or two sentences, and steer
          back to practice. Greeting -> greet back and say what you can do. Thanks -> welcome
          them. Asking what you can do -> say you pull real past Regents questions for Algebra I,
          Algebra II, and Geometry, and can list topics or count them. A math question you
          cannot answer -> say you serve practice questions rather than solving problems, and
          offer questions on that topic instead. Do not end with a colon.
        - Never invent topic names, exam years, or statistics.

        ### Default rules & error-proofing
        - If the text asks to “list topics” or “what topics”, set intent="list_topics" (subject may still be filled).
        - If it asks “how many” or “count”, set intent="count_questions" (ignore or zero out limit).
        - If it is a greeting, thanks, small talk, a question about your capabilities, or a
          request you cannot serve from a question bank, set intent="chitchat" and leave
          subject, topic and type empty with limit 0.
        - Otherwise default intent="generate".
        - Non-numeric counts (“some”, “a few”) → limit=5.
        - Accept spelled-out numbers up to “twenty” (e.g. “ten”→10); else default limit=5.
        - The student does not have to name a subject to get a topic filled in. Some topic names appear
          under more than one subject (e.g. "Interpreting Functions" is both Algebra I and Algebra II) —
          match the topic from the whitelist regardless of whether subject is known, and leave subject
          empty if it wasn't stated or implied.
        - Match topics case-insensitively and tolerate minor wording differences (plural/singular,
          extra/missing words) as long as the intent clearly points to one whitelist entry. Do not
          invent a topic that isn't in the whitelist.
        - Always output valid JSON; do not include any extra text, explanations, or markdown.

        ### Subject → Topic Whitelist
        {topic_whitelist_section}
        {context_section}

        ### JSON schema (exactly these keys; no extras)
        {{
        "intent":  "<generate|list_topics|count_questions|chitchat>",
        "subject": "<subject or empty string>",
        "topic":   "<one valid topic for that subject or empty string>",
        "type":    "<MCQ|CRQ|Essay or empty string>",
        "limit":   <integer number of questions or 0>,
        "reply":   "<one short friendly sentence>"
        }}

        Student Query: "{query_text}"
            """.strip()
    try:
        response = session.post(
            FIREWORKS_URL,
            headers=FIREWORKS_HEADERS,
            json={
                "model": FIREWORKS_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                # Slightly above zero so the conversational reply doesn't read
                # identically every time; the structured fields are constrained
                # enough by the schema and whitelist that this doesn't loosen them.
                "temperature": 0.3,
                # Raised from 120 to leave room for the `reply` sentence.
                "max_tokens": 220,
                "response_format": {"type": "json_object"},
                "reasoning_effort": "none",
            },
        )
        response.raise_for_status()

        raw = response.json()["choices"][0]["message"]["content"]
        print(f"[DEBUG] Fireworks raw output:\n{raw}")

        parsed = json.loads(raw)

        subject = parsed.get("subject", "")
        if subject and not is_valid_subject(subject):
            print(f"[WARN] LLM returned unrecognized subject '{subject}'; discarding")
            subject = ""

        topic = clean_topic(parsed.get("topic", ""))
        if topic and not is_valid_topic(subject, topic):
            print(f"[WARN] LLM returned topic '{topic}' not in whitelist for subject '{subject}'; discarding")
            topic = ""

        qtype = parsed.get("type", "")
        if qtype and not is_valid_type(qtype):
            print(f"[WARN] LLM returned unrecognized type '{qtype}'; discarding")
            qtype = ""

        # The reply is conversational only -- the caller supplies every real
        # fact -- so a missing or overlong one degrades to the plain template
        # rather than failing the request.
        reply = str(parsed.get("reply", "") or "").strip()
        if len(reply) > 300:
            print("[WARN] LLM reply unusually long; discarding")
            reply = ""

        return (
            parsed.get("intent", "generate"),
            subject,
            topic,
            qtype,
            int(parsed.get("limit", 5)),
            reply,
        )

    except Exception as e:
        print(f"Fireworks parsing failed: {e}")
        # Always return exactly six elements:
        return ("generate", "", "", "", 5, "")
