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


def parse_query_with_ollama(query_text):
    topic_whitelist_section = build_topic_whitelist_markdown()
    print(f"[DEBUG] Parsing query with Fireworks: {query_text}")
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
                "model": FIREWORKS_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 120,
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

        return (
            parsed.get("intent", "generate"),
            subject,
            topic,
            qtype,
            int(parsed.get("limit", 5)),
        )

    except Exception as e:
        print(f"Fireworks parsing failed: {e}")
        # Always return exactly five elements:
        return ("generate", "", "", "", 5)
