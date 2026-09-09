from flask import Flask, render_template, request, redirect, session, jsonify
import sqlite3
import os
from datetime import datetime, date, timedelta

app = Flask(__name__)
app.secret_key = "my-secret-key-123"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "messages.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_database():
    connection = sqlite3.connect(DB_PATH)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            message TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            distance_km REAL NOT NULL,
            minutes INTEGER NOT NULL,
            seconds INTEGER NOT NULL,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    connection.commit()
    connection.close()


def generate_plan(goal, days):
    """Generate a week-by-week running plan for a given goal and days-per-week."""
    configs = {
        "5k":       {"weeks": 8,  "start_long": 4,  "peak_long": 8,  "taper_weeks": 1},
        "10k":      {"weeks": 10, "start_long": 5,  "peak_long": 12, "taper_weeks": 1},
        "half":     {"weeks": 12, "start_long": 8,  "peak_long": 18, "taper_weeks": 2},
        "marathon": {"weeks": 16, "start_long": 10, "peak_long": 32, "taper_weeks": 2},
    }
    if goal not in configs or days not in (3, 4, 5, 6):
        return None
    cfg = configs[goal]
    total_weeks = cfg["weeks"]
    taper_weeks = cfg["taper_weeks"]
    build_weeks = total_weeks - taper_weeks - 1
    templates = {
        3: ["Easy Run", "Speed Training", "Long Run"],
        4: ["Easy Run", "Speed Training", "Easy Run", "Long Run"],
        5: ["Easy Run", "Speed Training", "Easy Run", "Tempo Run", "Long Run"],
        6: ["Easy Run", "Speed Training", "Easy Run", "Tempo Run", "Easy Run", "Long Run"],
    }
    day_template = templates[days]
    factors = {"Easy Run": 0.6, "Speed Training": 0.5, "Tempo Run": 0.55}

    def round_half(x):
        return round(x * 2) / 2

    def format_km(x):
        if x == int(x):
            return str(int(x))
        return str(x)

    def build_week_runs(long_distance):
        runs = []
        for run_type in day_template:
            if run_type == "Long Run":
                dist = long_distance
            else:
                dist = max(2, round_half(long_distance * factors[run_type]))
            runs.append(f"{run_type}: {format_km(dist)} km")
        return runs

    schedule = []
    for i in range(build_weeks):
        if build_weeks > 1:
            long_distance = cfg["start_long"] + (cfg["peak_long"] - cfg["start_long"]) * i / (build_weeks - 1)
        else:
            long_distance = cfg["peak_long"]
        long_distance = round_half(long_distance)
        schedule.append({"week": f"Week {i + 1}", "runs": build_week_runs(long_distance), "phase": "build" if i > 0 else "base"})
    taper_fractions = [0.75, 0.5] if taper_weeks == 2 else [0.6]
    for j in range(taper_weeks):
        long_distance = round_half(cfg["peak_long"] * taper_fractions[j])
        week_num = build_weeks + j + 1
        schedule.append({"week": f"Week {week_num}", "runs": build_week_runs(long_distance), "phase": "taper"})
    race_runs = []
    for run_type in day_template[:-1]:
        race_runs.append(f"{run_type}: {format_km(max(2, round_half(cfg['start_long'] * 0.4)))} km")
    race_runs.append(f"{goal.upper()} RACE 🏁")
    schedule.append({"week": f"Week {total_weeks} - Race Week", "runs": race_runs, "phase": "race"})
    return schedule


