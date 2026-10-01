#!/usr/bin/env bash
# The one checked path from a laptop to production for the backend.
# See RELEASE.md for what each step guards against and how to roll back.
#   scripts/release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/backend/venv/bin/python"
DB="$ROOT/backend/regentsqs.db"
LOG="${REGENTS_BACKUP_DIR:-$HOME/regents-backups}/releases.log"
step() { echo; echo "== $*"; }

step "1. Clean git tree"
if [[ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
  git -C "$ROOT" status --short --untracked-files=no
  echo "Commit or stash these first: the image must match a commit." >&2
  exit 1
fi
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD)"

step "2. Schema is current"
(cd "$ROOT/backend" && "$PY" migrate.py --status)
(cd "$ROOT/backend" && "$PY" -c "
import sqlite3, db, migrate
v = sqlite3.connect(db.DB_PATH).execute('PRAGMA user_version').fetchone()[0]
assert v == migrate.latest_version() == db.SCHEMA_VERSION, 'run python migrate.py (and bump db.SCHEMA_VERSION)'
")

step "3. Back up the database (before anything changes it)"
"$ROOT/scripts/backup_db.sh"

step "4. Empty the session tables, so local chats don't ship in the image"
sqlite3 "$DB" "DELETE FROM session_questions; DELETE FROM session_messages; DELETE FROM sessions; VACUUM;"

step "5. Data checks"
"$PY" "$ROOT/scripts/check_data.py" --ship

step "6. Tests (including the golden math payloads)"
(cd "$ROOT/backend" && "$PY" -m pytest -q)

step "7. Record the current release, the rollback target"
mkdir -p "$(dirname "$LOG")"
PREV="$(cd "$ROOT/backend" && fly releases --image -j | python3 -c 'import json,sys; r=json.load(sys.stdin)[0]; print(r["ImageRef"])')"
echo "$(date -u +%FT%TZ) commit=$COMMIT previous_image=$PREV" >> "$LOG"
echo "rollback target: $PREV (logged to $LOG)"

step "8. Deploy"
(cd "$ROOT/backend" && fly deploy)

step "9. Smoke test production"
"$ROOT/scripts/smoke.sh"

echo
echo "Released $COMMIT. If anything looks wrong: cd backend && fly deploy --image $PREV"
