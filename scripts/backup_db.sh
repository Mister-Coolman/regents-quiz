#!/usr/bin/env bash
# Copy the question bank somewhere safe. The database isn't in git, so these
# copies are the only way back from a bad edit.
#
#   REGENTS_BACKUP_DIR     local folder (default ~/regents-backups)
#   REGENTS_BACKUP_MIRROR  a second folder off this laptop, e.g. a synced
#                          cloud-drive folder. Without it the backup lives on
#                          the same disk as the original, and this says so.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/backend/regentsqs.db"
DIR="${REGENTS_BACKUP_DIR:-$HOME/regents-backups}"
mkdir -p "$DIR"

TMP="$DIR/.incoming.db"
# .backup takes a consistent copy even if something has the file open.
sqlite3 "$DB" ".backup '$TMP'"
SUM="$(shasum -a 256 "$TMP" | cut -c1-12)"
OUT="$DIR/regentsqs-$(date +%Y%m%d-%H%M%S)-$SUM.db"
mv "$TMP" "$OUT"
echo "[backup] $OUT"

if [[ -n "${REGENTS_BACKUP_MIRROR:-}" ]]; then
  mkdir -p "$REGENTS_BACKUP_MIRROR"
  cp "$OUT" "$REGENTS_BACKUP_MIRROR/"
  MIRRORED="$REGENTS_BACKUP_MIRROR/$(basename "$OUT")"
  if [[ "$(shasum -a 256 "$MIRRORED" | cut -c1-12)" != "$SUM" ]]; then
    echo "[backup] mirror copy doesn't match" >&2
    exit 1
  fi
  echo "[backup] mirrored to $MIRRORED"
else
  echo "[backup] WARNING: REGENTS_BACKUP_MIRROR is not set, so this backup is only on this laptop"
fi