def calculate_pace(distance_km, minutes, seconds):
    total_seconds = minutes * 60 + seconds
    pace_seconds_per_km = total_seconds / distance_km
    pace_min = int(pace_seconds_per_km // 60)
    pace_sec = int(round(pace_seconds_per_km % 60))
    if pace_sec == 60:
        pace_sec = 0
        pace_min += 1
    return pace_min, pace_sec


def get_recommendation(distance_km, pace_seconds_per_km):
    if distance_km < 3:
        goal, goal_label, days = "5k", "5K", 3
        distance_note = "You're just starting to build distance, so the first target is getting comfortable over a full 5K."
    elif distance_km < 6:
        goal, goal_label, days = "5k", "5K", 4
        distance_note = "You've already got a solid base for a 5K - the next step is sharpening your pace over that distance."
    elif distance_km < 10:
        goal, goal_label, days = "10k", "10K", 4
        distance_note = "You're covering more ground than a typical beginner - a 10K is a natural next target."
    elif distance_km < 16:
        goal, goal_label, days = "half", "Half Marathon", 4
        distance_note = "That's serious distance already. A half marathon plan will build on the endurance you've already got."
    else:
        goal, goal_label, days = "marathon", "Marathon", 5
        distance_note = "You've shown you can handle long distances - a marathon plan is within reach."
    if pace_seconds_per_km < 300:
        pace_note = "Your pace is quick for this stage - you're ahead of most beginners."
    elif pace_seconds_per_km < 390:
        pace_note = "That's a solid, comfortable pace to build from."
    elif pace_seconds_per_km < 480:
        pace_note = "That's a steady pace - a great base to build endurance on."
    else:
        pace_note = "That's an easy, sustainable pace - ideal for building a base without injury."
    return {"goal": goal, "goal_label": goal_label, "days": days, "distance_note": distance_note, "pace_note": pace_note}


def predict_race(distance_km, minutes, seconds, target_km):
    """Riegel formula: T2 = T1 * (D2/D1)^1.06"""
    t1 = minutes * 60 + seconds
    if distance_km <= 0 or t1 <= 0:
        return None
    t2 = t1 * ((target_km / distance_km) ** 1.06)
    h = int(t2 // 3600)
    m = int((t2 % 3600) // 60)
    s = int(round(t2 % 60))
    if s == 60:
        s = 0
        m += 1
    return {"hours": h, "minutes": m, "seconds": s}


def training_zones(pace_sec_per_km):
    """5-pace-zone model based on 5k / threshold-ish pace."""
    zones = [
        ("Z1 Recovery", 1.30, 1.20, "Easy chat pace. Builds base."),
        ("Z2 Aerobic", 1.20, 1.10, "Comfortable endurance pace."),
        ("Z3 Tempo", 1.10, 1.00, "Comfortably hard. Tempo runs."),
        ("Z4 Threshold", 1.00, 0.92, "Hard. Speed intervals."),
        ("Z5 VO2 Max", 0.92, 0.85, "Very hard. Short reps."),
    ]
    out = []
    for name, hi, lo, desc in zones:
        out.append({"name": name, "hi": fmt_pace(pace_sec_per_km * hi), "lo": fmt_pace(pace_sec_per_km * lo), "desc": desc})
    return out


def fmt_pace(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def get_run_stats():
    conn = get_db()
    runs = conn.execute("SELECT * FROM runs ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    runs = [dict(r) for r in runs]
    total_runs = len(runs)
    total_km = round(sum(r["distance_km"] for r in runs), 1) if runs else 0
    total_sec = sum(r["minutes"] * 60 + r["seconds"] for r in runs)
    avg_pace = fmt_pace(total_sec / total_km) if total_km else "--:--"
    # last 14 days for chart
    labels, data = [], []
    for i in range(13, -1, -1):
        d = (date.today() - timedelta(days=i)).isoformat()
        labels.append(d[5:])
        data.append(round(sum(r["distance_km"] for r in runs if r["date"] == d), 1))
    # streak: consecutive days with a run ending today/yesterday
    dates = sorted(set(r["date"] for r in runs), reverse=True)
    streak = 0
    cursor = date.today()
    date_set = set(dates)
    if cursor.isoformat() not in date_set:
        cursor -= timedelta(days=1)
    while cursor.isoformat() in date_set:
        streak += 1
        cursor -= timedelta(days=1)
    # achievements
    achievements = []
    if total_runs >= 1:
        achievements.append(("🔥", "First Run", "Logged your first run"))
    if total_km >= 42:
        achievements.append(("🏅", "Marathon Volume", "42+ km total"))
    if total_km >= 100:
        achievements.append(("💯", "Century Club", "100+ km total"))
    if streak >= 3:
        achievements.append(("⚡", f"{streak}-Day Streak", "Consistency pays"))
    if any(r["distance_km"] >= 21 for r in runs):
        achievements.append(("🏃", "Half Marathon+", "Logged 21km+"))
    return {"runs": runs, "total_runs": total_runs, "total_km": total_km, "avg_pace": avg_pace,
            "labels": labels, "data": data, "streak": streak, "achievements": achievements}


CHALLENGES = [
    {"id": 1, "emoji": "🌅", "title": "5K Sunrise Sprint", "desc": "Run 5K in one session. Perfect starter challenge.", "target": "5 km", "progress": 68, "joined": 1284},
    {"id": 2, "emoji": "🔥", "title": "50K Monthly Volume", "desc": "Accumulate 50 km this month across all runs.", "target": "50 km", "progress": 42, "joined": 862},
    {"id": 3, "emoji": "🏔️", "title": "10K Breakthrough", "desc": "Complete a single 10K run. Unlock tempo badge.", "target": "10 km", "progress": 55, "joined": 693},
    {"id": 4, "emoji": "⚡", "title": "7-Day Streak", "desc": "Run at least 2 km on 7 consecutive days.", "target": "7 days", "progress": 30, "joined": 451},
    {"id": 5, "emoji": "🏅", "title": "Half Marathon Hero", "desc": "Log 21.1 km in one run. The big one.", "target": "21.1 km", "progress": 18, "joined": 327},
    {"id": 6, "emoji": "🌙", "title": "Night Owl Miles", "desc": "Log 3 evening runs after 8pm this week.", "target": "3 runs", "progress": 74, "joined": 512},
]


@app.route("/")
def home():
    stats = get_run_stats()
    return render_template("index.html", stats=stats, challenges=CHALLENGES[:3])


@app.route("/dashboard")
def dashboard():
    stats = get_run_stats()
    return render_template("dashboard.html", stats=stats)


@app.route("/log", methods=["GET", "POST"])
def log_run():
    if request.method == "POST":
        run_date = request.form.get("date") or date.today().isoformat()
        distance = float(request.form.get("distance", 0))
        minutes = int(request.form.get("minutes", 0))
        seconds = int(request.form.get("seconds", 0))
        notes = request.form.get("notes", "").strip()[:300]
        if distance > 0 and (minutes > 0 or seconds > 0):
            conn = get_db()
            conn.execute("INSERT INTO runs (date, distance_km, minutes, seconds, notes, created_at) VALUES (?,?,?,?,?,?)",
                         (run_date, distance, minutes, seconds, notes, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            return redirect("/dashboard")
    return render_template("log.html", today=date.today().isoformat())


@app.route("/delete-run/<int:run_id>")
def delete_run(run_id):
    conn = get_db()
    conn.execute("DELETE FROM runs WHERE id=?", (run_id,))
    conn.commit()
    conn.close()
    return redirect("/dashboard")


@app.route("/api/chart")
def chart_api():
    stats = get_run_stats()
    return jsonify({"labels": stats["labels"], "data": stats["data"]})


@app.route("/challenges")
def challenges():
    return render_template("challenges.html", challenges=CHALLENGES)


@app.route("/tools", methods=["GET", "POST"])
def tools():
    result = None
    zones = None
    predictions = None
    if request.method == "POST":
        try:
            distance = float(request.form["distance"])
            minutes = int(request.form["minutes"])
            seconds = int(request.form["seconds"])
            pm, ps = calculate_pace(distance, minutes, seconds)
            pace_sec = pm * 60 + ps
            zones = training_zones(pace_sec)
            predictions = {k: predict_race(distance, minutes, seconds, k) for k in (5, 10, 21.0975, 42.195)}
            result = {"distance": distance, "pm": pm, "ps": ps}
        except Exception:
            result = None
    return render_template("tools.html", result=result, zones=zones, predictions=predictions)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        message = request.form["message"]
        connection = sqlite3.connect(DB_PATH)
        connection.execute("INSERT INTO messages (name, email, message) VALUES (?, ?, ?)", (name, email, message))
        connection.commit()
        connection.close()
        return render_template("contact.html", success=True, name=name)
    return render_template("contact.html", success=False)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == "admin" and password == "1234":
            session["logged_in"] = True
            return redirect("/admin")
        return render_template("login.html", error="Incorrect username or password.")
    return render_template("login.html")


@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect("/login")
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    messages = connection.execute("SELECT id, name, email, message FROM messages").fetchall()
    runs = connection.execute("SELECT * FROM runs ORDER BY date DESC").fetchall()
    connection.close()
    return render_template("admin.html", messages=messages, runs=runs)


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect("/login")


@app.route("/delete/<int:id>")
def delete_message(id):
    if not session.get("logged_in"):
        return redirect("/login")
    connection = sqlite3.connect(DB_PATH)
    connection.execute("DELETE FROM messages WHERE id = ?", (id,))
    connection.commit()
    connection.close()
    return redirect("/admin")


@app.route("/guidance")
def guidance():
    return render_template("injury_guidance.html")


@app.route("/beginner", methods=["GET", "POST"])
def beginner():
    if request.method == "POST":
        distance_km = float(request.form["distance"])
        minutes = int(request.form["minutes"])
        seconds = int(request.form["seconds"])
        pace_min, pace_sec = calculate_pace(distance_km, minutes, seconds)
        pace_seconds_per_km = pace_min * 60 + pace_sec
        recommendation = get_recommendation(distance_km, pace_seconds_per_km)
        return render_template("beginner_result.html", distance_km=distance_km, pace_min=pace_min,
                               pace_sec=pace_sec, recommendation=recommendation)
    return render_template("beginner.html")


@app.route("/program")
def program():
    preselect_goal = request.args.get("goal", "5k")
    preselect_days = request.args.get("days", "3")
    return render_template("program.html", preselect_goal=preselect_goal, preselect_days=preselect_days)


@app.route("/generate", methods=["POST"])
def generate():
    goal = request.form["goal"]
    days = int(request.form["days"])
    schedule = generate_plan(goal, days)
    if schedule:
        return render_template("schedule.html", goal=goal.upper(), schedule=schedule)
    return "Sorry, we don't have a program for that combination yet."


create_database()

if __name__ == "__main__":
    app.run(debug=True, port=5000)
