"""Keep answers on the server until the student has made an attempt.

Questions leave /api/query without their answer key, explanation or rubric.
What the quiz needs up front -- the hints -- is cut from the explanation here,
and the rest is released per question by /api/check once an answer is in.
"""
import re

# The only question fields that reach the browser before an attempt. An
# allowlist, so a column added to the table later (question text, standards,
# rubric ids...) stays on the server until someone decides to send it.
PUBLIC_FIELDS = (
    "id", "subject", "topic", "month", "year", "type",
    "question_image_path", "question_no",
)

# Sent only when set, so rows that don't use them (every math question) send
# exactly what they always did. alt_text is what a screen reader announces for
# the question image; stimulus_ids and line_refs tie an ELA question to its
# passage and the lines its stem cites (they are added by db, not columns).
OPTIONAL_PUBLIC_FIELDS = ("alt_text", "stimulus_ids", "line_refs")

# Fields a student may not see before answering. A second check on top of the
# allowlist: none of these may ever be added to PUBLIC_FIELDS.
# question_text and choices are internal: the image is what students see.
HIDDEN_FIELDS = ("correct_answer", "explanation", "rubric", "question_text", "choices")
assert not (set(PUBLIC_FIELDS) | set(OPTIONAL_PUBLIC_FIELDS)) & set(HIDDEN_FIELDS)

# Explanations are generated in a fixed four-section shape (enforced by the
# validators in scripts/fireworks_explanations.py and ela_explanations.py):
#   **What's being asked** / **Approach** / **Work** (numbered steps) / **Answer**
HEADINGS = [
    ("asked", "What's being asked"),
    ("approach", "Approach"),
    ("work", "Work"),
]

# How many work steps a student may unlock before answering: enough to get
# unstuck, not enough to hand over the solution. The Answer section is never
# part of a hint.
MAX_HINT_STEPS = 2


def _section(text, label):
    # Accept either apostrophe the model emits in "What's being asked".
    pattern = re.escape(label).replace("'", "['’]")
    m = re.search(r"\*\*" + pattern + r"\*\*([\s\S]*?)(?=\n\s*\*\*|$)", text, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _steps(work):
    # A step starts at "1." / "2." at the beginning of a line; steps can span
    # several lines and contain $$ blocks.
    if not work:
        return []
    parts = re.split(r"\n(?=\s*\d+\.\s)", work)
    return [s for s in (re.sub(r"^\d+\.\s*", "", p.strip()).strip() for p in parts) if s]


def build_hints(explanation):
    """Ordered hints: the framing, then the method, then the opening steps."""
    if not explanation or not isinstance(explanation, str):
        return []
    parts = {key: _section(explanation, label) for key, label in HEADINGS}
    if not any(parts.values()):
        return []
    hints = []
    if parts["asked"]:
        hints.append({"label": "What's being asked", "body": parts["asked"]})
    if parts["approach"]:
        hints.append({"label": "Approach", "body": parts["approach"]})
    for i, body in enumerate(_steps(parts["work"])[:MAX_HINT_STEPS], start=1):
        hints.append({"label": f"Step {i}", "body": body})
    return hints


def public_question(q):
    """The question as the browser may see it before an answer is submitted."""
    out = {k: q[k] for k in PUBLIC_FIELDS if k in q}
    out.update({k: q[k] for k in OPTIONAL_PUBLIC_FIELDS if q.get(k) is not None})
    out["hints"] = build_hints(q.get("explanation"))
    return out


def is_gradable(q):
    """Constructed-response questions are stored without a key ("N/A"): they
    are marked by rubric, so the app can't say right or wrong."""
    ans = str(q.get("correct_answer") or "").strip()
    return q.get("type") == "MCQ" and ans not in ("", "N/A")


def check_answer(q, answer):
    """What the student gets back after an attempt."""
    gradable = is_gradable(q)
    correct = None
    if gradable:
        correct = str(answer).strip() == str(q["correct_answer"]).strip()
    return {
        "question_id": q["id"],
        "correct": correct,
        "correct_answer": q["correct_answer"] if gradable else None,
        "explanation": q.get("explanation"),
    }
