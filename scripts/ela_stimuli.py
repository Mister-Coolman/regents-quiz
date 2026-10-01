"""List, verify and withdraw ELA passages (stimuli) in the question bank.

A passage is served only after a person has checked it line by line against
the printed exam (open scripts/ela_out/<code>/review.html beside the PDF) and
recorded that here. A withdrawn passage is never served, whatever else is set.

  python scripts/ela_stimuli.py list [626]
  python scripts/ela_stimuli.py verify 626 --by "Arjun" [--label A]
  python scripts/ela_stimuli.py unverify 626 --label C
  python scripts/ela_stimuli.py withdraw 12 13          # stimulus ids
  python scripts/ela_stimuli.py restore 12

To take a passage down in production right away, without a release:
  fly secrets set WITHDRAWN_STIMULI=12,13
then record it here with `withdraw` so the next release keeps it down.
"""
import argparse
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "backend", "regentsqs.db")


def _exam_filter(code):
    if not code:
        return "", []
    return " AND e.code = ?", [code]


def cmd_list(conn, args):
    where, params = _exam_filter(args.code)
    rows = conn.execute(f"""
      SELECT s.id, e.code, e.month, e.year, s.label, s.kind, s.title, s.lines, s.rights_status,
             s.verified_by, s.verified_at,
             (SELECT COUNT(*) FROM question_stimuli qs WHERE qs.stimulus_id = s.id)
      FROM stimuli s JOIN exams e ON e.id = s.exam_id
      WHERE e.subject = 'ELA'{where}
      ORDER BY e.year, e.month, s.label
    """, params).fetchall()
    for sid, code, month, year, label, kind, title, lines, rights, by, at, nq in rows:
        state = "WITHDRAWN" if rights == "withdrawn" else (f"verified by {by} {at}" if at else "NOT VERIFIED")
        print(f"{sid:>4}  {code} {month} {year}  {label}  {kind:<13} {len(json.loads(lines)):>3} lines "
              f"{nq:>2} qs  {state}  {title or ''}")
    if not rows:
        print("no passages")


def cmd_verify(conn, args, verified):
    where, params = _exam_filter(args.code)
    if args.label:
        where += " AND s.label = ?"
        params.append(args.label)
    ids = [r[0] for r in conn.execute(
        f"SELECT s.id FROM stimuli s JOIN exams e ON e.id = s.exam_id WHERE e.subject = 'ELA'{where}", params)]
    if not ids:
        raise SystemExit("no matching passages")
    ph = ",".join("?" * len(ids))
    if verified:
        conn.execute(f"UPDATE stimuli SET verified_by = ?, verified_at = CURRENT_TIMESTAMP WHERE id IN ({ph})",
                     [args.by, *ids])
    else:
        conn.execute(f"UPDATE stimuli SET verified_by = NULL, verified_at = NULL WHERE id IN ({ph})", ids)
    conn.commit()
    print(f"{'verified' if verified else 'unverified'} stimulus ids {ids}")


def cmd_rights(conn, args, status):
    ph = ",".join("?" * len(args.ids))
    n = conn.execute(f"UPDATE stimuli SET rights_status = ? WHERE id IN ({ph})", [status, *args.ids]).rowcount
    conn.commit()
    print(f"set {n} passage(s) to {status}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=DB_PATH)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("code", nargs="?")
    for name in ("verify", "unverify"):
        p = sub.add_parser(name)
        p.add_argument("code")
        p.add_argument("--label")
        if name == "verify":
            p.add_argument("--by", required=True, help="who checked the text against the exam")
    for name in ("withdraw", "restore"):
        p = sub.add_parser(name)
        p.add_argument("ids", nargs="+", type=int)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        if args.cmd == "list":
            cmd_list(conn, args)
        elif args.cmd in ("verify", "unverify"):
            cmd_verify(conn, args, args.cmd == "verify")
        else:
            cmd_rights(conn, args, "withdrawn" if args.cmd == "withdraw" else "unreviewed")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
