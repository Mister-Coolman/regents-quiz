"""Generate question explanations using Fireworks (Qwen3.7 Plus), the same
model the live app uses for query parsing.

Replaces the earlier local-Ollama approach: the hosted model is ~14x faster
(~2s vs ~26s per question), costs ~$0.001 per question, and is markedly more
accurate on multi-step math. It is multimodal, so it reads the question image
and reasons about it in a single call -- no separate transcription step.

IMPORTANT: `reasoning_effort: "none"` is required. Qwen3.7 Plus is a thinking
model; without it, raw chain-of-thought leaks into the response body (this is
why backend/llm_client.py sets the same flag).

Every explanation follows a fixed four-section format so the quiz UI renders
predictably. Responses that don't match are retried.

Usage:
  python3 fireworks_explanations.py --sample-per-topic 2   # spot-check sample
  python3 fireworks_explanations.py --limit 20             # first 20 pending
  python3 fireworks_explanations.py                        # everything pending
  python3 fireworks_explanations.py --regenerate           # redo ALL, even done ones

  --dry-run   generate + write the review report, but don't touch the DB
  --report FILE  where to write the HTML review report (default: explanation_review.html)
"""
import argparse
import base64
import csv
import html
import io
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", "backend", ".env"))

DB_PATH = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "regentsqs.db"))
IMG_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "static"))
BROKEN_CROPS_PATH = os.path.join(BASE_DIR, "broken_crops.csv")
NEEDS_REVIEW_PATH = os.path.join(BASE_DIR, "needs_review.csv")

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
One sentence restating the goal in plain terms. If the question has MULTIPLE PARTS (e.g. it asks \
you to both compute something AND explain/justify it, or asks two separate questions), name every \
part here.

**Approach**
One to two sentences naming the concept/formula/method that applies here.

**Work**
The actual step-by-step math, numbered steps if there's more than one. Read any graph/diagram \
values confidently and state them directly -- do not narrate your visual reading process or \
express uncertainty (no "wait", "let me re-examine", "looking closer", etc.).
Show computed numbers ONLY for the path leading to the correct answer. If a step here mentions \
a different answer option, state the concept or property that rules it out and stop there -- \
that step must contain no zeros, roots, intercepts, coordinates, or other computed values for \
that option.

**Answer**
One sentence stating the final result clearly.

CRITICAL: answer EVERY part the question asks for. Regents questions frequently have a second \
prompt further down the page (often after a large blank work space) -- read the whole image top \
to bottom and make sure no part goes unanswered.

ACCURACY REQUIREMENTS:

Do the full arithmetic only for the path that reaches the correct answer. Show those numbers, \
and make sure each one is actually computed rather than recalled or pattern-matched.

When you refer to any OTHER answer option, describe qualitatively why it fails -- name the \
concept, property, or mistake involved -- and do NOT state specific computed values for it \
(no zeros, roots, intercepts, coordinates, or numeric results for options you are not solving). \
Say "h(x) is undefined at x = 0, so it has no y-intercept", not "the zeros are 0.5 and -0.25". \
This restriction exists because unverified numbers attached to non-chosen options are the most \
common source of error -- omit the number instead of guessing it.

A shorter explanation that is entirely correct is much better than a fuller one containing a \
wrong value.

Use $...$ for inline math and $$...$$ for block equations.

Write any literal money amount with an escaped dollar sign -- \\$12.50, not $12.50 -- whether it \
appears in ordinary prose or inside a formula. An unescaped $ is read as a math delimiter, so a \
raw price silently turns the text after it into math.

Keep the whole response under 220 words."""

CONSTRUCTION_GUIDANCE = """
This is a compass-and-straightedge CONSTRUCTION question. Be especially careful:

