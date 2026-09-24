"""Live Fireworks/backend smoke test (uses API credits).

Run from the repository root: backend/venv/bin/python scripts/test_query_model.py
Uses a temporary database copy; does not change saved sessions or questions.
"""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / "backend/.env")
sys.path.insert(0, str(ROOT / "backend"))
import db
import llm_client


def main():
    with tempfile.TemporaryDirectory() as directory:
        with sqlite3.connect(db.DB_PATH) as source:
            with sqlite3.connect(Path(directory) / "test.db") as target:
                source.backup(target)
        db.DB_PATH = str(Path(directory) / "test.db")
        from app import app

        client = app.test_client()
        real_parser = llm_client.parse_query_with_ollama
        real_post = llm_client.session.post
        outputs = []

        def checked_post(*args, **kwargs):
            response = real_post(*args, **kwargs)
            response.raise_for_status()
            choice = response.json()["choices"][0]
            assert choice["finish_reason"] == "stop", choice
            payload = json.loads(choice["message"]["content"])
            assert set(payload) == {"intent", "subject", "topic", "type", "limit", "reply"}
            outputs.append(payload)
            return response

        cases = [
            ("Give me 3 Algebra I MCQs on Systems of Equations",
             ("generate", "Algebra I", "Systems of Equations", "MCQ", 3)),
            ("Give me 2 more", ("generate", "Algebra I", "Systems of Equations", "MCQ", 2)),
            ("Now do short answer instead", ("generate", "Algebra I", "Systems of Equations", "CRQ", 2)),
            ("How many of those are there?", ("count_questions", "Algebra I", "Systems of Equations", "CRQ", 0)),
            ("List Geometry topics", ("list_topics", "Geometry", "", "", 0)),
            ("Give me five Algebra II MCQs on Complex Numbers",
             ("generate", "Algebra II", "Complex Numbers", "MCQ", 5)),
            ("Hi! What can you do?", ("chitchat", "", "", "", 0)),
        ]
        seen = set()
        for query, expected in cases:
            def checked_parser(text, last_query):
                actual = real_parser(text, last_query)
                assert actual[:5] == expected, (query, actual, expected)
                assert actual[5], "Missing conversational reply"
                return actual

            started = time.monotonic()
            before = len(outputs)
            with patch("app.parse_query_with_ollama", checked_parser), patch.object(llm_client.session, "post", checked_post):
                response = client.post("/api/query", json={"query": query, "session_id": "model-smoke-test"})
            assert response.status_code == 200, response.status_code
            assert len(outputs) == before + 1, "No successful model response"
            body = response.get_json()
            assert body["response"]
            if expected[0] == "generate":
                questions = body["questions"]
                assert len(questions) == expected[4]
                for question in questions:
                    assert (question["subject"], question["topic"], question["type"]) == expected[1:4]
                    assert question["id"] not in seen, "Repeated question"
                    seen.add(question["id"])
            elif expected[0] == "count_questions":
                assert f"<b>{db.count_questions(*expected[1:4])}</b>" in body["response"]
            elif expected[0] == "list_topics":
                assert "<li>" in body["response"]
            print(f"PASS ({time.monotonic() - started:.1f}s): {query}")
        print(f"All {len(cases)} live backend checks passed using {llm_client.FIREWORKS_MODEL}")


if __name__ == "__main__":
    main()
