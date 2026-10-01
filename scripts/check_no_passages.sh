#!/usr/bin/env bash
# Fail if any ELA passage text is tracked in git. The repo is public and most
# passages are third-party copyrighted text: they live only in the database
# (which ships inside the image, never in git). Question crops are NYSED
# material and may be committed; passages and their figures may not.
#   scripts/check_no_passages.sh [path/to/regentsqs.db]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${1:-$ROOT/backend/regentsqs.db}"
PY="${PYTHON:-python3}"

"$PY" - "$DB" "$ROOT" <<'PYEOF'
import json, os, re, sqlite3, subprocess, sys

db, root = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(db)
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
if "stimuli" not in tables:
    print("[passages] no stimuli table; nothing to check")
    sys.exit(0)

norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()
# Distinctive lines only: short ones ("And then", "I") match by accident.
needles = set()
for (lines,) in conn.execute("SELECT lines FROM stimuli"):
    for line in json.loads(lines):
        t = norm(line.get("text", ""))
        if len(t) >= 40:
            needles.add(t)
conn.close()
if not needles:
    print("[passages] no passage text in the database yet")
    sys.exit(0)

hits = []
# Files that would reach GitHub: everything tracked or staged.
tracked = subprocess.run(["git", "-C", root, "ls-files", "--cached"], capture_output=True, text=True, check=True).stdout
for rel in tracked.split("\n"):
    path = os.path.join(root, rel)
    if not rel or not os.path.isfile(path) or os.path.getsize(path) > 5_000_000:
        continue
    try:
        with open(path, encoding="utf-8") as f:
            text = norm(f.read())
    except (UnicodeDecodeError, OSError):
        continue  # binary
    found = [n for n in needles if n in text]
    if found:
        hits.append((rel, len(found), found[0][:70]))

for rel, n, sample in hits:
    print(f"[passages] {rel}: {n} passage line(s), e.g. \"{sample}...\"")
if hits:
    print("[passages] FAILED: remove these from git (git rm --cached) before releasing")
    sys.exit(1)
print(f"[passages] ok: none of {len(needles)} passage lines is in a tracked file")
PYEOF