- Describe the construction steps concretely (where the compass point goes, what width it is set \
to, which intersections get labeled), not just the end result.
- Before claiming any figure is equilateral/congruent/regular, VERIFY it. For a circle of radius \
$r$, a chord subtending a central angle $\\theta$ has length $2r\\sin(\\theta/2)$: a $60°$ arc gives \
a chord of exactly $r$, but a $120°$ arc gives $r\\sqrt{3}$, NOT $r$.
- Stepping the radius around a circle lands on 6 evenly spaced points ($60°$ apart) forming a \
regular HEXAGON. An inscribed equilateral triangle uses every OTHER one of those points \
($120°$ apart) -- three consecutive hexagon points do NOT form an equilateral triangle.
- Do not claim two different arcs meet at the same point unless they genuinely do.
- To erect a perpendicular AT a point $P$ that lies ON a line (not from an external point), \
use this exact method and commit to it: with the compass at $P$, draw an arc cutting the line on \
both sides of $P$ at $X$ and $Y$ (extend the line past $P$ first if $P$ is an endpoint); then from \
$X$ and $Y$ in turn, with a radius larger than $PX$, draw arcs meeting at $Z$; line $PZ$ is \
perpendicular to the original line at $P$. Do not offer two competing methods or trail off into \
an alternative -- pick one and give its complete steps."""

REQUIRED_HEADERS = ["**What's being asked**", "**Approach**", "**Work**", "**Answer**"]
MAX_ATTEMPTS = 3

# The accuracy instructions push the model to double-check its work, and it
# sometimes narrates that checking ("...wait, that connects adjacent hexagon
# points. Correction: ..."). The final answer is usually right, but a student
# shouldn't watch it argue with itself -- detect and retry rather than trying
# to prompt this away, since prompting for verification and prompting against
# narrating verification pull against each other.
#
# NOTE: deliberately does NOT match a bare "is incorrect" -- "Choice (1) is
# incorrect because..." is exactly the prose we want, and matching it flagged
# 24 of 26 sampled explanations. Only self-referential corrections count.
SELF_CORRECTION_RE = re.compile(
    r"\bwait\b"                       # "...wait, that connects adjacent points"
    r"|\bcorrection\s*:"              # "Correction: the vertices are..."
    r"|\blet me re-"                  # "let me re-examine"
    r"|\boops\b|\bscratch that\b|\bon second thought\b|\bdisregard th"
    r"|\bi made (?:an|a) (?:error|mistake)\b|\bmy mistake\b"
    r"|\bactually,\s*(?:no|that|it|this)\b"
    r"|is incorrect rearrangement"    # model labelling its own step wrong
    r"|\$\s*is incorrect"             # a formula immediately called incorrect
    r"|\bthat(?:'s| is) (?:wrong|not right)\b",
    re.IGNORECASE,
)

CROP_PROBE = """Look at this multiple-choice exam question image. On a single line, list ONLY the \
answer-choice numbers that are fully visible in the image, comma separated.
Format exactly: CHOICES: <numbers>
Example: CHOICES: 1,2,3,4
If a choice is cut off or missing from the image, do not list it."""

# Topics where the model is least reliable and output should be human-reviewed
# even when it looks well-formed.
REVIEW_TOPICS = {"Constructions"}


def build_prompt(qtype, correct_answer, topic=""):
    extra = CONSTRUCTION_GUIDANCE if topic in REVIEW_TOPICS else ""
    if qtype == "MCQ" and correct_answer and correct_answer != "N/A":
        return f"""This image shows a NY Regents exam multiple-choice math question. \
The correct answer is choice {correct_answer}.

Explain how to solve this problem and arrive at choice {correct_answer}. Explain the \
reasoning a student should use, not just the arithmetic. Do not start with "the correct \
answer is" -- teach it.
{extra}

{RESPONSE_FORMAT}"""
    return f"""This image shows a NY Regents exam constructed-response math question. \
Solve it yourself and write a worked solution a student could follow.
{extra}

