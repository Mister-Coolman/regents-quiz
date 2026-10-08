# Releasing

The backend image carries the code, the question images and the SQLite
question bank together. That makes a release easy to undo (redeploy the
previous image and everything goes back at once), but it also means the
database file on this laptop *is* what ships. `scripts/release.sh` is the
checked path from here to production.

## Order

1. Backend first: `scripts/release.sh`.
2. Then the frontend: merge or push to `main`. Netlify builds it; it reports
   no status to GitHub, so open https://nystateregentsprep.netlify.app and
   check the change is live.

A frontend change that needs a new API field must wait for step 1.

## What release.sh does

| Step | Guards against |
|---|---|
| Clean git tree | an image that matches no commit |
| Schema is current (`migrate.py --status`) | deploying a DB the code can't read (the app would refuse to boot and Fly would keep the old release, but better to know first) |
| Back up the DB (`scripts/backup_db.sh`) | losing the only copy of a hand-edited bank; it is not in git |
| Empty the session tables | local test chats shipping in the public image |
| `scripts/check_data.py --ship` | missing images, bad answer keys, topics the parser can't name, question numbers that don't fit |
| `pytest` | answers or new columns leaking to the browser, grading changes (the golden test covers every question) |
| Record the current image in `~/regents-backups/releases.log` | not knowing what to roll back to |
| `fly deploy` | |
| `scripts/smoke.sh` | a deploy that boots but doesn't work: it runs a real query, check, image and PDF |

Off-laptop backups are paused for now (owner decision, 2026-10-01): the
script keeps a local copy and warns that it isn't mirrored. To mirror later,
set `REGENTS_BACKUP_MIRROR` to a folder synced off this laptop. To skip the
local copy too, run with `REGENTS_SKIP_BACKUP=1`.

`scripts/check_no_passages.sh` fails the release if any ELA passage line from
the database is in a file tracked by git (the repo is public).

## Rolling back

```bash
cd backend
fly deploy --image <previous_image from ~/regents-backups/releases.log>
```

Code and data go back together. Session data (open chats) is lost on any
deploy, rollback included; saved quiz progress lives in the browser and
survives.

For the frontend, use "Publish deploy" on the previous build in Netlify.

## Settings

| Name | Where | Default | Purpose |
|---|---|---|---|
| `FIREWORKS_API_KEY` | `fly secrets set` | none | query parsing |
| `ELA_ENABLED` | `fly secrets set` | off | serve ELA passage sets and show ELA on the welcome screen |
| `WITHDRAWN_STIMULI` | `fly secrets set` | none | comma-separated stimulus ids to stop serving at once (query, history and check) |
| `SET_TOKEN_SECRET` | `fly secrets set` | derived from `FIREWORKS_API_KEY` | signs practice sets so chats reopened from history can check answers; changing it (or the Fireworks key, while this is unset) makes older saved chats unable to check unanswered questions |
| `LLM_DAILY_CAP` | `fly secrets set` or `[env]` in fly.toml | 2000 | Fireworks calls per day across all visitors; past it, students see "Practice sets are paused for today because of heavy use. Try again tomorrow." |

Rate limits and the daily cap are counted in memory, which is exact for the
one machine and one gunicorn worker this app runs. Don't scale to more
machines or workers without moving them to shared storage.

## Monitoring

- `/readyz` reports the schema version, question counts, whether images are
  present and whether the LLM key is set. Point an uptime monitor at
  `https://backend-winter-smoke-307.fly.dev/readyz`.
- `fly logs | grep llm_call` shows every Fireworks call with its latency and
  token counts.

## ELA

ELA ships dark: the code, the passages and the frontend can all be live with
`ELA_ENABLED` off, and nothing ELA is served or shown.

### Adding many exams

`python scripts/ela_batch.py` downloads, extracts and dry-runs every exam
listed in `ela_extract.EXAMS` (all 34 Common Core and Next Generation
administrations) that isn't imported yet, and prints a table: ready to
review, extract failed, or import gates failed. Then take the ready ones
through steps 2 to 6 below. A passage whose type was misread (literary, poem,
informational) can be fixed in `scripts/ela_kinds.json`.

### Adding an exam

All on the laptop, no code changes:

1. `python scripts/ela_extract.py <code>` writes `scripts/ela_out/<code>/`
   (git-ignored): `bundle.json`, the crops and `review.html`.
2. Read each passage in `review.html` beside the exam PDF, line by line.
3. `python scripts/ela_import.py <code>` re-runs the hard gates and loads the
   exam. Re-importing keeps ids; a passage whose text changed loses its
   verification.
4. `python scripts/ela_stimuli.py verify <code> --by "<name>"` once the text
   is checked. Unverified passages are never served.
5. `python scripts/ela_explanations.py --exam <code> --dry-run`, read the
   report (every theme and "best supports" item by hand), then run it
   without `--dry-run`. A question that fails a validator ships without an
   explanation.
6. `scripts/release.sh`.

### Kill switches

| To | Do | Takes effect |
|---|---|---|
| Take down one passage now | `fly secrets set WITHDRAWN_STIMULI=12,13` | on the restart the secret triggers, within about 2 minutes |
| Keep it down in later releases | `python scripts/ela_stimuli.py withdraw 12 13`, then release | next release |
| Turn ELA off entirely | `fly secrets set ELA_ENABLED=false` | on restart |

A withdrawn passage disappears from new sets, from chat history and from
answer checks. `/readyz` shows `ela_enabled` and `withdrawn_stimuli`.

### Launch checklist

- [ ] The 6 most recent administrations imported, every passage verified
- [ ] Both kill switches tried once (on a deploy with ELA on, before telling anyone)
- [ ] noindex on the API (`X-Robots-Tag`, smoke test checks it)
- [ ] Download rejects ELA ids (smoke test checks it once ELA is on)
- [ ] `LLM_DAILY_CAP` set
- [ ] `fly secrets set ELA_ENABLED=true`, then `scripts/smoke.sh`, then watch
      `fly logs` for 72 hours

Deferred by the owner (2026-10-01): legal consult, a published rights contact
and takedown target (to be confirmed with NYSED later), off-laptop backups,
and a monthly Fireworks spending cap.
