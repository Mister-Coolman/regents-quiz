import sqlite3

DB_PATH = "../backend/regentsqs.db"

def view_questions():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT id, subject, topic, year, type, question_image_path, correct_answer FROM questions")
    rows = cursor.fetchall()
    for row in rows:
        print(f"ID: {row[0]}, Subject: {row[1]}, Topic: {row[2]}, Year: {row[3]}, Type: {row[4]}")
        print(f"Image: {row[5]}, Answer: {row[6]}")
        print("-" * 60)

    conn.close()

if __name__ == "__main__":
    view_questions()
