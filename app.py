from flask import Flask, request, jsonify, render_template, redirect, url_for, session
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from questions import subjects
import random
import os
from dotenv import load_dotenv
from datetime import timedelta

# Load .env file
load_dotenv()

app = Flask(__name__)
DB_FILE = "leaderboard.db"

# ✅ Use environment variables
app.secret_key = os.environ.get("SECRET_KEY", "fallback-secret")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "fallback-password")

# ✅ Set session lifetime
app.permanent_session_lifetime = timedelta(days=7)

@app.before_request
def make_session_permanent():
    session.permanent = True

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
    username = request.args.get("username")
    return render_template("index.html", username=username)

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

    available_questions = subjects[subject]
    num_questions = min(requested, len(available_questions))
    questions = random.sample(available_questions, k=num_questions)

    if not questions:
        return jsonify({"error": "No questions available"}), 404

    session["quiz_state"] = {
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

    state = session.get("quiz_state")
    if not state:
        return jsonify({"error": "No quiz in progress"}), 400

    index = state["index"]
    question = state["questions"][index]

    correct = (choice == question["answer"])
    if correct:
        state["score"] += 1

    state["index"] += 1
    next_q = state["questions"][state["index"]] if state["index"] < len(state["questions"]) else None
    session["quiz_state"] = state

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
        session.pop("quiz_state", None)

    return jsonify({
        "correct": correct,
        "correct_answer": question["answer"],
        "next_question": next_q
    })

# 🏆 Global leaderboard
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
    return jsonify([{"name": r[0], "score": r[1]} for r in rows])

# 🧠 Subject leaderboard
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
        session["username"] = username
        return jsonify({"message": "Login successful"})
    else:
        return jsonify({"error": "Invalid credentials"}), 401

# 📊 User Dashboard
@app.route("/dashboard/<username>")
def dashboard(username):
    if session.get("username") != username:
        return redirect(url_for("auth_page"))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE username = ?", (username,))
    if not c.fetchone():
        conn.close()
        return redirect(url_for("auth_page"))

    c.execute("""
        SELECT name, SUM(score) AS total_score
        FROM leaderboard
        GROUP BY name
        ORDER BY total_score DESC
    """)
    all_scores = c.fetchall()
    rank = next((i + 1 for i, row in enumerate(all_scores) if row[0] == username), None)
    user_total = next((row[1] for row in all_scores if row[0] == username), 0)

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

# 🔐 Logout
@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("auth_page"))

# 🔑 Admin login
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_users"))
        else:
            return render_template("admin_login.html", error="Invalid password")
    return render_template("admin_login.html")

# 👥 Admin: View users + leaderboard
@app.route("/admin/users")
def admin_users():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    search = request.args.get("search", "").strip()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    if search:
        c.execute("SELECT id, username FROM users WHERE username LIKE ? ORDER BY id DESC", (f"%{search}%",))
    else:
        c.execute("SELECT id, username FROM users ORDER BY id DESC")
    users = c.fetchall()

    # Leaderboard
    c.execute("""
        SELECT name, subject, score, total, percentage, created_at
        FROM leaderboard
        ORDER BY created_at DESC
        LIMIT 20
    """)
    leaderboard = c.fetchall()

    conn.close()
    return render_template("admin_users.html", users=users, search=search, leaderboard=leaderboard)
# 🗑️ Delete a user by ID
@app.route("/admin/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "User deleted successfully"})

# 🧹 Clear leaderboard (protected)
@app.route("/admin/clear_leaderboard", methods=["POST"])
def clear_leaderboard():
    if not session.get("is_admin"):
        return redirect(url_for("admin_login"))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM leaderboard")
    conn.commit()
    conn.close()
    return jsonify({"message": "Leaderboard cleared"})

# 🔓 Admin logout
@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("auth_page"))

# 🚀 Run app
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
