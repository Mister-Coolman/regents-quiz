# NY State Regents Prep AI

Practice New York State Regents exams using real past questions, interactive
quizzes, progressive hints, and AI-generated worked explanations. Math practice
covers **Algebra I, Algebra II, and Geometry**. **ELA Part 1 reading practice** is
implemented behind a feature flag and is off by default.

[Open the app](https://nystateregentsprep.netlify.app/)

## Features

- Ask for practice questions, list topics, or count matching questions in plain
  English. Follow-ups can reuse the previous subject, topic, and question type.
  Math sets prefer questions not yet served in the current session.
- View question images cropped from official exams; download math practice sets
  as PDFs generated on demand.
- Check multiple-choice answers on the server. Answer keys, full explanations,
  and rubrics are omitted from the initial question payload; `/api/check`
  releases feedback for the submitted question.
- Written-response questions are available for practice but **are not
  automatically graded** and do not count toward the score or missed questions.
- Where an explanation is available, reveal hints in order: “What's being
  asked,” “Approach,” then up to two work steps. These are excerpts from the
  explanation, not separately generated hints.
- Open a full explanation after answering; it opens automatically on a miss.
  Explanations follow four sections: “What's being asked,” “Approach,” “Work,”
  and “Answer,” with Markdown and KaTeX math rendering. They are AI-generated
  and can contain errors; some questions have no explanation.
- Resume quiz progress in the same browser, review missed answers, and see the
  total hints used and a score dial at the end.
- Reopen or delete saved chats, grouped by day. Chats and quiz progress use
  browser localStorage, not an account or cross-device sync.
- When enabled, ELA serves complete passage sets in a side-by-side reader, with
  printed line numbers, cited-line highlighting, footnotes, and elapsed time.
  It covers Part 1 multiple-choice reading, not essay or written-response
  scoring. ELA sets cannot be exported as PDFs.

## Architecture

- **Backend:** Flask + SQLite, deployed on Fly.io. Question metadata,
  explanations, and ELA passage data live in `backend/regentsqs.db`; question
  images live under `backend/static/images/`.
- **AI:** Fireworks `accounts/fireworks/models/deepseek-v4p1-flash` handles live
  query parsing and the current offline math and ELA explanation generators.
  Explanations are generated ahead of time and stored in the database.
- **Frontend:** React + Vite, deployed on Netlify. It requests available feature
  flags from `/api/features`, so ELA can be enabled without a frontend rebuild.
- **Saved sets:** signed tokens let reopened chats check answers after server
  session tables are cleared, provided the signing key remains stable and the
  questions remain available. ELA availability and withdrawal rules still apply.
- **Deployment data:** the SQLite bank and images ship inside the backend image;
  the database is not committed to Git. Server session history is not durable
  across releases. Browser-saved chats and quiz progress are separate.

## Local setup

Use Python 3.11 (the backend Docker runtime) and a Node.js version supported by
Vite 7, such as Node 22.12 or newer in the Node 22 series, plus npm.

### Backend

A fresh clone does not contain the question database. Restore an existing bank
as `backend/regentsqs.db` and ensure its referenced images are present.
Migrations update the schema; they do not populate the question bank.

From the repository root:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

Create `backend/.env` (Git-ignored):

```dotenv
FIREWORKS_API_KEY=your_api_key
SET_TOKEN_SECRET=your_stable_random_secret
ELA_ENABLED=false
```

Keep `SET_TOKEN_SECRET` stable to preserve saved-set tokens. If omitted, it is
derived from `FIREWORKS_API_KEY`; changing that key then invalidates old tokens.
Without either key, tokens last only for the current backend process.

From `backend/`, with the virtual environment active:

```bash
python migrate.py
python app.py
```

The backend listens on `http://localhost:8080`. It checks the schema at startup
and refuses an older database. Add schema changes as numbered files in
`backend/migrations/`, then apply them offline with `python migrate.py`.

### Frontend

In a second terminal, from the repository root:

```bash
cd frontend
npm ci
```

Create `frontend/.env.local` (Git-ignored) with this local override:

```dotenv
VITE_API_BASE_URL=
```

Then run `npm run dev` and open `http://localhost:5173`. The blank value makes
Vite proxy `/api` and `/images` to the local backend on port 8080. The tracked
`frontend/.env` points to production; keep local overrides in `.env.local`.
Restart Vite after changing environment files.

Frontend dependencies are managed by `package.json` and `package-lock.json`,
not a Python `requirements.txt`. Build with `npm run build`.

## Verification

From `backend/`, with the virtual environment active:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Backend tests stub the LLM and use temporary databases. Tests requiring the real
question bank use a copy and skip when it is absent; synthetic-bank tests can
still run. `backend/tests/golden_math.json` fingerprints math payloads and
answer checking. After reviewing an intentional change, regenerate it from
`backend/` with `python -m tests.golden --update`.

From the repository root, `scripts/smoke.sh [base-url]` checks the deployed API,
answer checking, an image, and a PDF; it also checks ELA when enabled. It
**makes real Fireworks calls** and defaults to the production backend.

## Data preparation

Run scripts from the repository root with the backend virtual environment
active. Current extraction, recropping, explanation, and rubric tools need:

```bash
python -m pip install requests python-dotenv Pillow PyMuPDF numpy
```

- `download_exams.py` and `download_rating_guides.py` download source material.
- `recrop_broken.py` repairs existing question crops by matching them to the
  original PDF and expanding their boundaries. It is not a replacement for
  initial question extraction.
- `fireworks_explanations.py` generates and validates math explanations using
  Fireworks, with dry-run reports for review.
- `ela_extract.py`, `ela_import.py`, and `ela_stimuli.py` extract, import, verify,
  and withdraw ELA passages. Only verified, available passages may be served.
- `ela_explanations.py` generates ELA explanations with format, answer-key,
  quotation-length, and cited-line checks. Flagged items need human review.
- `backfill_crq_rubrics.py` prepares rubric data using a local Ollama model;
  it does not implement student-response grading.
- `generate_explanations.py` is the older local Ollama explanation generator
  (`qwen2.5vl:7b`), not the current Fireworks generator.
- The older YOLO/OCR tools (`run_pipeline.py`, `extract_topics.py`, and
  `image2latex_test.py`) need additional ML/OCR dependencies not installed above.

See [RELEASE.md](RELEASE.md) for the ELA import/review workflow and switches.
Keep passage text and passage-containing review artifacts out of the public
repository; `scripts/check_no_passages.sh` checks tracked files before release.

## Deployment and operations

Release the backend first with `scripts/release.sh` from the repository root,
then push or merge frontend changes to `main` for Netlify. The release script
uses `backend/venv/bin/python` and requires the Fly CLI, authentication, Git,
and the SQLite CLI.

The script checks tracked changes and schema compatibility, backs up the bank,
**clears local session tables**, runs data checks and tests, records the previous
image, deploys, and runs live smoke checks. Pushing to Git alone does not update
the deployed database. Follow [RELEASE.md](RELEASE.md) for release order,
rollback commands, and backup settings; off-laptop backup mirroring is currently
paused.

The backend Fly app is `backend-winter-smoke-307`, configured in
`backend/fly.toml`. `/healthz` checks liveness; `/readyz` reports schema, question
counts, image availability, API-key presence, and ELA status.

Environment settings include `FIREWORKS_API_KEY`, `SET_TOKEN_SECRET`,
`ELA_ENABLED` (default off), `WITHDRAWN_STIMULI`, and `LLM_DAILY_CAP` (default
2,000 calls/day). Per-IP rate limits and the daily budget are held in memory
and reset on restart. The deployment uses one worker and one always-on machine;
move counters to shared storage before scaling. See [RELEASE.md](RELEASE.md)
for production secret configuration and ELA launch checks.
