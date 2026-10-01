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

Set `REGENTS_BACKUP_MIRROR` to a folder that is synced off this laptop (for
example a cloud-drive folder). Without it the backup script warns that the
copy shares a disk with the original.

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
