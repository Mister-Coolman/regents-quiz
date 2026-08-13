#!/bin/bash
# Runs generate_explanations.py overnight: keeps the Mac awake, runs detached
# from the terminal, and logs progress. Safe to Ctrl-C or close the terminal --
# next run (any night) picks up wherever this one left off.
#
# Usage:
#   ./run_explanations_overnight.sh 880      # process the next 880 pending questions
#   ./run_explanations_overnight.sh           # process everything remaining

cd "$(dirname "$0")"

LIMIT_ARGS=()
if [ -n "$1" ]; then
  LIMIT_ARGS=(--limit "$1")
fi

LOG_FILE="explanations_run_$(date +%Y%m%d_%H%M%S).log"

echo "Starting run, logging to $LOG_FILE"
echo "Watch progress with: tail -f scripts/$LOG_FILE"

caffeinate -i nohup python3 -u generate_explanations.py "${LIMIT_ARGS[@]}" > "$LOG_FILE" 2>&1 &
disown

echo "Started in background (pid $!)."
