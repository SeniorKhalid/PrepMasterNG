from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import random
import copy
import sqlite3
import os
from questions import subjects
# expects a dict like { "Math": [ { "question": "...", "options": [...], "answer": "..." }, ... ] }

DB_FILE = "leaderboard.db"
MAX_QUESTIONS = 20  # absolute cap per quiz


# ---------------------------
# Database utilities
# ---------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS leaderboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            subject TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            percentage REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def add_score(name, subject, score, total):
    percentage = round((score / total) * 100, 2)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO leaderboard (name, subject, score, total, percentage)
        VALUES (?, ?, ?, ?, ?)
    """, (name, subject, score, total, percentage))
    conn.commit()
    conn.close()


def get_leaderboard(subject=None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if subject:
        c.execute("""
            SELECT name, subject, score, total, percentage
            FROM leaderboard
            WHERE subject = ?
            ORDER BY percentage DESC, created_at ASC
        """, (subject,))
    else:
        c.execute("""
            SELECT name, subject, score, total, percentage
            FROM leaderboard
            ORDER BY percentage DESC, created_at ASC
        """)
    rows = c.fetchall()
    conn.close()
    return [
        {
            "name": r[0],
            "subject": r[1],
            "score": r[2],
            "total": r[3],
            "percentage": r[4]
        }
        for r in rows
    ]


# ---------------------------
# Flask app
# ---------------------------
app = Flask(__name__, template_folder='templates')
CORS(app)  # Allow browser requests

# In-memory quiz sessions
sessions = {}


@app.route("/")
def home():
    return render_template


@app.route("/subjects", methods=["GET"])
def list_subjects():
    return jsonify({"subjects": list(subjects.keys())})


@app.route("/start_quiz", methods=["POST"])
def start_quiz():
    data = request.get_json(force=True)
    subject = data.get("subject")
    name = data.get("name")
    requested = int(data.get("num_questions", 10))

    if not name or not subject:
        return jsonify({"error": "Missing 'name' or 'subject'"}), 400

    if subject not in subjects or not subjects[subject]:
        return jsonify({"error": "Invalid or empty subject"}), 400

    # Copy and shuffle questions
    questions = copy.deepcopy(subjects[subject])
    random.shuffle(questions)

    # Limit to requested number, but not more than MAX_QUESTIONS
    questions = questions[:min(requested, MAX_QUESTIONS)]

    # Shuffle options for each question
    for q in questions:
        random.shuffle(q["options"])

    sessions[name] = {
        "subject": subject,
        "questions": questions,
        "score": 0,
        "current_index": 0
    }

    return jsonify({
        "message": f"Quiz started for {name} on {subject}",
        "total_questions": len(questions),
        "first_question": questions[0]
    })


@app.route("/answer", methods=["POST"])
def answer():
    data = request.get_json(force=True)
    name = data.get("name")
    choice = data.get("choice")

    if not name:
        return jsonify({"error": "Missing 'name'"}), 400

    session = sessions.get(name)
    if not session:
        return jsonify({"error": "No active quiz for this user"}), 400

    idx = session["current_index"]
    if idx >= len(session["questions"]):
        return jsonify({"message": "Quiz already finished"}), 200

    question = session["questions"][idx]
    correct = (choice == question["answer"])
    if correct:
        session["score"] += 1

    session["current_index"] += 1

    # If finished
    if session["current_index"] >= len(session["questions"]):
        add_score(name, session["subject"], session["score"], len(session["questions"]))
        sessions.pop(name, None)  # cleanup
        return jsonify({
            "correct": correct,
            "correct_answer": question["answer"],
            "next_question": None,
            "score": session["score"]
        })

    # Otherwise send next question
    next_q = session["questions"][session["current_index"]]
    random.shuffle(next_q["options"])
    return jsonify({
        "correct": correct,
        "correct_answer": question["answer"],
        "next_question": next_q,
        "score": session["score"]
    })


@app.route("/leaderboard", methods=["GET"])
def leaderboard():
    board = get_leaderboard()
    return jsonify(board)


@app.route("/leaderboard/<subject>", methods=["GET"])
def leaderboard_by_subject(subject):
    board = get_leaderboard(subject=subject)
    return jsonify(board)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
