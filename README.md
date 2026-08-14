# NY State Regents Prep AI

A web app for practicing NY State Regents exams with real, past exam questions
and AI-generated explanations. Users can browse by subject/topic, download
practice sets as PDFs, and work through questions in an interactive quiz mode
with progressive hints and worked explanations.

Live at **https://nystateregentsprep.netlify.app/**

## Features

- Real Regents exam questions pulled from official exam PDFs, with question
  images cropped out of the source PDFs
- AI-generated explanations (via Fireworks AI, Qwen3.7 Plus) for each
  question, broken into "What's being asked," "Approach," "Work," and "Answer"
- Interactive quiz mode:
  - Progressive hints, unlocked one at a time from the explanation, so a
    student can get unstuck without seeing the full solution
  - Answer checking with an explanation panel that opens automatically on a
    miss and stays collapsed on a correct answer
  - Progress (question index, results, hints used) saved to the browser's
    localStorage, so closing and reopening a quiz resumes where you left off
  - A review screen at the end listing every missed question with its
    explanation
  - Confetti on a perfect score
- Math rendered with KaTeX (via `react-markdown` + `remark-math` +
  `rehype-katex`), so explanations with equations render properly
- PDF export of a practice set
- Natural-language query parsing (e.g. "10 easy algebra questions from
  2019") backed by Fireworks AI, used to build a practice set from a
  free-text request

## Architecture

- **Backend** — Flask + SQLite, deployed on Fly.io. Serves questions,
  explanations, and question images from `regentsqs.db`, and proxies
  natural-language quiz requests to Fireworks AI for parsing. The database
  is not committed to git — it ships as part of the Docker image on
  `fly deploy`.
- **Frontend** — React + Vite, deployed on Netlify with auto-deploy on push
  to `main`.
- **Data pipeline** (`scripts/`) — offline, run manually, not part of the
  deployed app:
  - Downloads official exam PDFs and rating guides
  - Crops question images out of the source PDFs (PyMuPDF-based exact-match
    recropping, plus a `recrop_broken.py` pass to fix images cut off in the
    initial extraction)
  - Generates explanations for each question via Fireworks AI and writes
    them back into the database (`fireworks_explanations.py`,
    `generate_explanations.py`)
  - `extract_topics.py`, `run_pipeline.py`, and `image2latex_test.py` are an
    earlier, YOLO/OCR-based extraction pipeline (`ultralytics`, `surya`,
    `pdfplumber`, `pandas`) that predates the current PyMuPDF-based
    recropping approach. They're left in the repo for reference but are not
    part of the maintained pipeline and their dependencies are not included
    in `scripts/requirements.txt` below.

## Getting started

### Backend

```bash
cd backend
pip install -r requirements.txt
# create a .env with FIREWORKS_API_KEY and any other secrets llm_client.py expects
python app.py
```

### Frontend

```bash
cd frontend
npm install
# set VITE_API_BASE_URL in frontend/.env to point at your backend
npm run dev
```

`frontend/requirements.txt` mirrors `package.json`'s dependencies in
pip-style format for reference; `package.json` is the actual manifest and
what `npm install` reads.

### Data pipeline scripts

The scripts in `scripts/` that are actually run day-to-day
(`fireworks_explanations.py`, `recrop_broken.py`, `download_exams.py`,
`download_rating_guides.py`, `backfill_crq_rubrics.py`,
`generate_explanations.py`, `vlm_utils.py`) need:

```bash
pip install requests python-dotenv Pillow PyMuPDF numpy
```

## Deployment

### Frontend (Vite + React)

Hosted on **Netlify**, auto-deployed from `main`.
https://nystateregentsprep.netlify.app/

### Backend (Flask + SQLite)

Hosted on **Fly.io** (`fly.toml`, app `backend-winter-smoke-307`).
Deploy with:

```bash
cd backend
fly deploy
```

The SQLite database ships inside the built image — pushing to git alone does
not update the deployed data; you need to `fly deploy` after any local
database change.
