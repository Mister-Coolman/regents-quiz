import os
import sqlite3

# Path settings
DB_PATH = "backend/regentsqs.db"
IMAGES_DIR = "images/mcqQuestionBlock"

# 1. Get all image paths from the database
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT question_image_path FROM questions")
db_paths = set(row[0] for row in cursor.fetchall())
conn.close()

# 2. Get all files from the images directory
all_files = []
for root, _, files in os.walk(IMAGES_DIR):
    for f in files:
        full_path = os.path.join(root, f)
        rel_path = os.path.relpath(full_path, ".")  # match DB format
        all_files.append(rel_path)

print(all_files)
# 3. Delete files not in DB
deleted = 0
for file_path in all_files:
    if file_path not in db_paths:
        os.remove(file_path)
        print(f"Deleted: {file_path}")
        deleted += 1

print(f"✅ Done. Deleted {deleted} unused images.")