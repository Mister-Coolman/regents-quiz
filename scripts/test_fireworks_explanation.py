"""Quick test of using Fireworks Qwen3.7 Plus (same model as the live query
parser) to generate explanations directly from the question image in a
single call -- no separate local transcription step needed, since this model
is multimodal.

Measures actual cost (via the API's own token usage) and latency, and prints
the explanation for manual quality review, on a handful of sample questions.

Usage:
  python3 test_fireworks_explanation.py
  python3 test_fireworks_explanation.py --id 987
"""
import argparse
import base64
import os
import sqlite3
import time

import requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", "backend", ".env"))

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))

FIREWORKS_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = "accounts/fireworks/models/qwen3p7-plus"
API_KEY = os.getenv("FIREWORKS_API_KEY")

# Per 1M tokens, from Fireworks' published pricing for this model.
PRICE_INPUT = 0.40
PRICE_OUTPUT = 1.60

HEADERS = {
    "Accept": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}


RESPONSE_FORMAT = """Format your entire response using EXACTLY these four section headers, in \
this order, every time. Your response must START IMMEDIATELY with "**What's being asked**" -- \
no preamble, no meta-commentary about the task, no other headers:

**What's being asked**
One sentence restating the goal in plain terms.

**Approach**
One to two sentences naming the concept/formula/method that applies here.

**Work**
The actual step-by-step math, numbered steps if there's more than one. Read any graph/diagram \
values confidently and state them directly -- do not narrate your visual reading process or \
express uncertainty (no "wait", "let me re-examine", "looking closer", etc.).

**Answer**
One sentence stating the final result clearly.

Use $...$ for inline math and $$...$$ for block equations. Keep the whole response under 220 words."""


def build_prompt(qtype, correct_answer, transcript=None):
    """Prompt for the explanation step. If `transcript` is given, reason from
    that text instead of directly from the image (two-call mode)."""
    source = (
        f"Below is a transcription of a NY Regents exam math question.\n\n{transcript}\n"
        if transcript
        else "This image shows a NY Regents exam math question."
    )

    if qtype == "MCQ" and correct_answer and correct_answer != "N/A":
        return f"""{source}
The correct answer is choice {correct_answer}.

Explain how to solve this problem and arrive at choice {correct_answer}. Explain the \
reasoning a student should use, not just the arithmetic. Do not start with "the correct \
answer is" -- teach it.

{RESPONSE_FORMAT}"""
    return f"""{source}
This is a constructed-response question. Solve it yourself and write a worked solution a \
student could follow.

{RESPONSE_FORMAT}"""


TRANSCRIBE_PROMPT = """Transcribe this Regents exam question image exactly as it appears. Include:
- The full question text
- Any answer choices (numbered 1-4), verbatim
- A precise description of any diagram, graph, table, or figure: state the axis labels and \
scales, the coordinates of key points (maxima, minima, intercepts, labeled points), the period \
and amplitude of any wave, and any given values or units.

Read gridlines and axis labels carefully and commit to specific numeric values. Do not answer \
the question. Do not add commentary. Just transcribe and describe what is on the page."""

REQUIRED_HEADERS = ["**What's being asked**", "**Approach**", "**Work**", "**Answer**"]
MAX_ATTEMPTS = 2


def is_well_formatted(content: str) -> bool:
    if not content.strip().startswith(REQUIRED_HEADERS[0]):
        return False
    positions = [content.find(h) for h in REQUIRED_HEADERS]
    if any(p == -1 for p in positions):
        return False
    return positions == sorted(positions)


def _call_fireworks(prompt, image_b64=None, max_tokens=900):
    content = [{"type": "text", "text": prompt}]
    if image_b64:
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
        )
    payload = {
        "model": FIREWORKS_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        # Qwen3.7 Plus is a thinking model -- without this it dumps its raw
        # chain-of-thought into the response body. The live query parser in
        # backend/llm_client.py sets this for the same reason.
        "reasoning_effort": "none",
    }
    resp = requests.post(FIREWORKS_URL, headers=HEADERS, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _add_usage(total, data):
    usage = data.get("usage", {})
    total["prompt_tokens"] += usage.get("prompt_tokens", 0)
    total["completion_tokens"] += usage.get("completion_tokens", 0)


def generate_explanation(image_path, qtype, correct_answer, two_call=False):
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    t0 = time.time()

    transcript = None
    if two_call:
        data = _call_fireworks(TRANSCRIBE_PROMPT, image_b64=img_b64, max_tokens=900)
        _add_usage(total_usage, data)
        transcript = data["choices"][0]["message"]["content"]

    prompt = build_prompt(qtype, correct_answer, transcript)
    content = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        # In two-call mode the reasoning step works from the transcript only,
        # so the image isn't re-sent (cheaper, and keeps the model focused on
        # the math rather than re-reading the graph).
        data = _call_fireworks(prompt, image_b64=None if two_call else img_b64)
        content = data["choices"][0]["message"]["content"]
        _add_usage(total_usage, data)
        if is_well_formatted(content):
            break
        if attempt < MAX_ATTEMPTS:
            print(f"    [RETRY] malformed response (attempt {attempt}/{MAX_ATTEMPTS})")
    dt = time.time() - t0

    return content, total_usage, dt, transcript


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, default=None)
    parser.add_argument("--two-call", action="store_true",
                        help="transcribe the image first, then reason from the transcript")
    parser.add_argument("--show-transcript", action="store_true")
    args = parser.parse_args()

    if not API_KEY:
        print("[ERROR] FIREWORKS_API_KEY not set in backend/.env")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    if args.id:
        ids = [args.id]
    else:
        # A representative mix: a couple of MCQs (one we've seen locally
        # before, for direct quality comparison) and a CRQ.
        ids = [1, 987, 200]

    total_cost = 0.0
    for qid in ids:
        cur.execute(
            "SELECT type, correct_answer, question_image_path, subject, topic FROM questions WHERE id = ?",
            (qid,),
        )
        row = cur.fetchone()
        if not row:
            print(f"[WARN] id={qid} not found")
            continue
        qtype, correct_answer, img_rel, subject, topic = row
        img_path = os.path.join(IMG_ROOT, img_rel)

        try:
            content, usage, dt, transcript = generate_explanation(
                img_path, qtype, correct_answer, two_call=args.two_call
            )
        except Exception as e:
            print(f"[ERROR] id={qid}: {e}")
            continue

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cost = (prompt_tokens / 1_000_000) * PRICE_INPUT + (completion_tokens / 1_000_000) * PRICE_OUTPUT
        total_cost += cost

        mode = "two-call" if args.two_call else "one-call"
        print(f"\n{'=' * 70}")
        print(f"id={qid} ({subject} / {topic} / {qtype}) [{mode}] -- {dt:.1f}s, "
              f"{prompt_tokens} in + {completion_tokens} out tokens, ${cost:.5f}")
        print(f"{'-' * 70}")
        if transcript and args.show_transcript:
            print("--- TRANSCRIPT ---")
            print(transcript)
            print("--- EXPLANATION ---")
        print(content)
        print(f"[format ok: {is_well_formatted(content)}]")

    print(f"\n{'=' * 70}")
    print(f"Total for {len(ids)} questions: ${total_cost:.5f}  "
          f"(~${total_cost / len(ids) * 1777:.2f} projected for all 1777 questions)")

    conn.close()


if __name__ == "__main__":
    main()