{RESPONSE_FORMAT}"""


def is_well_formatted(content: str) -> bool:
    if not content.strip().startswith(REQUIRED_HEADERS[0]):
        return False
    positions = [content.find(h) for h in REQUIRED_HEADERS]
    if any(p == -1 for p in positions):
        return False
    if positions != sorted(positions):
        return False
    return not SELF_CORRECTION_RE.search(content)


def _call(prompt, img_b64, max_tokens, usage_acc):
    """Returns (content, finish_reason). finish_reason == 'length' means the
    response was cut off by max_tokens -- the caller should retry with more."""
    payload = {
        "model": FIREWORKS_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
            ],
        }],
        "temperature": 0.2 if max_tokens > 100 else 0,
        "max_tokens": max_tokens,
        "reasoning_effort": "none",
    }
    resp = requests.post(FIREWORKS_URL, headers=HEADERS, json=payload, timeout=90)
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    usage_acc["prompt_tokens"] += usage.get("prompt_tokens", 0)
    usage_acc["completion_tokens"] += usage.get("completion_tokens", 0)
    choice = data["choices"][0]
    return choice["message"]["content"], choice.get("finish_reason")


def check_crop(img_b64, qtype, correct_answer, usage_acc):
    """For MCQs, confirm all 4 answer choices are actually visible in the crop.
    Returns a reason string if the crop looks broken, else None.

    The YOLO crops that built this dataset sometimes cut off the answer choices,
    which would otherwise silently produce an explanation for a question the
    student can't fully see."""
    if qtype != "MCQ":
        return None

    out, _ = _call(CROP_PROBE, img_b64, 30, usage_acc)
    found = {int(n) for n in re.findall(r"[1-4]", out.split("CHOICES")[-1])}

    missing = sorted(set(range(1, 5)) - found)
    if missing:
        return f"answer choice(s) {missing} not visible in crop"
    try:
        if int(correct_answer) not in found:
            return f"correct_answer={correct_answer} not among visible choices"
    except (TypeError, ValueError):
        pass
    return None


def generate_explanation(image_path, qtype, correct_answer, topic=""):
    """Returns (explanation, usage, seconds, well_formatted, broken_reason)."""
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0}
    t0 = time.time()

    broken = check_crop(img_b64, qtype, correct_answer, total_usage)
    if broken:
        # Don't explain a question whose crop is missing content.
        return "", total_usage, time.time() - t0, False, broken

    prompt = build_prompt(qtype, correct_answer, topic)
    content, ok = "", False
    max_tokens = 900
    for _ in range(MAX_ATTEMPTS):
        content, finish = _call(prompt, img_b64, max_tokens, total_usage)
        if finish == "length":
            # Cut off mid-sentence. Retrying at the same ceiling just truncates
            # again, so give the next attempt more room.
            max_tokens = min(max_tokens * 2, 3000)
            ok = False
            continue
        ok = is_well_formatted(content)
        if ok:
            break

    return content, total_usage, time.time() - t0, ok, None


def select_rows(cur, args):
    cols = "id, subject, topic, month, year, type, correct_answer, question_image_path"

    if args.id:
        cur.execute(f"SELECT {cols} FROM questions WHERE id = ?", (args.id,))
        return cur.fetchall()

    if args.sample_per_topic:
        # Deterministic sample: the N lowest ids in each subject+topic pair.
        cur.execute(f"SELECT {cols} FROM questions ORDER BY subject, topic, id")
        by_topic = {}
        for row in cur.fetchall():
            key = (row[1], row[2])
            by_topic.setdefault(key, []).append(row)
        rows = []
        for key in sorted(by_topic):
            rows.extend(by_topic[key][:args.sample_per_topic])
        return rows

    where = "" if args.regenerate else "WHERE explanation IS NULL OR TRIM(explanation) = ''"
    cur.execute(f"SELECT {cols} FROM questions {where} ORDER BY id")
    rows = cur.fetchall()
    return rows[:args.limit] if args.limit else rows


def log_csv(path, r, reason):
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(["id", "subject", "topic", "month", "year", "type", "image_path", "reason"])
        w.writerow([r["id"], r["subject"], r["topic"], r["month"], r["year"],
                    r["type"], r["img_rel"], reason])


def thumbnail_data_uri(image_path, max_width=700):
    """Downscaled JPEG data URI, so a 96-question report stays a sane size."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        if im.width > max_width:
            im = im.resize((max_width, int(im.height * max_width / im.width)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=70, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


def write_report(path, results, meta):
    parts = [f"""<!doctype html>
