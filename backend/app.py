from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import json
import random
from datetime import datetime
import os

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend requests

DATABASE = 'regentsqs.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    conn = get_db_connection()

    # Questions database
    conn.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT NOT NULL,
            topic TEXT NOT NULL,
            year INTEGER NOT NULL,
            type TEXT NOT NULL,
            question_text TEXT NOT NULL,
            choices TEXT NOT NULL,  -- JSON string of choices
            correct_answer INTEGER NOT NULL,
            explanation TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

if __name__ == '__main__':
    # Initialize database on first run
    if not os.path.exists(DATABASE):
        print("Creating database...")
        init_database()