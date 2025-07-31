#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta

# — adjust to your DB path —
DB_PATH = "regentsqs.db"

# how old (days) before we delete
TTL_DAYS = 1

def cleanup():
    cutoff = datetime.now() - timedelta(days=TTL_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DB_PATH)
    cur  = conn.cursor()

    # delete messages for stale sessions
    cur.execute("""
      DELETE FROM session_messages
       WHERE session_id IN (
         SELECT session_id FROM sessions
          WHERE last_active < ?
       )
    """, (cutoff_str,))

    # delete the sessions themselves
    cur.execute("""
      DELETE FROM sessions
       WHERE last_active < ?
    """, (cutoff_str,))

    conn.commit()
    conn.close()
    print(f"[cleanup] removed sessions inactive before {cutoff_str}")

if __name__ == "__main__":
    cleanup()
