"""Extract and dry-run many ELA exams in one go, with a summary table.

For each code: download the files if they aren't there yet, run
ela_extract.py, then ela_import.py --dry-run. Nothing is imported; do that
per exam once its review page has been checked.

  python scripts/ela_batch.py              # every exam not yet in the database
  python scripts/ela_batch.py 615 815 116  # just these

The table goes to the screen and to scripts/ela_out/batch.txt. For a failed
exam, the first errors are shown; the full output is in
scripts/ela_out/<code>/batch.log.
"""
import glob
import os
import sqlite3
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)
from ela_extract import EXAMS, PDF_DIR  # noqa: E402

DB_PATH = os.path.join(ROOT, "backend", "regentsqs.db")
OUT = os.path.join(SCRIPTS, "ela_out")


def imported_codes():
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""SELECT DISTINCT e.code FROM exams e JOIN questions q ON q.exam_id = e.id
                               WHERE q.subject = 'ELA'""").fetchall()
        conn.close()
        return {r[0] for r in rows}
    except sqlite3.Error:
        return set()


def run(cmd, cwd):
    p = subprocess.run([sys.executable, *cmd], cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    codes = sys.argv[1:] or [c for c in EXAMS if c not in imported_codes()]
    rows = []
    for code in codes:
        if code not in EXAMS:
            rows.append((code, "unknown code", ""))
            continue
        meta = EXAMS[code]
        have = glob.glob(os.path.join(PDF_DIR, code, "*.pdf"))
        cmd = ["ela_extract.py", code] + ([] if have else ["--download"])
        print(f"[batch] {code} ({meta['month']} {meta['year']}) ...", flush=True)
        rc, log = run(cmd, SCRIPTS)
        os.makedirs(os.path.join(OUT, code), exist_ok=True)
        if rc == 0:
            rc2, log2 = run(["scripts/ela_import.py", code, "--dry-run"], ROOT)
            log += "\n" + log2
        with open(os.path.join(OUT, code, "batch.log"), "w") as f:
            f.write(log)
        lines = log.splitlines()
        if rc != 0:
            problems = [l for l in lines if l.startswith(("[error]", "[ela] need", "[ela] couldn't", "[ela] no page"))
                        or "Traceback" in l or l.startswith(("Error", "FileNotFound"))]
            rows.append((code, "extract failed", " | ".join(problems[:3]) or (lines[-1] if lines else "")))
        elif rc2 != 0:
            gates = [l for l in log2.splitlines() if l.startswith("[gate]")]
            rows.append((code, "import gates failed", " | ".join(gates[:3])))
        else:
            checks = sum(1 for l in lines if l.startswith(("[check]", "[warn]")))
            rows.append((code, "ready to review", f"{checks} warnings" if checks else ""))

    width = max([len(EXAMS.get(c, {}).get("month", "")) for c, _, _ in rows] + [0])
    table = [f"{'code':<5} {'exam':<{width + 5}} {'status':<20} details"]
    for code, status, detail in rows:
        meta = EXAMS.get(code, {"month": "?", "year": "?"})
        table.append(f"{code:<5} {meta['month'] + ' ' + str(meta['year']):<{width + 5}} {status:<20} {detail[:160]}")
    text = "\n".join(table)
    print("\n" + text)
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "batch.txt"), "w") as f:
        f.write(text + "\n")
    ready = [c for c, s, _ in rows if s == "ready to review"]
    if ready:
        print(f"\n[batch] {len(ready)} ready. For each: check scripts/ela_out/<code>/review.html, then "
              f"ela_import.py <code>, ela_stimuli.py verify <code>, explanations.")


if __name__ == "__main__":
    main()
