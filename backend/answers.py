"""Keep answers on the server until the student has made an attempt.

Questions leave /api/query without their answer key, explanation or rubric.
What the quiz needs up front -- the hints -- is cut from the explanation here,
and the rest is released per question by /api/check once an answer is in.
"""
import re

# Fields a student may not see before answering.
HIDDEN_FIELDS = ("correct_answer", "explanation", "rubric")

# Explanations are generated in a fixed four-section shape (enforced by the
# validator in scripts/fireworks_explanations.py):
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
    out = {k: v for k, v in q.items() if k not in HIDDEN_FIELDS}
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
