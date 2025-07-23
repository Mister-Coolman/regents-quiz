import sqlite3

conn = sqlite3.connect("questions.db")
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print(cursor.fetchall())

# Show first 5 rows of questions
cursor.execute("SELECT * FROM questions LIMIT 5;")
print(cursor.fetchall())

conn.close()