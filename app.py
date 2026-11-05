import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path
from flask import (
    Flask, render_template_string, request, redirect, 
    url_for, flash, session
)
from werkzeug.security import generate_password_hash, check_password_hash

# PostgreSQL support check
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app = Flask(__name__)
app.secret_key = "farmconnect-super-secret-key-change-in-production"
DB_PATH = Path(__file__).with_name("farmconnect.db")

# ------------------------------------------------------------------------------
# DATABASE CONNECTION HELPER (Supports both SQLite & PostgreSQL)
# ------------------------------------------------------------------------------
class DictRow(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
    def __setattr__(self, key, value):
        self[key] = value

class DatabaseConnection:
    def __init__(self):
        if DATABASE_URL:
            self.conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
            self.is_pg = True
        else:
            self.conn = sqlite3.connect(DB_PATH)
            self.conn.row_factory = sqlite3.Row
            self.is_pg = False
        self.cursor = self.conn.cursor()

    def execute(self, query, params=None):
        if self.is_pg:
            query = query.replace('?', '%s')
        if params:
            self.cursor.execute(query, params)
        else:
            self.cursor.execute(query)
        return self

    def fetchone(self):
        res = self.cursor.fetchone()
        if res and not self.is_pg:
            return res
        elif res and self.is_pg:
            return DictRow(res)
        return None

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not self.is_pg:
            return rows
        return [DictRow(r) for r in rows]

    @property
    def lastrowid(self):
        if self.is_pg:
            try:
                self.cursor.execute("SELECT lastval()")
                return self.cursor.fetchone()[0]
            except Exception:
                return None
        else:
            return self.cursor.lastrowid

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.cursor.close()
        self.conn.close()

def db():
    return DatabaseConnection()

# ------------------------------------------------------------------------------
# DATABASE SETUP & MIGRATION
# ------------------------------------------------------------------------------
def init_db():
    with db() as con:
        if DATABASE_URL:
            con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'visitor',
                created_at TEXT NOT NULL
            )""")
        else:
            con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'visitor',
                created_at TEXT NOT NULL
            )""")

        if DATABASE_URL:
            con.execute("""
            CREATE TABLE IF NOT EXISTS farmers (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                village TEXT NOT NULL,
                district TEXT NOT NULL,
                crops TEXT NOT NULL,
                experience INTEGER DEFAULT 0,
                fee REAL DEFAULT 0,
                bio TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )""")
        else:
            con.execute("""
            CREATE TABLE IF NOT EXISTS farmers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                village TEXT NOT NULL,
                district TEXT NOT NULL,
                crops TEXT NOT NULL,
                experience INTEGER DEFAULT 0,
                fee REAL DEFAULT 0,
                bio TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )""")

        if DATABASE_URL:
            con.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id SERIAL PRIMARY KEY,
                farmer_id INTEGER NOT NULL REFERENCES farmers(id) ON DELETE CASCADE,
                visitor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                visitor_name TEXT NOT NULL,
                visitor_phone TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                message TEXT DEFAULT '',
                payment_status TEXT DEFAULT 'Pay on visit',
                status TEXT DEFAULT 'Pending',
                created_at TEXT NOT NULL
            )""")
        else:
            con.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                farmer_id INTEGER NOT NULL,
                visitor_id INTEGER,
                visitor_name TEXT NOT NULL,
                visitor_phone TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                message TEXT DEFAULT '',
                payment_status TEXT DEFAULT 'Pay on visit',
                status TEXT DEFAULT 'Pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY(farmer_id) REFERENCES farmers(id) ON DELETE CASCADE,
                FOREIGN KEY(visitor_id) REFERENCES users(id) ON DELETE SET NULL
            )""")

        if DATABASE_URL:
            con.execute("""
            CREATE TABLE IF NOT EXISTS crop_guides (
                id SERIAL PRIMARY KEY,
                crop TEXT NOT NULL,
                topic TEXT NOT NULL,
                guidance TEXT NOT NULL
            )""")
        else:
            con.execute("""
            CREATE TABLE IF NOT EXISTS crop_guides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                crop TEXT NOT NULL,
                topic TEXT NOT NULL,
                guidance TEXT NOT NULL
            )""")

        count_res = con.execute("SELECT COUNT(*) AS n FROM crop_guides").fetchone()
        count = count_res["n"] if count_res else 0
        if count == 0:
            guides = [
                ("Tomato", "General Care & Disease Management", "Use certified seedlings, maintain 60x45cm spacing, install drip irrigation to avoid leaf wetness, and apply Neem oil preventive spray for leaf miners."),
                ("Cotton", "Nutrient & Pest Control", "Apply balanced NPK according to soil testing. Monitor regularly for sucking pests (Thrips, Aphids) and set up pheromone traps for pink bollworm."),
                ("Onion", "Irrigation & Harvest Care", "Provide light, frequent irrigation during bulb development. Stop watering 10-15 days before harvesting for better shelf life and storage quality."),
                ("Wheat", "Sowing & Fertilizer Management", "Sow during mid-November using certified rust-resistant varieties. Ensure timely first irrigation at Crown Root Initiation (CRI) stage (20-25 days)."),
                ("Soybean", "Drainage & Weed Control", "Ensure broadbed-furrow system for proper field drainage during heavy rains. Use pre-emergence herbicides within 48 hours of sowing.")
            ]
            for g in guides:
                con.execute("INSERT INTO crop_guides(crop,topic,guidance) VALUES(?,?,?)", g)

        admin = con.execute("SELECT * FROM users WHERE role='admin'").fetchone()
        if not admin:
            admin_pw = generate_password_hash("admin123")
            con.execute("""
                INSERT INTO users (name, email, phone, password, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("System Admin", "admin@farmconnect.com", "9999999999", admin_pw, "admin", datetime.now().isoformat(timespec="minutes")))

init_db()

# ------------------------------------------------------------------------------
# AUTH DECORATORS
# ------------------------------------------------------------------------------
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("कृपया पुढे जाण्यासाठी लॉगिन करा.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('role') not in roles:
                flash("तुम्हाला या पेजवर जाण्याची परवानगी नाही.", "danger")
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ------------------------------------------------------------------------------
# BASE HTML LAYOUT TEMPLATE & RENDER HELPER
# ------------------------------------------------------------------------------
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="mr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FarmConnect - Agri Agritourism Platform</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --primary-green: #1b4d3e;
            --accent-green: #2e7d32;
            --light-green: #e8f5e9;
            --mint-bg: #f4f9f5;
            --dark-emerald: #0c231c;
            --gold-accent: #fbc02d;
        }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--mint-bg);
            color: #2c3e50;
            display: flex;
            flex-direction: column;
            min-height: 100vh;
        }
        .navbar-custom {
            background: rgba(27, 77, 62, 0.95);
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        .brand-logo {
            font-weight: 800;
            font-size: 1.5rem;
            color: #ffffff !important;
            letter-spacing: -0.5px;
        }
        .brand-logo span { color: var(--gold-accent); }
        .nav-link {
            color: rgba(255,255,255,0.85) !important;
            font-weight: 500;
            transition: all 0.3s ease;
        }
        .nav-link:hover {
            color: var(--gold-accent) !important;
            transform: translateY(-1px);
        }
        .btn-agri-primary {
            background: linear-gradient(135deg, var(--accent-green), var(--primary-green));
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            padding: 10px 24px;
            box-shadow: 0 4px 12px rgba(46, 125, 50, 0.25);
            transition: all 0.3s ease;
        }
        .btn-agri-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 18px rgba(46, 125, 50, 0.35);
            color: white;
        }
        .card-custom {
            border: none;
            border-radius: 16px;
            background: #ffffff;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.05);
            transition: all 0.3s ease;
        }
        .card-custom:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
        }
        .hero-section {
            background: linear-gradient(135deg, rgba(12, 35, 28, 0.88), rgba(27, 77, 62, 0.85)), url('https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=1600&q=80') center/cover;
            color: white;
            padding: 100px 0 80px 0;
            border-radius: 0 0 30px 30px;
        }
        .footer-custom {
            background: var(--dark-emerald);
            color: rgba(255,255,255,0.7);
            margin-top: auto;
            padding: 40px 0 20px 0;
        }
        .badge-agri {
            background-color: var(--light-green);
            color: var(--accent-green);
            font-weight: 600;
            padding: 6px 12px;
            border-radius: 20px;
        }
    </style>
</head>
<body>

    <nav class="navbar navbar-expand-lg navbar-dark navbar-custom sticky-top">
        <div class="container">
            <a class="navbar-brand brand-logo" href="{{ url_for('home') }}">
                <i class="bi bi-tree-fill text-warning me-2"></i>Farm<span>Connect</span>
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav ms-auto align-items-center">
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('home') }}">मुख्यपृष्ठ (Home)</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('farmers') }}">शेतकरी (Farmers)</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('guidance') }}">सल्ला (Guidance)</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('about') }}">आमच्याबद्दल (About)</a></li>
                    
                    {% if session.get('user_id') %}
                        {% if session.get('role') == 'admin' %}
                            <li class="nav-item"><a class="nav-link fw-bold text-warning" href="{{ url_for('admin') }}"><i class="bi bi-speedometer2"></i> Admin Panel</a></li>
                        {% elif session.get('role') == 'farmer' %}
                            <li class="nav-item"><a class="nav-link fw-bold text-warning" href="{{ url_for('farmer_dashboard') }}"><i class="bi bi-speedometer2"></i> Farmer Dashboard</a></li>
                        {% else %}
                            <li class="nav-item"><a class="nav-link fw-bold text-warning" href="{{ url_for('visitor_dashboard') }}"><i class="bi bi-speedometer2"></i> Visitor Dashboard</a></li>
                        {% endif %}
                        <li class="nav-item ms-lg-2">
                            <a class="btn btn-outline-light btn-sm px-3 rounded-pill" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right me-1"></i>बाहेर पडा</a>
                        </li>
                    {% else %}
                        <li class="nav-item ms-lg-2">
                            <a class="nav-link me-2" href="{{ url_for('login') }}">लॉगिन</a>
                        </li>
                        <li class="nav-item">
                            <a class="btn btn-agri-primary text-white" href="{{ url_for('register') }}">नोंदणी करा</a>
                        </li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-3">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ 'danger' if category == 'error' else category }} alert-dismissible fade show rounded-3 shadow-sm" role="alert">
                        <i class="bi bi-info-circle-fill me-2"></i> {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
    </div>

    <!-- CONTENT_PLACEHOLDER -->

    <footer class="footer-custom">
        <div class="container text-center text-md-start">
            <div class="row">
                <div class="col-md-5 mb-4">
                    <h5 class="text-white fw-bold"><i class="bi bi-tree-fill text-success me-2"></i>FarmConnect</h5>
                    <p class="small text-muted">शेतकरी आणि पर्यटकांना थेट जोडणारे डिजिटल ॲग्रिटुरिझम आणि कृषी मार्गदर्शन व्यासपीठ.</p>
                </div>
                <div class="col-md-3 mb-4">
                    <h6 class="text-white fw-bold">क्विक लिंक्स</h6>
                    <ul class="list-unstyled small">
                        <li><a href="{{ url_for('farmers') }}" class="text-muted text-decoration-none">शेतकरी शोधा</a></li>
                        <li><a href="{{ url_for('guidance') }}" class="text-muted text-decoration-none">कृषी सल्ला</a></li>
                        <li><a href="{{ url_for('register') }}" class="text-muted text-decoration-none">शेताची नोंदणी करा</a></li>
                    </ul>
                </div>
                <div class="col-md-4 mb-4">
                    <h6 class="text-white fw-bold">संपर्क</h6>
                    <p class="small text-muted mb-1"><i class="bi bi-geo-alt me-2"></i>पुणे, महाराष्ट्र, भारत</p>
                    <p class="small text-muted"><i class="bi bi-envelope me-2"></i>support@farmconnect.com</p>
                </div>
            </div>
            <hr class="border-secondary">
            <div class="text-center small text-muted">
                &copy; {{ current_year }} FarmConnect Inc. सर्व हक्क सुरक्षित.
            </div>
        </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

def render_page(content_html, **kwargs):
    full_html = BASE_LAYOUT.replace("<!-- CONTENT_PLACEHOLDER -->", content_html)
    return render_template_string(full_html, current_year=datetime.now().year, **kwargs)

# ------------------------------------------------------------------------------
# ROUTES & CONTROLLERS
# ------------------------------------------------------------------------------

@app.route("/")
def home():
    with db() as con:
        farmers = con.execute("SELECT * FROM farmers ORDER BY id DESC LIMIT 3").fetchall()
        
        fc_res = con.execute("SELECT COUNT(*) FROM farmers").fetchone()
        farmer_count = fc_res[list(fc_res.keys())[0]] if fc_res else 0
        
        bc_res = con.execute("SELECT COUNT(*) FROM bookings").fetchone()
        booking_count = bc_res[list(bc_res.keys())[0]] if bc_res else 0
        
        gc_res = con.execute("SELECT COUNT(*) FROM crop_guides").fetchone()
        guide_count = gc_res[list(gc_res.keys())[0]] if gc_res else 0

    content = """
    <section class="hero-section text-center">
        <div class="container">
            <h1 class="display-4 fw-bold mb-3">थेट शेताचा अनुभव आणि कृषी ज्ञान</h1>
            <p class="lead mb-4 opacity-90">प्रगतीशील शेतकऱ्यांच्या शेताला भेट द्या, नवीन तंत्रज्ञान शिका आणि ॲग्रिटुरिझमचा आनंद घ्या.</p>
            <div class="d-flex justify-content-center gap-3">
                <a href=""" + f"\"{url_for('farmers')}\"" + """ class="btn btn-agri-primary btn-lg px-4"><i class="bi bi-search me-2"></i>शेताला भेट द्या</a>
                <a href=""" + f"\"{url_for('guidance')}\"" + """ class="btn btn-outline-light btn-lg px-4 rounded-3"><i class="bi bi-book me-2"></i>पीक मार्गदर्शन</a>
            </div>
        </div>
    </section>

    <div class="container my-5">
        <div class="row g-4 text-center mb-5">
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h2 class="display-5 fw-bold text-success">{{ farmer_count }}</h2>
                    <p class="text-muted mb-0 fw-semibold">नोंदणीकृत शेतकरी</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h2 class="display-5 fw-bold text-success">{{ booking_count }}</h2>
                    <p class="text-muted mb-0 fw-semibold">यशस्वी बुकिंग्स</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h2 class="display-5 fw-bold text-success">{{ guide_count }}</h2>
                    <p class="text-muted mb-0 fw-semibold">कृषी मार्गदर्शन मार्गदर्शिका</p>
                </div>
            </div>
        </div>

        <div class="d-flex justify-content-between align-items-center mb-4">
            <div>
                <h3 class="fw-bold mb-0 text-success"><i class="bi bi-star-fill text-warning me-2"></i>प्रमुख शेतकरी</h3>
                <p class="text-muted small">उत्कृष्ट ॲग्रिटुरिझम आणि प्रयोगशील शेतकरी</p>
            </div>
            <a href=""" + f"\"{url_for('farmers')}\"" + """ class="btn btn-outline-success rounded-pill px-4">सर्व पहा &rarr;</a>
        </div>

        <div class="row g-4">
            {% for farmer in farmers %}
            <div class="col-md-4">
                <div class="card card-custom h-100">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <span class="badge badge-agri"><i class="bi bi-geo-alt-fill me-1"></i>{{ farmer.village }}, {{ farmer.district }}</span>
                            <span class="fw-bold text-success">₹{{ farmer.fee }}/भेट</span>
                        </div>
                        <h5 class="card-title fw-bold mb-1">{{ farmer.name }}</h5>
                        <p class="text-muted small mb-3"><i class="bi bi-award me-1"></i>अनुभव: {{ farmer.experience }} वर्षे</p>
                        <p class="card-text text-secondary small mb-3"><strong>मुख्य पिके:</strong> {{ farmer.crops }}</p>
                        <div class="pt-3 border-top">
                            <a href="/book/{{ farmer.id }}" class="btn btn-agri-primary btn-sm w-100">बुकिंग करा / भेट द्या</a>
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12 text-center py-4">
                <p class="text-muted">अद्याप कोणत्याही शेतकऱ्याची नोंदणी झालेली नाही.</p>
            </div>
            {% endfor %}
        </div>
    </div>
    """
    return render_page(content, farmers=farmers, farmer_count=farmer_count, booking_count=booking_count, guide_count=guide_count)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["role"] = user["role"]
            flash(f"जी! आपले स्वागत आहे, {user['name']}!", "success")
            
            if user["role"] == "admin":
                return redirect(url_for("admin"))
            elif user["role"] == "farmer":
                return redirect(url_for("farmer_dashboard"))
            else:
                return redirect(url_for("visitor_dashboard"))
        else:
            flash("ईमेल किंवा पासवर्ड चुकीचा आहे.", "error")

    content = """
    <div class="container my-5">
        <div class="row justify-content-center">
            <div class="col-md-5">
                <div class="card card-custom p-4 p-md-5">
                    <div class="text-center mb-4">
                        <i class="bi bi-person-circle display-4 text-success"></i>
                        <h3 class="fw-bold mt-2">लॉगिन करा</h3>
                        <p class="text-muted small">आपल्या FarmConnect खातात प्रवेश करा</p>
                    </div>
                    <form method="POST">
                        <div class="mb-3">
                            <label class="form-label fw-semibold">ईमेल पत्ता (Email)</label>
                            <input type="email" name="email" class="form-control form-control-lg fs-6" required placeholder="example@mail.com">
                        </div>
                        <div class="mb-4">
                            <label class="form-label fw-semibold">पासवर्ड (Password)</label>
                            <input type="password" name="password" class="form-control form-control-lg fs-6" required placeholder="••••••••">
                        </div>
                        <button type="submit" class="btn btn-agri-primary w-100 py-2 fs-6">लॉगिन</button>
                    </form>
                    <div class="text-center mt-4">
                        <p class="small text-muted">खाते नाही? <a href=""" + f"\"{url_for('register')}\"" + """ class="text-success fw-bold text-decoration-none">नवीन नोंदणी करा</a></p>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(content)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "visitor").strip()

        village = request.form.get("village", "").strip()
        district = request.form.get("district", "").strip()
        crops = request.form.get("crops", "").strip()
        experience = request.form.get("experience", 0)
        fee = request.form.get("fee", 0)
        bio = request.form.get("bio", "").strip()

        if not name or not email or not phone or not password:
            flash("कृपया सर्व आवश्यक माहिती भरा.", "error")
            return redirect(url_for("register"))

        if role == "farmer" and (not village or not district or not crops):
            flash("शेतकरी खात्यासाठी गाव, जिल्हा आणि पिकांची माहिती आवश्यक आहे.", "error")
            return redirect(url_for("register"))

        hashed_pw = generate_password_hash(password)

        try:
            with db() as con:
                if DATABASE_URL:
                    con.execute("""
                        INSERT INTO users (name, email, phone, password, role, created_at)
                        VALUES (?, ?, ?, ?, ?, ?) RETURNING id
                    """, (name, email, phone, hashed_pw, role, datetime.now().isoformat(timespec="minutes")))
                    user_row = con.fetchone()
                    user_id = user_row["id"] if user_row else None
                else:
                    con.execute("""
                        INSERT INTO users (name, email, phone, password, role, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (name, email, phone, hashed_pw, role, datetime.now().isoformat(timespec="minutes")))
                    user_id = con.lastrowid

                if role == "farmer" and user_id:
                    con.execute("""
                        INSERT INTO farmers (user_id, name, phone, village, district, crops, experience, fee, bio, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (user_id, name, phone, village, district, crops, experience, fee, bio, datetime.now().isoformat(timespec="minutes")))

            flash("नोंदणी यशस्वी झाली! आता लॉगिन करा.", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash("हा ईमेल आयडी आधीच वापरला गेला आहे किंवा एरर आला.", "error")

    content = """
    <div class="container my-5">
        <div class="row justify-content-center">
            <div class="col-md-7">
                <div class="card card-custom p-4 p-md-5">
                    <div class="text-center mb-4">
                        <i class="bi bi-person-plus-fill display-4 text-success"></i>
                        <h3 class="fw-bold mt-2">नवीन खाते तयार करा</h3>
                        <p class="text-muted small">शेतकरी किंवा पर्यटक म्हणून FarmConnect मध्ये सामील व्हा</p>
                    </div>

                    <form method="POST">
                        <div class="row g-3 mb-3">
                            <div class="col-md-6">
                                <label class="form-label fw-semibold">पूर्ण नाव *</label>
                                <input type="text" name="name" class="form-control" required placeholder="उदा. अजय पाटील">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold">फोन नंबर *</label>
                                <input type="tel" name="phone" class="form-control" required placeholder="9876543210">
                            </div>
                        </div>

                        <div class="row g-3 mb-3">
                            <div class="col-md-6">
                                <label class="form-label fw-semibold">ईमेल *</label>
                                <input type="email" name="email" class="form-control" required placeholder="name@example.com">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold">पासवर्ड *</label>
                                <input type="password" name="password" class="form-control" required placeholder="••••••••">
                            </div>
                        </div>

                        <div class="mb-4">
                            <label class="form-label fw-semibold">तुम्ही कोण आहात? *</label>
                            <select name="role" id="roleSelect" class="form-select form-select-lg fs-6" onchange="toggleFarmerFields()">
                                <option value="visitor">पर्यटक / अभ्यासक (Visitor)</option>
                                <option value="farmer">प्रगतीशील शेतकरी (Farmer Profile)</option>
                            </select>
                        </div>

                        <div id="farmerFields" style="display: none;" class="p-3 bg-light rounded-3 mb-4 border">
                            <h6 class="fw-bold text-success mb-3"><i class="bi bi-geo-alt-fill me-1"></i>शेतीची माहिती</h6>
                            <div class="row g-3 mb-3">
                                <div class="col-md-6">
                                    <label class="form-label fw-semibold">गाव *</label>
                                    <input type="text" name="village" class="form-control" placeholder="उदा. राहूरी">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label fw-semibold">जिल्हा *</label>
                                    <input type="text" name="district" class="form-control" placeholder="उदा. अहिल्यानगर">
                                </div>
                            </div>
                            <div class="mb-3">
                                <label class="form-label fw-semibold">मुख्य पिके *</label>
                                <input type="text" name="crops" class="form-control" placeholder="उदा. कांदा, ऊस, टोमॅटो">
                            </div>
                            <div class="row g-3 mb-3">
                                <div class="col-md-6">
                                    <label class="form-label fw-semibold">शेती अनुभव (वर्षे)</label>
                                    <input type="number" name="experience" class="form-control" value="0">
                                </div>
                                <div class="col-md-6">
                                    <label class="form-label fw-semibold">भेट शुल्क (₹)</label>
                                    <input type="number" name="fee" class="form-control" value="0">
                                </div>
                            </div>
                            <div class="mb-2">
                                <label class="form-label fw-semibold">शेताविषयी माहिती (Bio)</label>
                                <textarea name="bio" class="form-control" rows="2" placeholder="तुमच्या शेताविषयी आणि तंत्रज्ञानाविषयी थोडक्यात माहिती..."></textarea>
                            </div>
                        </div>

                        <button type="submit" class="btn btn-agri-primary w-100 py-2 fs-6">खाते तयार करा</button>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <script>
        function toggleFarmerFields() {
            var role = document.getElementById("roleSelect").value;
            var fields = document.getElementById("farmerFields");
            fields.style.display = (role === "farmer") ? "block" : "none";
        }
    </script>
    """
    return render_page(content)

@app.route("/logout")
def logout():
    session.clear()
    flash("आपण यशस्वीपणे बाहेर पडला आहात.", "info")
    return redirect(url_for("login"))

@app.route("/farmers")
def farmers():
    q = request.args.get("q", "").strip()
    with db() as con:
        if q:
            rows = con.execute("""
                SELECT * FROM farmers
                WHERE name LIKE ? OR village LIKE ? OR district LIKE ? OR crops LIKE ?
                ORDER BY id DESC
            """, tuple([f"%{q}%"] * 4)).fetchall()
        else:
            rows = con.execute("SELECT * FROM farmers ORDER BY id DESC").fetchall()

    content = """
    <div class="container my-5">
        <div class="row align-items-center mb-4">
            <div class="col-md-6">
                <h2 class="fw-bold text-success mb-1"><i class="bi bi-people-fill me-2"></i>नोंदणीकृत शेतकरी</h2>
                <p class="text-muted">ॲग्रिटुरिझम आणि शेत भेटीसाठी योग्य शेतकरी शोधा</p>
            </div>
            <div class="col-md-6">
                <form method="GET" action=""" + f"\"{url_for('farmers')}\"" + """ class="d-flex gap-2">
                    <input type="text" name="q" value="{{ q }}" class="form-control" placeholder="नाव, गाव, जिल्हा किंवा पीक शोधा...">
                    <button type="submit" class="btn btn-agri-primary"><i class="bi bi-search"></i></button>
                </form>
            </div>
        </div>

        <div class="row g-4">
            {% for farmer in farmers %}
            <div class="col-md-4">
                <div class="card card-custom h-100">
                    <div class="card-body p-4 d-flex flex-column">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <span class="badge badge-agri"><i class="bi bi-geo-alt-fill me-1"></i>{{ farmer.village }}, {{ farmer.district }}</span>
                            <span class="fw-bold text-success">₹{{ farmer.fee }} / भेट</span>
                        </div>
                        <h5 class="fw-bold mb-1">{{ farmer.name }}</h5>
                        <p class="text-muted small mb-2"><i class="bi bi-award me-1"></i>अनुभव: {{ farmer.experience }} वर्षे</p>
                        <p class="small text-secondary mb-3"><strong>पिके:</strong> {{ farmer.crops }}</p>
                        {% if farmer.bio %}
                        <p class="small text-muted mb-4 flex-grow-1">{{ farmer.bio[:100] }}...</p>
                        {% endif %}
                        <a href="/book/{{ farmer.id }}" class="btn btn-agri-primary btn-sm w-100 mt-auto">शेताला भेट बुकिंग करा</a>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12 text-center py-5">
                <i class="bi bi-emoji-frown display-4 text-muted"></i>
                <p class="text-muted mt-2">कोणतेही शेतकरी सापडले नाहीत.</p>
            </div>
            {% endfor %}
        </div>
    </div>
    """
    return render_page(content, farmers=rows, q=q)

@app.route("/book/<int:farmer_id>", methods=["GET", "POST"])
def book(farmer_id):
    with db() as con:
        farmer = con.execute("SELECT * FROM farmers WHERE id=?", (farmer_id,)).fetchone()

    if not farmer:
        flash("शेतकरी सापडला नाही.", "error")
        return redirect(url_for("farmers"))

    if request.method == "POST":
        visitor_name = request.form.get("visitor_name", "").strip()
        visitor_phone = request.form.get("visitor_phone", "").strip()
        visit_date = request.form.get("visit_date", "").strip()
        message = request.form.get("message", "").strip()
        visitor_id = session.get("user_id")

        if not visitor_name or not visitor_phone or not visit_date:
            flash("कृपया सर्व आवश्यक माहिती भरा.", "error")
            return redirect(url_for("book", farmer_id=farmer_id))

        with db() as con:
            con.execute("""
                INSERT INTO bookings(farmer_id, visitor_id, visitor_name, visitor_phone, visit_date, message, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (farmer_id, visitor_id, visitor_name, visitor_phone, visit_date, message, datetime.now().isoformat(timespec="minutes")))

        flash("बुकिंग विनंती यशस्वीरित्या पाठवली आहे! शेतकरी तुमच्याशी संपर्क साधतील.", "success")
        return redirect(url_for("visitor_dashboard") if session.get("user_id") else url_for("farmers"))

    content = """
    <div class="container my-5">
        <div class="row justify-content-center">
            <div class="col-md-8">
                <div class="card card-custom p-4 p-md-5">
                    <h3 class="fw-bold text-success mb-4"><i class="bi bi-calendar-check me-2"></i>शेतास भेट - बुकिंग अर्ज</h3>
                    
                    <div class="bg-light p-3 rounded-3 mb-4">
                        <h5 class="fw-bold text-dark mb-1">{{ farmer.name }}</h5>
                        <p class="text-muted small mb-0"><i class="bi bi-geo-alt me-1"></i>{{ farmer.village }}, {{ farmer.district }} | <strong>शुल्क:</strong> ₹{{ farmer.fee }}</p>
                    </div>

                    <form method="POST">
                        <div class="row g-3 mb-3">
                            <div class="col-md-6">
                                <label class="form-label fw-semibold">तुमचे नाव *</label>
                                <input type="text" name="visitor_name" class="form-control" required value="{{ session.get('user_name', '') }}">
                            </div>
                            <div class="col-md-6">
                                <label class="form-label fw-semibold">फोन नंबर *</label>
                                <input type="tel" name="visitor_phone" class="form-control" required placeholder="9876543210">
                            </div>
                        </div>

                        <div class="mb-3">
                            <label class="form-label fw-semibold">भेटीची तारीख *</label>
                            <input type="date" name="visit_date" class="form-control" required>
                        </div>

                        <div class="mb-4">
                            <label class="form-label fw-semibold">संदेश / उद्देश (पर्यायी)</label>
                            <textarea name="message" class="form-control" rows="3" placeholder="भेटीचा उद्देश किंवा विचारायचे प्रश्न लिहू शकता..."></textarea>
                        </div>

                        <button type="submit" class="btn btn-agri-primary w-100 py-2 fs-6">बुकिंग कन्फर्म करा</button>
                    </form>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(content, farmer=farmer)

@app.route("/guidance")
def guidance():
    q = request.args.get("q", "").strip()
    with db() as con:
        if q:
            guides = con.execute("SELECT * FROM crop_guides WHERE crop LIKE ? OR topic LIKE ?", (f"%{q}%", f"%{q}%")).fetchall()
        else:
            guides = con.execute("SELECT * FROM crop_guides ORDER BY crop").fetchall()

    content = """
    <div class="container my-5">
        <div class="row align-items-center mb-4">
            <div class="col-md-6">
                <h2 class="fw-bold text-success mb-1"><i class="bi bi-book-half me-2"></i>कृषी सल्ला आणि पीक मार्गदर्शन</h2>
                <p class="text-muted">पिकांची निगा आणि आधुनिक शेती तंत्रज्ञानाची माहिती</p>
            </div>
            <div class="col-md-6">
                <form method="GET" action=""" + f"\"{url_for('guidance')}\"" + """ class="d-flex gap-2">
                    <input type="text" name="q" value="{{ q }}" class="form-control" placeholder="पिकाचे नाव शोधा (उदा. Tomato, Cotton)...">
                    <button type="submit" class="btn btn-agri-primary"><i class="bi bi-search"></i></button>
                </form>
            </div>
        </div>

        <div class="row g-4">
            {% for guide in guides %}
            <div class="col-md-6">
                <div class="card card-custom h-100">
                    <div class="card-body p-4">
                        <span class="badge badge-agri mb-2">{{ guide.crop }}</span>
                        <h5 class="fw-bold text-dark mb-2">{{ guide.topic }}</h5>
                        <p class="text-secondary mb-0" style="line-height: 1.6;">{{ guide.guidance }}</p>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12 text-center py-5">
                <p class="text-muted">कोणतेही पीक मार्गदर्शन उपलब्ध नाही.</p>
            </div>
            {% endfor %}
        </div>
    </div>
    """
    return render_page(content, guides=guides, q=q)

@app.route("/about")
def about():
    content = """
    <div class="container my-5">
        <div class="row justify-content-center">
            <div class="col-md-10">
                <div class="card card-custom p-4 p-md-5">
                    <h2 class="fw-bold text-success mb-3"><i class="bi bi-info-circle me-2"></i>FarmConnect विषयी</h2>
                    <p class="lead text-secondary">FarmConnect हे एक आधुनिक डिजिटल प्लॅटफॉर्म आहे जे शेतकरी, संशोधक आणि कृषी-पर्यटकांना एकमेकांशी थेट जोडते.</p>
                    <hr class="my-4">
                    <div class="row g-4">
                        <div class="col-md-6">
                            <h5 class="fw-bold text-dark"><i class="bi bi-bullseye text-success me-2"></i>आमचे उद्दिष्ट</h5>
                            <p class="text-muted">ग्रामीण भागातील प्रगतीशील शेतकऱ्यांच्या कौशल्याला आणि शेताला योग्य व्यासपीठ देणे तसेच पर्यटकांना थेट निसर्गाच्या सानिध्यात कृषी पर्यटनाचा आनंद घेण्याची संधी उपलब्ध करून देणे.</p>
                        </div>
                        <div class="col-md-6">
                            <h5 class="fw-bold text-dark"><i class="bi bi-shield-check text-success me-2"></i>मुख्य वैशिष्ट्ये</h5>
                            <ul class="text-muted">
                                <li>थेट शेतकरी भेट आणि अनुभव</li>
                                <li>पारदर्शक बुकिंग व्यवस्था</li>
                                <li>पिकांचे आधुनिक तंत्रज्ञान व मार्गदर्शन</li>
                                <li>सुलभ आणि सुरक्षित डिजिटल प्लॅटफॉर्म</li>
                            </ul>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """
    return render_page(content)

@app.route("/farmer-dashboard")
@login_required
@role_required("farmer")
def farmer_dashboard():
    user_id = session.get("user_id")
    with db() as con:
        farmer = con.execute("SELECT * FROM farmers WHERE user_id=?", (user_id,)).fetchone()
        bookings = []
        if farmer:
            bookings = con.execute("""
                SELECT * FROM bookings WHERE farmer_id=? ORDER BY id DESC
            """, (farmer["id"],)).fetchall()

    content = """
    <div class="container my-5">
        <h2 class="fw-bold text-success mb-4"><i class="bi bi-speedometer2 me-2"></i>शेतकरी डॅशबोर्ड (Farmer Dashboard)</h2>
        
        {% if farmer %}
        <div class="row g-4 mb-5">
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h6 class="text-muted fw-bold">तुमची प्रोफाईल</h6>
                    <h4 class="fw-bold text-dark mb-1">{{ farmer.name }}</h4>
                    <p class="small text-muted mb-0"><i class="bi bi-geo-alt"></i> {{ farmer.village }}, {{ farmer.district }}</p>
                    <p class="small text-muted mb-0"><i class="bi bi-journal-text"></i> पिके: {{ farmer.crops }}</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-custom p-4 text-center">
                    <h6 class="text-muted fw-bold">एकूण बुकिंग्स</h6>
                    <h2 class="display-6 fw-bold text-success mb-0">{{ bookings|length }}</h2>
                </div>
            </div>
        </div>

        <h4 class="fw-bold text-dark mb-3">शेतास भेट बुकिंग विनंत्या</h4>
        <div class="card card-custom p-3">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>पर्यटकाचे नाव</th>
                            <th>फोन नंबर</th>
                            <th>भेटीची तारीख</th>
                            <th>संदेश</th>
                            <th>स्थिती (Status)</th>
                            <th>कृती (Action)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for b in bookings %}
                        <tr>
                            <td class="fw-semibold">{{ b.visitor_name }}</td>
                            <td>{{ b.visitor_phone }}</td>
                            <td>{{ b.visit_date }}</td>
                            <td class="small text-muted">{{ b.message or '-' }}</td>
                            <td>
                                <span class="badge bg-{{ 'warning' if b.status == 'Pending' else ('success' if b.status == 'Accepted' else 'secondary') }}">
                                    {{ b.status }}
                                </span>
                            </td>
                            <td>
                                <form method="POST" action="/booking-status/{{ b.id }}" class="d-flex gap-1">
                                    <select name="status" class="form-select form-select-sm" style="width: 120px;">
                                        <option value="Pending" {% if b.status=='Pending' %}selected{% endif %}>Pending</option>
                                        <option value="Accepted" {% if b.status=='Accepted' %}selected{% endif %}>Accepted</option>
                                        <option value="Completed" {% if b.status=='Completed' %}selected{% endif %}>Completed</option>
                                        <option value="Cancelled" {% if b.status=='Cancelled' %}selected{% endif %}>Cancelled</option>
                                    </select>
                                    <button type="submit" class="btn btn-sm btn-agri-primary">अपडेट</button>
                                </form>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="6" class="text-center text-muted py-4">अद्याप कोणत्याही बुकिंग्स आलेल्या नाहीत.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% else %}
        <div class="alert alert-warning">तुमची शेतकरी प्रोफाईल पूर्ण केलेली नाही.</div>
        {% endif %}
    </div>
    """
    return render_page(content, farmer=farmer, bookings=bookings)

@app.route("/visitor-dashboard")
@login_required
@role_required("visitor")
def visitor_dashboard():
    user_id = session.get("user_id")
    with db() as con:
        bookings = con.execute("""
            SELECT b.*, f.name AS farmer_name, f.village, f.district
            FROM bookings b
            JOIN farmers f ON f.id = b.farmer_id
            WHERE b.visitor_id=?
            ORDER BY b.id DESC
        """, (user_id,)).fetchall()

    content = """
    <div class="container my-5">
        <h2 class="fw-bold text-success mb-4"><i class="bi bi-person-badge me-2"></i>माझा डॅशबोर्ड (Visitor Dashboard)</h2>
        
        <h4 class="fw-bold text-dark mb-3">माझ्या शेत भेट बुकिंग्स</h4>
        <div class="card card-custom p-3">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>शेतकऱ्याचे नाव</th>
                            <th>ठिकाण</th>
                            <th>भेटीची तारीख</th>
                            <th>पेमेंट स्थिती</th>
                            <th>बुकिंग स्थिती</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for b in bookings %}
                        <tr>
                            <td class="fw-semibold">{{ b.farmer_name }}</td>
                            <td>{{ b.village }}, {{ b.district }}</td>
                            <td>{{ b.visit_date }}</td>
                            <td><span class="badge bg-light text-dark border">{{ b.payment_status }}</span></td>
                            <td>
                                <span class="badge bg-{{ 'warning' if b.status == 'Pending' else ('success' if b.status == 'Accepted' else 'secondary') }}">
                                    {{ b.status }}
                                </span>
                            </td>
                        </tr>
                        {% else %}
                        <tr><td colspan="5" class="text-center text-muted py-4">तुम्ही अद्याप कोणतीही भेट बुकिंग केलेली नाही. <a href=""" + f"\"{url_for('farmers')}\"" + """>येथे शोधा</a>.</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page(content, bookings=bookings)

@app.route("/admin")
@login_required
@role_required("admin")
def admin():
    with db() as con:
        bookings = con.execute("""
            SELECT b.*, f.name AS farmer_name, f.village, f.district, f.fee
            FROM bookings b JOIN farmers f ON f.id=b.farmer_id
            ORDER BY b.id DESC
        """).fetchall()
        farmers = con.execute("SELECT * FROM farmers ORDER BY id DESC").fetchall()
        users = con.execute("SELECT * FROM users ORDER BY id DESC").fetchall()

    content = """
    <div class="container my-5">
        <h2 class="fw-bold text-success mb-4"><i class="bi bi-shield-lock me-2"></i>ॲडमिन पॅनेल (Admin Control)</h2>

        <h4 class="fw-bold text-dark mb-3">सर्व बुकिंग्स</h4>
        <div class="card card-custom p-3 mb-5">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>#ID</th>
                            <th>शेतकरी</th>
                            <th>पर्यटक</th>
                            <th>फोन</th>
                            <th>तारीख</th>
                            <th>स्थिती</th>
                            <th>कृती</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for b in bookings %}
                        <tr>
                            <td>#{{ b.id }}</td>
                            <td class="fw-semibold">{{ b.farmer_name }}</td>
                            <td>{{ b.visitor_name }}</td>
                            <td>{{ b.visitor_phone }}</td>
                            <td>{{ b.visit_date }}</td>
                            <td><span class="badge bg-info text-dark">{{ b.status }}</span></td>
                            <td>
                                <form method="POST" action="/booking-status/{{ b.id }}" class="d-flex gap-1">
                                    <select name="status" class="form-select form-select-sm">
                                        <option value="Pending" {% if b.status=='Pending' %}selected{% endif %}>Pending</option>
                                        <option value="Accepted" {% if b.status=='Accepted' %}selected{% endif %}>Accepted</option>
                                        <option value="Completed" {% if b.status=='Completed' %}selected{% endif %}>Completed</option>
                                        <option value="Cancelled" {% if b.status=='Cancelled' %}selected{% endif %}>Cancelled</option>
                                    </select>
                                    <button type="submit" class="btn btn-sm btn-agri-primary">अपडेट</button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>

        <h4 class="fw-bold text-dark mb-3">नोंदणीकृत शेतकरी यादी</h4>
        <div class="card card-custom p-3">
            <div class="table-responsive">
                <table class="table table-hover align-middle mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>नाव</th>
                            <th>फोन</th>
                            <th>ठिकाण</th>
                            <th>पिके</th>
                            <th>शुल्क</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for f in farmers %}
                        <tr>
                            <td class="fw-semibold">{{ f.name }}</td>
                            <td>{{ f.phone }}</td>
                            <td>{{ f.village }}, {{ f.district }}</td>
                            <td>{{ f.crops }}</td>
                            <td>₹{{ f.fee }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    """
    return render_page(content, bookings=bookings, farmers=farmers, users=users)

@app.route("/booking-status/<int:booking_id>", methods=["POST"])
@login_required
def booking_status(booking_id):
    status = request.form.get("status", "Pending")
    if status not in ("Pending", "Accepted", "Completed", "Cancelled"):
        status = "Pending"
    with db() as con:
        con.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    flash("बुकिंग स्थिती अद्यतनित (Updated) केली गेली आहे.", "success")
    return redirect(request.referrer or url_for("home"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
