
import os
import re
import json
import sqlite3
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None


# ==================================================
# 1. APP CONFIGURATION
# ==================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "change-this-secret-key-before-deployment"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

DB_PATH = os.path.join(DATABASE_DIR, "resume_analyzer.db")

os.makedirs(DATABASE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf"}
MAX_FILE_SIZE = 5 * 1024 * 1024

SKILLS = [
    "python", "java", "javascript", "html", "css",
    "php", "mysql", "sql", "flask", "django",
    "react", "node.js", "c", "c++", "git", "github",
    "machine learning", "artificial intelligence",
    "data analysis", "power bi", "excel",
    "communication", "teamwork", "problem solving",
    "rest api", "mongodb", "linux", "cloud computing"
]


# ==================================================
# 2. DATABASE
# ==================================================

def get_db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = get_db()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            job_title TEXT NOT NULL,
            match_score INTEGER NOT NULL,
            matched_skills TEXT NOT NULL,
            missing_skills TEXT NOT NULL,
            suggestions TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    connection.commit()
    connection.close()


init_db()


# ==================================================
# 3. LOGIN PROTECTION
# ==================================================

def login_required(view_function):
    @wraps(view_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))

        return view_function(*args, **kwargs)

    return wrapper


# ==================================================
# 4. HELPER FUNCTIONS
# ==================================================

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def extract_pdf_text(file_path):
    if PdfReader is None:
        raise RuntimeError(
            "PyPDF2 is missing. Run: python -m pip install PyPDF2"
        )

    reader = PdfReader(file_path)

    text = []
    for page in reader.pages:
        text.append(page.extract_text() or "")

    return "\n".join(text).strip()


def find_skills(text):
    text = text.lower()
    found = []

    for skill in SKILLS:
        pattern = r"(?<!\w)" + re.escape(skill) + r"(?!\w)"

        if re.search(pattern, text):
            found.append(skill.title())

    return found


def analyze_resume(resume_text, job_description):
    resume_skills = find_skills(resume_text)
    required_skills = find_skills(job_description)

    resume_lower = {skill.lower() for skill in resume_skills}

    matched_skills = [
        skill for skill in required_skills
        if skill.lower() in resume_lower
    ]

    missing_skills = [
        skill for skill in required_skills
        if skill.lower() not in resume_lower
    ]

    if required_skills:
        score = round(
            len(matched_skills) / len(required_skills) * 100
        )
    else:
        score = 0

    suggestions = []

    if missing_skills:
        suggestions.append(
            "Consider learning or highlighting: "
            + ", ".join(missing_skills) + "."
        )

    if not resume_skills:
        suggestions.append(
            "Add relevant technical skills to your resume."
        )

    if len(resume_text.split()) < 100:
        suggestions.append(
            "Include more details about education, projects, "
            "experience and achievements."
        )

    if not suggestions:
        suggestions.append(
            "Good match! Highlight relevant projects and measurable "
            "achievements for this role."
        )

    return score, matched_skills, missing_skills, suggestions


