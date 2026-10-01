"""Fingerprint what the API does with every question in the bank.

For each question: what /api/query sends before an attempt, and what
/api/check returns for each possible answer. Only a hash per id is stored,
so the committed file (the repo is public) reveals no answers or
explanations, yet any change to any question's payload or grading shows up.

  python -m tests.golden            # compare with tests/golden_math.json
  python -m tests.golden --update   # accept the current output as the baseline
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from answers import check_answer, public_question  # noqa: E402

MATH_SUBJECTS = ("Algebra I", "Geometry", "Algebra II")

GOLDEN_PATH = os.path.join(BACKEND, "tests", "golden_math.json")
ANSWERS = ("1", "2", "3", "4", "an unmatched answer")


def fingerprint(q):
    payload = {
        "public": public_question(q),
        "checks": [check_answer(q, a) for a in ANSWERS],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def compute(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Math only: ELA rows are new and have their own tests (tests/test_ela.py).
    rows = conn.execute("SELECT * FROM questions WHERE subject IN (?, ?, ?) ORDER BY id", MATH_SUBJECTS).fetchall()
    conn.close()
    return {str(r["id"]): fingerprint(dict(r)) for r in rows}


def load():
    with open(GOLDEN_PATH) as f:
        return json.load(f)


def compare(expected, actual):
    """(missing ids, new ids, changed ids)"""
    missing = sorted(set(expected) - set(actual), key=int)
    added = sorted(set(actual) - set(expected), key=int)
    changed = sorted((i for i in expected if i in actual and expected[i] != actual[i]), key=int)
    return missing, added, changed


def main():
    import db
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    actual = compute(db.DB_PATH)
    if args.update:
        with open(GOLDEN_PATH, "w") as f:
            json.dump(actual, f, indent=0, sort_keys=True)
        print(f"[golden] wrote {len(actual)} fingerprints")
        return
    missing, added, changed = compare(load(), actual)
    print(f"[golden] {len(actual)} questions; missing {len(missing)}, new {len(added)}, changed {len(changed)}")
    for label, ids in (("missing", missing), ("new", added), ("changed", changed)):
        if ids:
            print(f"  {label}: {', '.join(ids[:30])}{' ...' if len(ids) > 30 else ''}")
    sys.exit(1 if (missing or changed) else 0)


if __name__ == "__main__":
    main()
