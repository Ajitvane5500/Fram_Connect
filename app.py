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
            flash("Please log in to continue.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('role') not in roles:
                flash("You do not have permission to access this page.", "danger")
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ------------------------------------------------------------------------------
# BASE HTML LAYOUT TEMPLATE & RENDER HELPER
# ------------------------------------------------------------------------------
BASE_LAYOUT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>FarmConnect - Agritourism & Farming Guidance Platform</title>
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
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('home') }}">Home</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('farmers') }}">Farmers</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('guidance') }}">Crop Guidance</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('about') }}">About Us</a></li>
                    
                    {% if session.get('user_id') %}
                        {% if session.get('role') == 'admin' %}
                            <li class="nav-item"><a class="nav-link fw-bold text-warning" href="{{ url_for('admin') }}"><i class="bi bi-shield-lock-fill me-1"></i> Admin Panel</a></li>
                        {% elif session.get('role') == 'farmer' %}
                            <li class="nav-item"><a class="nav-link fw-bold text-warning" href="{{ url_for('farmer_dashboard') }}"><i class="bi bi-speedometer2"></i> Farmer Dashboard</a></li>
                        {% else %}
                            <li class="nav-item"><a class="nav-link fw-bold text-warning" href="{{ url_for('visitor_dashboard') }}"><i class="bi bi-speedometer2"></i> Visitor Dashboard</a></li>
                        {% endif %}
                        <li class="nav-item ms-lg-2">
                            <a class="btn btn-outline-light btn-sm px-3 rounded-pill" href="{{ url_for('logout') }}"><i class="bi bi-box-arrow-right me-1"></i>Logout</a>
                        </li>
                    {% else %}
                        <li class="nav-item ms-lg-2">
                            <a class="nav-link me-2" href="{{ url_for('login') }}">Login</a>
                        </li>
                        <li class="nav-item me-2">
                            <a class="btn btn-agri-primary text-white" href="{{ url_for('register') }}">Register</a>
                        </li>
                        <li class="nav-item">
                            <a class="btn btn-outline-warning btn-sm px-3 rounded-pill" href="{{ url_for('login') }}"><i class="bi bi-shield-lock-fill me-1"></i> Admin</a>
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
                    <p class="small text-muted">A digital agritourism and farming guidance platform directly connecting progressive farmers with visitors and learners.</p>
                </div>
                <div class="col-md-3 mb-4">
                    <h6 class="text-white fw-bold">Quick Links</h6>
                    <ul class="list-unstyled small">
                        <li><a href="{{ url_for('farmers') }}" class="text-muted text-decoration-none">Explore Farmers</a></li>
                        <li><a href="{{ url_for('guidance') }}" class="text-muted text-decoration-none">Crop Guidance</a></li>
                        <li><a href="{{ url_for('register') }}" class="text-muted text-decoration-none">Register Farm</a></li>
                    </ul>
                </div>
                <div class="col-md-4 mb-4">
                    <h6 class="text-white fw-bold">Contact Us</h6>
                    <p class="small text-muted mb-1"><i class="bi bi-geo-alt me-2"></i>Pune, Maharashtra, India</p>
                    <p class="small text-muted"><i class="bi bi-envelope me-2"></i>support@farmconnect.com</p>
                </div>
            </div>
            <hr class="border-secondary">
            <div class="text-center small text-muted">
                &copy; {{ current_year }} FarmConnect Inc. All rights reserved.
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
            <h1 class="display-4 fw-bold mb-3">Experience Authentic Farming & Agritourism</h1>
            <p class="lead mb-4 opacity-90">Visit progressive farms, learn modern agricultural technologies, and experience nature firsthand.</p>
            <div class="d-flex justify-content-center gap-3">
                <a href=""" + f"\"{url_for('farmers')}\"" + """ class="btn btn-agri-primary btn-lg px-4"><i class="bi bi-search me-2"></i>Book Farm Visit</a>
                <a href=""" + f"\"{url_for('guidance')}\"" + """ class="btn btn-outline-light btn-lg px-4 rounded-3"><i class="bi bi-book me-2"></i>Crop Guidance</a>
            </div>
        </div>
    </section>

    <div class="container my-5">
        {% if session.get('role') == 'admin' %}
        <!-- ADMIN DASHBOARD QUICK CONTROL WIDGET ON HOMEPAGE -->
        <div class="card card-custom p-4 mb-5 border border-warning border-2 bg-light">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h4 class="fw-bold text-success mb-0"><i class="bi bi-shield-lock-fill me-2"></i>Admin Dashboard Quick Access</h4>
                <a href=""" + f"\"{url_for('admin')}\"" + """ class="btn btn-agri-primary btn-sm"><i class="bi bi-gear-fill me-1"></i>Open Admin Panel</a>
            </div>
            <div class="row g-3">
                <div class="col-md-4">
                    <div class="p-3 bg-white rounded shadow-sm text-center">
                        <span class="text-muted small fw-semibold">Total Farmers</span>
                        <h3 class="fw-bold text-dark mb-0">{{ farmer_count }}</h3>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="p-3 bg-white rounded shadow-sm text-center">
                        <span class="text-muted small fw-semibold">Total Bookings</span>
                        <h3 class="fw-bold text-dark mb-0">{{ booking_count }}</h3>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="p-3 bg-white rounded shadow-sm text-center">
                        <span class="text-muted small fw-semibold">System Status</span>
                        <h3 class="fw-bold text-success mb-0"><i class="bi bi-check-circle-fill"></i> Active</h3>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <div class="row g-4 text-center mb-5">
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h2 class="display-5 fw-bold text-success">{{ farmer_count }}</h2>
                    <p class="text-muted mb-0 fw-semibold">Registered Farmers</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h2 class="display-5 fw-bold text-success">{{ booking_count }}</h2>
                    <p class="text-muted mb-0 fw-semibold">Successful Bookings</p>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card card-custom p-4">
                    <h2 class="display-5 fw-bold text-success">{{ guide_count }}</h2>
                    <p class="text-muted mb-0 fw-semibold">Farming Crop Guides</p>
                </div>
            </div>
        </div>

        <div class="d-flex justify-content-between align-items-center mb-4">
            <div>
                <h3 class="fw-bold mb-0 text-success"><i class="bi bi-star-fill text-warning me-2"></i>Featured Farmers</h3>
                <p class="text-muted small">Explore top-rated farms and progressive agricultural practices</p>
            </div>
            <a href=""" + f"\"{url_for('farmers')}\"" + """ class="btn btn-outline-success rounded-pill px-4">View All &rarr;</a>
        </div>

        <div class="row g-4">
            {% for farmer in farmers %}
            <div class="col-md-4">
                <div class="card card-custom h-100">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-start mb-3">
                            <span class="badge badge-agri"><i class="bi bi-geo-alt-fill me-1"></i>{{ farmer.village }}, {{ farmer.district }}</span>
                            <span class="fw-bold text-success">₹{{ farmer.fee }}/visit</span>
                        </div>
                        <h5 class="card-title fw-bold mb-1">{{ farmer.name }}</h5>
                        <p class="text-muted small mb-3"><i class="bi bi-award me-1"></i>Experience: {{ farmer.experience }} Years</p>
                        <p class="card-text text-secondary small mb-3"><strong>Key Crops:</strong> {{ farmer.crops }}</p>
                        <div class="pt-3 border-top">
                            <a href="/book/{{ farmer.id }}" class="btn btn-agri-primary btn-sm w-100">Book Farm Visit</a>
                        </div>
                    </div>
                </div>
            </div>
            {% else %}
            <div class="col-12 text-center py-4">
                <p class="text-muted">No farmers registered yet.</p>
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