def get_user_results(user_id):
    connection = get_db()

    rows = connection.execute("""
        SELECT id, job_title, match_score, created_at,
               matched_skills, missing_skills, suggestions
        FROM results
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    connection.close()

    results = []

    for row in rows:
        item = dict(row)

        # Convert saved JSON data back into Python lists.
        for key in ("matched_skills", "missing_skills", "suggestions"):
            try:
                item[key] = json.loads(item[key])
            except (TypeError, json.JSONDecodeError):
                item[key] = []

        results.append(item)

    return results


# ==================================================
# 5. HOME PAGE
# ==================================================

@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if os.path.exists(os.path.join(BASE_DIR, "templates", "index.html")):
        return render_template("index.html")

    if os.path.exists(os.path.join(BASE_DIR, "templates", "home.html")):
        return render_template("home.html")

    return redirect(url_for("login"))


# ==================================================
# 6. REGISTER
# ==================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "error")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)

        connection = get_db()

        try:
            connection.execute("""
                INSERT INTO users (name, email, password)
                VALUES (?, ?, ?)
            """, (name, email, hashed_password))

            connection.commit()

        except sqlite3.IntegrityError:
            flash("This email is already registered.", "error")
            return render_template("register.html")

        finally:
            connection.close()

        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ==================================================
# 7. LOGIN
# ==================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        connection = get_db()

        user = connection.execute("""
            SELECT id, name, email, password
            FROM users
            WHERE email = ?
        """, (email,)).fetchone()

        connection.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]

            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "error")

    return render_template("login.html")


# ==================================================
# 8. DASHBOARD - GLASSMORPHISM TEMPLATE DATA
# ==================================================

@app.route("/dashboard")
@login_required
def dashboard():
    # Get the logged-in user's analysis history.
    results = get_user_results(session["user_id"])

    # Pass results and user details into dashboard.html.
    return render_template(
        "dashboard.html",
        results=results,
        user_name=session.get("user_name", "User"),
        name=session.get("user_name", "User"),
        total_results=len(results)
    )


# ==================================================
# 9. UPLOAD AND ANALYZE RESUME
# ==================================================

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        resume = request.files.get("resume")
        job_description = request.form.get(
            "job_description", ""
        ).strip()

        if not resume or not resume.filename:
            flash("Please select your resume PDF.", "error")
            return render_template("upload.html")

        if not allowed_file(resume.filename):
            flash("Only PDF files are supported.", "error")
            return render_template("upload.html")

        if not job_description:
            flash("Please enter a job description.", "error")
            return render_template("upload.html")

        resume.stream.seek(0, os.SEEK_END)
        file_size = resume.stream.tell()
        resume.stream.seek(0)

        if file_size > MAX_FILE_SIZE:
            flash("Your resume must be smaller than 5 MB.", "error")
            return render_template("upload.html")

        filename = secure_filename(resume.filename)
        temporary_path = os.path.join(UPLOAD_DIR, filename)

        try:
            resume.save(temporary_path)

            resume_text = extract_pdf_text(temporary_path)

            if not resume_text:
                flash(
                    "No readable text found. Please upload a text-based PDF.",
                    "error"
                )
                return render_template("upload.html")

            score, matched_skills, missing_skills, suggestions = (
                analyze_resume(resume_text, job_description)
            )

            job_title = next(
                (
                    line.strip()
                    for line in job_description.splitlines()
                    if line.strip()
                ),
                "Resume Analysis"
            )[:100]

            connection = get_db()

            connection.execute("""
                INSERT INTO results (
                    user_id, job_title, match_score,
                    matched_skills, missing_skills,
                    suggestions, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                session["user_id"],
                job_title,
                score,
                json.dumps(matched_skills),
                json.dumps(missing_skills),
                json.dumps(suggestions),
                datetime.now().strftime("%d %b %Y, %I:%M %p")
            ))

            connection.commit()
            connection.close()

            return render_template(
                "results.html",
                score=score,
                match_score=score,
                matched_skills=matched_skills,
                missing_skills=missing_skills,
                suggestions=suggestions,
                job_title=job_title
            )

        except Exception as error:
            app.logger.exception("Resume analysis failed")

            if isinstance(error, RuntimeError):
                message = str(error)
            else:
                message = (
                    "Unable to analyze this PDF. Try another "
                    "text-based PDF and check the terminal if it continues."
                )

            flash(message, "error")
            return render_template("upload.html")

        finally:
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    app.logger.warning("Could not remove temporary PDF.")

    return render_template("upload.html")


# ==================================================
# 10. HISTORY
# ==================================================

@app.route("/history")
@login_required
def history():
    results = get_user_results(session["user_id"])

    return render_template(
        "history.html",
        results=results,
        user_name=session.get("user_name", "User")
    )


# ==================================================
# 11. LOGOUT
# ==================================================

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ==================================================
# 12. START FLASK
# ==================================================

if __name__ == "__main__":
    app.run(debug=True)
