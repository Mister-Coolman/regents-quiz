# classify_with_ollama.py
import sqlite3
import ollama

MODEL_NAME = "mistral"

def build_prompt(latex, question_text=None):
    base = f"""
Classify this Algebra I Regents exam question by topic.

Equation (LaTeX): {latex}

{f"Context: {question_text}" if question_text else ""}

Respond with only the topic in 2-4 words like:
Factoring, Linear Functions, Quadratics, Sequences, Graphing, Inequalities, etc.
"""
    return base.strip()

def classify_questions(db_path="questions.db"):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT id, math_latex, question_text FROM questions WHERE topic IS NULL OR topic = ''")
    rows = cursor.fetchall()

    for qid, latex, text in rows:
        prompt = build_prompt(latex, text)
        try:
            response = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt}])
            topic = response['message']['content'].strip()
            print(f"[{qid}] {topic}")
            cursor.execute("UPDATE questions SET topic = ? WHERE id = ?", (topic, qid))
            conn.commit()
        except Exception as e:
            print(f"Error classifying {qid}: {e}")

    conn.close()