<meta charset="utf-8">
<title>Explanation Review</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"
  onload="renderMathInElement(document.body, {{delimiters:[
    {{left:'$$',right:'$$',display:true}},{{left:'$',right:'$',display:false}}]}})"></script>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 900px;
         margin: 0 auto; padding: 2rem 1rem; color: #17212B; line-height: 1.5; }}
  h1 {{ font-size: 1.5rem; }}
  .summary {{ background: #EDF1F5; border-left: 3px solid #1E5AA8; padding: 1rem;
              border-radius: 2px 8px 8px 2px; margin-bottom: 2rem; }}
  .q {{ border: 1px solid #D3DCE6; border-radius: 10px; padding: 1.25rem;
        margin-bottom: 1.5rem; }}
  .meta {{ font-family: ui-monospace, monospace; font-size: .75rem; color: #5B6472;
           margin-bottom: .75rem; }}
  .flag {{ color: #C6483A; font-weight: 600; }}
  .review {{ color: #B4740A; font-weight: 600; }}
  img {{ max-width: 100%; border: 1px solid #D3DCE6; border-radius: 6px; }}
  .exp {{ background: #F7F9FB; border-left: 3px solid #1E5AA8; padding: .75rem 1rem;
          border-radius: 2px 8px 8px 2px; margin-top: 1rem; }}
  .exp strong {{ display: block; margin-top: .75rem; color: #123B6D; }}
  .exp strong:first-child {{ margin-top: 0; }}
</style>
<h1>Explanation Review</h1>
<div class="summary">
  <strong>{meta['count']} questions</strong> &middot; {meta['topics']} topics &middot;
  {meta['elapsed']:.0f}s &middot; <strong>${meta['cost']:.4f}</strong>
  (~${meta['projected']:.2f} projected for all 1,777)<br>
  Format OK: {meta['ok']}/{meta['explained']} explained
  &middot; Broken crops skipped: {meta['broken']}
  &middot; Flagged for review: {meta['review']}
  &middot; Model: Qwen3.7 Plus (Fireworks)<br>
  <em>Check each explanation against its question image. The math is what matters --
  formatting and crop completeness are already validated automatically.</em>
</div>"""]

    for r in results:
        body = html.escape(r["explanation"])
        for h_ in REQUIRED_HEADERS:
            label = h_.strip("*")
            body = body.replace(html.escape(h_), f"<strong>{label}</strong>")
        body = body.replace("\n", "<br>")
        flag = ""
        if r.get("broken"):
            flag += f' <span class="flag">[BROKEN CROP: {html.escape(r["broken"])} — not explained]</span>'
        if not r["ok"] and not r.get("broken"):
            flag += ' <span class="flag">[FORMAT FAILED]</span>'
        if r.get("needs_review"):
            flag += ' <span class="review">[NEEDS MANUAL REVIEW]</span>'
        parts.append(f"""<div class="q">
  <div class="meta">id={r['id']} &middot; {html.escape(r['subject'])} &middot;
    {html.escape(r['topic'])} &middot; {html.escape(r['month'])} {r['year']} &middot;
    {r['type']} &middot; answer: {html.escape(str(r['correct_answer']))}{flag}</div>
  <img src="{r['thumb']}" alt="question">
  <div class="exp">{body}</div>
</div>""")

    with open(path, "w") as f:
        f.write("\n".join(parts))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--id", type=int, default=None,
                        help="process a single question id (for spot re-checks)")
    parser.add_argument("--sample-per-topic", type=int, default=None,
                        help="take N questions from each subject+topic pair")
    parser.add_argument("--regenerate", action="store_true",
                        help="reprocess questions that already have explanations")
    parser.add_argument("--dry-run", action="store_true", help="don't write to the DB")
    parser.add_argument("--report", default="explanation_review.html")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    if not API_KEY:
        print("[ERROR] FIREWORKS_API_KEY not set in backend/.env")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = select_rows(cur, args)
    print(f"[INFO] {len(rows)} questions to process"
          + (" (dry run, DB not modified)" if args.dry_run else ""))

    results, total_cost, ok_count = [], 0.0, 0
    t_start = time.time()

    def work(row):
        qid, subject, topic, month, year, qtype, correct_answer, img_rel = row
        img_path = os.path.join(IMG_ROOT, img_rel)
        if not os.path.exists(img_path):
            return None
        explanation, usage, dt, ok, broken = generate_explanation(
            img_path, qtype, correct_answer, topic
        )
        return {
            "id": qid, "subject": subject, "topic": topic, "month": month, "year": year,
            "type": qtype, "correct_answer": correct_answer, "img_path": img_path,
            "img_rel": img_rel, "explanation": explanation, "usage": usage, "dt": dt,
            "ok": ok, "broken": broken, "needs_review": topic in REVIEW_TOPICS,
        }

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(work, row): row for row in rows}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                r = fut.result()
            except Exception as e:
                print(f"[ERROR] id={futures[fut][0]}: {e}")
                continue
            if r is None:
                continue

            cost = (r["usage"]["prompt_tokens"] / 1_000_000) * PRICE_INPUT \
                 + (r["usage"]["completion_tokens"] / 1_000_000) * PRICE_OUTPUT
            total_cost += cost
            results.append(r)

            if r["broken"]:
                log_csv(BROKEN_CROPS_PATH, r, r["broken"])
                # Clear any explanation left over from an earlier run -- a stale
                # explanation of a truncated question is worse than none at all.
                if not args.dry_run:
                    cur.execute("UPDATE questions SET explanation = NULL WHERE id = ?", (r["id"],))
                    conn.commit()
                print(f"[{i}/{len(rows)}] id={r['id']} ({r['type']}) BROKEN CROP: {r['broken']}")
                continue

            ok_count += int(r["ok"])
            if r["needs_review"]:
                log_csv(NEEDS_REVIEW_PATH, r, f"topic '{r['topic']}' always needs manual review")

            # Only persist explanations that passed validation -- a truncated or
            # malformed one is worse than leaving the field empty for a retry.
            if not args.dry_run:
                cur.execute("UPDATE questions SET explanation = ? WHERE id = ?",
                            (r["explanation"] if r["ok"] else None, r["id"]))
                conn.commit()

            flags = ""
            if not r["ok"]:
                flags += "  [FORMAT FAILED]"
            if r["needs_review"]:
                flags += "  [NEEDS REVIEW]"
            print(f"[{i}/{len(rows)}] id={r['id']} ({r['type']}) {r['dt']:.1f}s "
                  f"${cost:.5f}{flags}")

    conn.close()
    elapsed = time.time() - t_start

    results.sort(key=lambda r: (r["subject"], r["topic"], r["id"]))
    print("[INFO] building review report...")
    for r in results:
        r["thumb"] = thumbnail_data_uri(r["img_path"])

    n_broken = sum(1 for r in results if r["broken"])
    n_review = sum(1 for r in results if r["needs_review"] and not r["broken"])
    n_explained = len(results) - n_broken

    report_path = os.path.join(BASE_DIR, args.report)
    write_report(report_path, results, {
        "count": len(results),
        "explained": n_explained,
        "broken": n_broken,
        "review": n_review,
        "topics": len({(r["subject"], r["topic"]) for r in results}),
        "elapsed": elapsed,
        "cost": total_cost,
        "projected": total_cost / max(len(results), 1) * 1777,
        "ok": ok_count,
    })

    print(f"\n{'=' * 60}")
    print(f"{len(results)} questions in {elapsed:.0f}s  |  ${total_cost:.4f}")
    print(f"  explained:     {n_explained}  (format ok {ok_count}/{n_explained})")
    print(f"  broken crops:  {n_broken}  -> {BROKEN_CROPS_PATH}")
    print(f"  needs review:  {n_review}  -> {NEEDS_REVIEW_PATH}")
    print(f"Projected for all 1,777: ${total_cost / max(len(results), 1) * 1777:.2f}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
