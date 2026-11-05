from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from pathlib import Path
from datetime import datetime

app = Flask(__name__)
app.secret_key = "change-this-secret-key"
DB_PATH = Path(__file__).with_name("farmconnect.db")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS farmers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        con.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            visitor_name TEXT NOT NULL,
            visitor_phone TEXT NOT NULL,
            visit_date TEXT NOT NULL,
            message TEXT DEFAULT '',
            payment_status TEXT DEFAULT 'Pay on visit',
            status TEXT DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY(farmer_id) REFERENCES farmers(id)
        )""")
        con.execute("""
        CREATE TABLE IF NOT EXISTS crop_guides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crop TEXT NOT NULL,
            topic TEXT NOT NULL,
            guidance TEXT NOT NULL
        )""")
        count = con.execute("SELECT COUNT(*) AS n FROM crop_guides").fetchone()["n"]
        if count == 0:
            guides = [
                ("Tomato", "General care", "Use healthy seedlings, maintain suitable spacing, avoid waterlogging, and monitor plants regularly for pests and disease."),
                ("Cotton", "General care", "Use locally recommended varieties, follow soil-test-based nutrient plans, and monitor for sucking pests and bollworm."),
                ("Onion", "General care", "Maintain well-drained soil, avoid excess irrigation near maturity, and monitor for thrips and purple blotch."),
                ("Wheat", "General care", "Use certified seed, sow at the locally recommended time, and apply nutrients according to soil-test results."),
                ("Soybean", "General care", "Ensure good drainage, use recommended seed treatment, and monitor for defoliators and yellow mosaic symptoms.")
            ]
            con.executemany("INSERT INTO crop_guides(crop,topic,guidance) VALUES(?,?,?)", guides)

@app.route("/")
def home():
    with db() as con:
        farmers = con.execute("SELECT * FROM farmers ORDER BY id DESC LIMIT 3").fetchall()
        farmer_count = con.execute("SELECT COUNT(*) FROM farmers").fetchone()[0]
        booking_count = con.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    return render_template("index.html", farmers=farmers, farmer_count=farmer_count, booking_count=booking_count)

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
    return render_template("farmers.html", farmers=rows, q=q)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        data = [request.form.get(k, "").strip() for k in
                ("name", "phone", "village", "district", "crops", "experience", "fee", "bio")]
        if not all(data[i] for i in range(5)):
            flash("Please fill all required fields.", "error")
            return redirect(url_for("register"))
        try:
            experience = max(0, int(data[5] or 0))
            fee = max(0, float(data[6] or 0))
        except ValueError:
            flash("Experience and consultation fee must be numbers.", "error")
            return redirect(url_for("register"))
        with db() as con:
            con.execute("""
                INSERT INTO farmers(name,phone,village,district,crops,experience,fee,bio,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (data[0], data[1], data[2], data[3], data[4], experience, fee, data[7],
                  datetime.now().isoformat(timespec="minutes")))
        flash("Farmer profile created successfully!", "success")
        return redirect(url_for("farmers"))
    return render_template("register.html")

@app.route("/book/<int:farmer_id>", methods=["GET", "POST"])
def book(farmer_id):
    with db() as con:
        farmer = con.execute("SELECT * FROM farmers WHERE id=?", (farmer_id,)).fetchone()
    if not farmer:
        flash("Farmer not found.", "error")
        return redirect(url_for("farmers"))
    if request.method == "POST":
        name = request.form.get("visitor_name", "").strip()
        phone = request.form.get("visitor_phone", "").strip()
        date = request.form.get("visit_date", "").strip()
        message = request.form.get("message", "").strip()
        if not name or not phone or not date:
            flash("Name, phone and visit date are required.", "error")
            return redirect(url_for("book", farmer_id=farmer_id))
        with db() as con:
            con.execute("""
                INSERT INTO bookings(farmer_id,visitor_name,visitor_phone,visit_date,message,created_at)
                VALUES(?,?,?,?,?,?)
            """, (farmer_id, name, phone, date, message, datetime.now().isoformat(timespec="minutes")))
        flash("Booking request submitted. Payment is not collected in this demo.", "success")
        return redirect(url_for("farmers"))
    return render_template("book.html", farmer=farmer)

@app.route("/guidance")
def guidance():
    q = request.args.get("q", "").strip()
    with db() as con:
        if q:
            guides = con.execute("SELECT * FROM crop_guides WHERE crop LIKE ?", (f"%{q}%",)).fetchall()
        else:
            guides = con.execute("SELECT * FROM crop_guides ORDER BY crop").fetchall()
    return render_template("guidance.html", guides=guides, q=q)

@app.route("/admin")
def admin():
    with db() as con:
        bookings = con.execute("""
            SELECT b.*, f.name AS farmer_name, f.village, f.district, f.fee
            FROM bookings b JOIN farmers f ON f.id=b.farmer_id
            ORDER BY b.id DESC
        """).fetchall()
        farmers = con.execute("SELECT * FROM farmers ORDER BY id DESC").fetchall()
    return render_template("admin.html", bookings=bookings, farmers=farmers)

@app.route("/booking-status/<int:booking_id>", methods=["POST"])
def booking_status(booking_id):
    status = request.form.get("status", "Pending")
    if status not in ("Pending", "Accepted", "Completed", "Cancelled"):
        status = "Pending"
    with db() as con:
        con.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    flash("Booking status updated.", "success")
    return redirect(url_for("admin"))
init_db()
@app.route("/about")
def about():
    return render_template("about.html")

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
