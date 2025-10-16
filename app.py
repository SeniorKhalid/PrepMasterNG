from flask import Flask, request, jsonify, render_template
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from questions import subjects

app = Flask(__name__)
DB_FILE = "leaderboard.db"

# 🔧 Initialize database
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

init_db()

# 🏠 Home page
@app.route("/")
def home():
    return render_template("index.html")

# 🔐 Auth page
@app.route("/auth")
def auth_page():
    return render_template("auth.html")

# 📚 Get subjects
@app.route("/subjects")
def get_subjects():
    return jsonify({"subjects": list(subjects.keys())})

# 🚀 Start quiz
@app.route("/start_quiz", methods=["POST"])
def start_quiz():
    data = request.get_json(force=True)
    subject = data.get("subject", "").strip().title()
    name = data.get("name")
    requested = int(data.get("num_questions", 10))

    if not name or not subject:
        return jsonify({"error": "Missing 'name' or 'subject'"}), 400

    if subject not in subjects or not subjects[subject]:
        return jsonify({"error": "Invalid or empty subject"}), 400

    questions = subjects[subject][:requested]
    if not questions:
        return jsonify({"error": "No questions available"}), 404

    app.quiz_state = {
        "name": name,
        "subject": subject,
        "questions": questions,
        "index": 0,
        "score": 0
    }

    return jsonify({
        "first_question": questions[0],
        "total_questions": len(questions)
    })

# ✅ Submit answer
@app.route("/answer", methods=["POST"])
def submit_answer():
    data = request.get_json(force=True)
    choice = data.get("choice")
    state = app.quiz_state
    index = state["index"]
    question = state["questions"][index]

    correct = (choice == question["answer"])
    if correct:
        state["score"] += 1

    state["index"] += 1
    next_q = state["questions"][state["index"]] if state["index"] < len(state["questions"]) else None

    if not next_q:
        percentage = (state["score"] / len(state["questions"])) * 100
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("""
            INSERT INTO leaderboard (name, subject, score, total, percentage)
            VALUES (?, ?, ?, ?, ?)
        """, (state["name"], state["subject"], state["score"], len(state["questions"]), percentage))
        conn.commit()
        conn.close()

    return jsonify({
        "correct": correct,
        "correct_answer": question["answer"],
        "next_question": next_q
    })

# 🏆 Global leaderboard (by total points)
@app.route("/leaderboard")
def leaderboard_global():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT name, SUM(score) AS total_score
        FROM leaderboard
        GROUP BY name
        ORDER BY total_score DESC
        LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    return jsonify([{
        "name": r[0],
        "score": r[1]
    } for r in rows])

# 🧠 Subject leaderboard (individual attempts)
@app.route("/leaderboard/<subject>")
def leaderboard_subject(subject):
    subject = subject.strip().title()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT name, score, total, percentage
        FROM leaderboard
        WHERE subject = ?
        ORDER BY percentage DESC
        LIMIT 10
    """, (subject,))
    rows = c.fetchall()
    conn.close()
    return jsonify([{
        "name": r[0], "score": r[1], "total": r[2], "percentage": round(r[3], 2)
    } for r in rows])

# 🧹 Clear leaderboard
@app.route("/clear_leaderboard", methods=["POST"])
def clear_leaderboard():
    data = request.get_json(force=True)
    password = data.get("password")
    if password != "admin123":
        return jsonify({"error": "Invalid admin password"}), 403

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM leaderboard")
    conn.commit()
    conn.close()
    return jsonify({"message": "Leaderboard cleared"})

# 🔐 Register
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(force=True)
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    hashed = generate_password_hash(password)
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed))
        conn.commit()
        conn.close()
        return jsonify({"message": "User registered successfully"})
    except sqlite3.IntegrityError:
        return jsonify({"error": f"Username '{username}' is already taken"}), 409
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)}"}), 500

# 🔐 Login
@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = data.get("username")
    password = data.get("password")

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()

    if row and check_password_hash(row[0], password):
        return jsonify({"message": "Login successful"})
    else:
        return jsonify({"error": "Invalid credentials"}), 401

# 📊 User Dashboard
@app.route("/dashboard/<username>")
def dashboard(username):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Get all users' total scores
    c.execute("""
        SELECT name, SUM(score) AS total_score
        FROM leaderboard
        GROUP BY name
        ORDER BY total_score DESC
    """)
    all_scores = c.fetchall()

    # Find the user's rank
    rank = next((i + 1 for i, row in enumerate(all_scores) if row[0] == username), None)
    user_total = next((row[1] for row in all_scores if row[0] == username), 0)

    # Get user's quiz history
    c.execute("""
        SELECT subject, score, total, percentage, created_at
        FROM leaderboard
        WHERE name = ?
        ORDER BY created_at DESC
    """, (username,))
    history = c.fetchall()
    conn.close()

    return render_template("dashboard.html",
                           username=username,
                           history=[{
                               "subject": r[0],
                               "score": r[1],
                               "total": r[2],
                               "percentage": r[3],
                               "created_at": r[4]
                           } for r in history],
                           rank=rank,
                           total_score=user_total
                           )

# 🚀 Run app
if __name__ == "__main__":
    app.run(debug=True)
