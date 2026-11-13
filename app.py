"""CampusFix: campus maintenance ticketing on Flask + SQLite."""
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from functools import wraps

from flask import (Flask, abort, after_this_request, flash, g, redirect,
                   render_template, request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from seed import DEMO_ACCOUNTS, seed

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("CAMPUSFIX_DB", os.path.join(BASE, "campusfix.db"))

app = Flask(__name__)
app.secret_key = os.environ.get("CAMPUSFIX_SECRET", "change-this-before-real-use")

STATUSES = ["Reported", "Assigned", "In Progress", "Resolved", "Closed"]
NEXT_STATUS = {"Assigned": "In Progress", "In Progress": "Resolved", "Resolved": "Closed"}
# Which role may move a ticket forward from which current status.
MAY_MOVE = {
    "technician": {"Assigned", "In Progress"},
    "student": {"Resolved"},
    "admin": {"Assigned", "In Progress", "Resolved"},
}


# ---------------------------------------------------------------- database
def connect():
    conn = sqlite3.connect(DB_PATH, isolation_level=None, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    if os.path.exists(DB_PATH):
        return
    conn = connect()
    with open(os.path.join(BASE, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    seed(conn)
    conn.close()


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(db, actor_id=None):
    """BEGIN IMMEDIATE takes the write lock, so two admins cannot interleave."""
    db.execute("BEGIN IMMEDIATE")
    try:
        if actor_id is not None:
            db.execute("UPDATE Audit_Context SET user_id = ? WHERE id = 1", (actor_id,))
        yield
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


# -------------------------------------------------------------------- auth
def current_user():
    if "user" not in g:
        uid = session.get("uid")
        g.user = None if uid is None else get_db().execute(
            "SELECT user_id, name, email, role FROM Users WHERE user_id = ?", (uid,)).fetchone()
    return g.user


@app.context_processor
def inject_user():
    return {"user": current_user(), "STATUSES": STATUSES}


def login_required(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if u is None:
                return redirect(url_for("login"))
            if roles and u["role"] not in roles:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def home_for(role):
    return url_for({"student": "student_home", "technician": "tech_home", "admin": "admin_home"}[role])


@app.route("/")
def home():
    u = current_user()
    return redirect(home_for(u["role"]) if u else url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        row = get_db().execute("SELECT * FROM Users WHERE email = ?", (email,)).fetchone()
        if row and check_password_hash(row["password_hash"], request.form.get("password", "")):
            session.clear()
            session["uid"] = row["user_id"]
            return redirect(home_for(row["role"]))
        flash("Wrong email or password.", "error")
    return render_template("login.html", demo=DEMO_ACCOUNTS)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not name or "@" not in email or len(pw) < 6:
            flash("Enter a name, a valid email and a password of at least 6 characters.", "error")
        else:
            try:
                get_db().execute(
                    "INSERT INTO Users (name, email, password_hash, role) VALUES (?,?,?, 'student')",
                    (name, email, generate_password_hash(pw)))
                flash("Account created. You can sign in now.", "ok")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("That email is already registered.", "error")
    return render_template("register.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- students
@app.route("/student")
@login_required("student")
def student_home():
    rows = get_db().execute(
        "SELECT * FROM v_complaint_detail WHERE student_id = ? "
        "ORDER BY created_at DESC, complaint_id DESC", (current_user()["user_id"],)).fetchall()
    return render_template("list.html", title="My complaints", rows=rows,
                           empty="You have not reported anything yet.", new_button=True)


@app.route("/complaint/new", methods=["GET", "POST"])
@login_required("student")
def new_complaint():
    db = get_db()
    cats = db.execute("SELECT * FROM Categories ORDER BY category_name").fetchall()
    if request.method == "POST":
        loc = request.form.get("location", "").strip()
        desc = request.form.get("description", "").strip()
        try:
            cat = int(request.form.get("category_id", ""))
        except ValueError:
            cat = None
        if not loc or not desc or cat is None:
            flash("Choose a category and fill in the location and description.", "error")
        else:
            try:
                with transaction(db):
                    cid = db.execute(
                        "INSERT INTO Complaints (student_id, category_id, location, description) VALUES (?,?,?,?)",
                        (current_user()["user_id"], cat, loc, desc)).lastrowid
                flash(f"Ticket #{cid} created.", "ok")
                return redirect(url_for("complaint_detail", cid=cid))
            except sqlite3.IntegrityError:
                flash("That category does not exist.", "error")
    return render_template("complaint_form.html", cats=cats)


# ------------------------------------------------------------- technicians
@app.route("/technician")
@login_required("technician")
def tech_home():
    rows = get_db().execute(
        "SELECT * FROM v_complaint_detail WHERE technician_user_id = ? "
        "ORDER BY current_status IN ('Resolved','Closed'), created_at", (current_user()["user_id"],)).fetchall()
    return render_template("list.html", title="Assigned to me", rows=rows,
                           empty="Nothing is assigned to you right now.", show_student=True)


# ------------------------------------------------------------ ticket detail
def load_ticket(cid):
    row = get_db().execute("SELECT * FROM v_complaint_detail WHERE complaint_id = ?", (cid,)).fetchone()
    if row is None:
        abort(404)
    u = current_user()
    allowed = (u["role"] == "admin"
               or (u["role"] == "student" and row["student_id"] == u["user_id"])
               or (u["role"] == "technician" and row["technician_user_id"] == u["user_id"]))
    if not allowed:
        abort(403)
    return row


@app.route("/complaint/<int:cid>")
@login_required()
def complaint_detail(cid):
    t = load_ticket(cid)
    u = current_user()
    history = get_db().execute(
        "SELECT h.*, x.name AS who FROM Status_History h LEFT JOIN Users x ON x.user_id = h.changed_by "
        "WHERE h.complaint_id = ? ORDER BY h.history_id", (cid,)).fetchall()
    nxt = NEXT_STATUS.get(t["current_status"]) if t["current_status"] in MAY_MOVE[u["role"]] else None
    return render_template("complaint.html", t=t, history=history, nxt=nxt)


@app.route("/complaint/<int:cid>/status", methods=["POST"])
@login_required()
def change_status(cid):
    load_ticket(cid)  # authorisation check
    u = current_user()
    db = get_db()
    try:
        with transaction(db, u["user_id"]):
            cur = db.execute("SELECT current_status FROM Complaints WHERE complaint_id = ?", (cid,)).fetchone()["current_status"]
            target = NEXT_STATUS.get(cur)
            if target is None or request.form.get("new_status") != target or cur not in MAY_MOVE[u["role"]]:
                raise ValueError(f"That change is not allowed. The ticket is {cur}.")
            db.execute("UPDATE Complaints SET current_status = ? WHERE complaint_id = ?", (target, cid))
        flash(f"Status changed to {target}.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("complaint_detail", cid=cid))


# -------------------------------------------------------------------- admin
@app.route("/admin")
@login_required("admin")
def admin_home():
    db = get_db()
    flt = request.args.get("status")
    if flt in STATUSES:
        rows = db.execute("SELECT * FROM v_complaint_detail WHERE current_status = ? ORDER BY created_at DESC", (flt,)).fetchall()
    else:
        flt = None
        rows = db.execute("SELECT * FROM v_complaint_detail ORDER BY created_at DESC, complaint_id DESC").fetchall()
    counts = {r["current_status"]: r["n"] for r in db.execute(
        "SELECT current_status, COUNT(*) AS n FROM Complaints GROUP BY current_status")}
    techs = db.execute(
        "SELECT t.technician_id, u.name, t.speciality FROM Technicians t "
        "JOIN Users u ON u.user_id = t.user_id ORDER BY u.name").fetchall()
    return render_template("admin.html", rows=rows, counts=counts, techs=techs, flt=flt)


@app.route("/admin/assign", methods=["POST"])
@login_required("admin")
def assign():
    db = get_db()
    u = current_user()
    try:
        cid = int(request.form["complaint_id"])
        tid = int(request.form["technician_id"])
    except (KeyError, ValueError):
        abort(400)
    try:
        with transaction(db, u["user_id"]):
            row = db.execute("SELECT current_status FROM Complaints WHERE complaint_id = ?", (cid,)).fetchone()
            if row is None:
                raise ValueError("That ticket does not exist.")
            if row["current_status"] != "Reported":
                raise ValueError(f"Ticket #{cid} is already {row['current_status']}. Another admin may have assigned it first.")
            if db.execute("SELECT 1 FROM Technicians WHERE technician_id = ?", (tid,)).fetchone() is None:
                raise ValueError("That technician does not exist.")
            db.execute("INSERT INTO Assignments (complaint_id, technician_id, assigned_by) VALUES (?,?,?)",
                       (cid, tid, u["user_id"]))
            db.execute("UPDATE Complaints SET current_status = 'Assigned' WHERE complaint_id = ?", (cid,))
        flash(f"Ticket #{cid} assigned.", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(request.referrer or url_for("admin_home"))


@app.route("/admin/technicians", methods=["POST"])
@login_required("admin")
def add_technician():
    db = get_db()
    f = request.form
    name, email, pw, spec = (f.get(k, "").strip() for k in ("name", "email", "password", "speciality"))
    if not name or "@" not in email or len(pw) < 6 or not spec:
        flash("Fill in every field; the password needs at least 6 characters.", "error")
        return redirect(url_for("admin_home"))
    try:
        with transaction(db):
            uid = db.execute("INSERT INTO Users (name, email, password_hash, role) VALUES (?,?,?, 'technician')",
                             (name, email.lower(), generate_password_hash(pw))).lastrowid
            db.execute("INSERT INTO Technicians (user_id, speciality) VALUES (?,?)", (uid, spec))
        flash(f"Technician {name} added.", "ok")
    except sqlite3.IntegrityError:
        flash("That email is already registered.", "error")
    return redirect(url_for("admin_home"))


REPORTS = [
    ("Complaints by category", "Join, GROUP BY, ORDER BY",
     """SELECT cat.category_name AS category, COUNT(*) AS total
FROM Complaints c JOIN Categories cat ON cat.category_id = c.category_id
GROUP BY cat.category_id
ORDER BY total DESC"""),
    ("Repeat locations", "GROUP BY with HAVING",
     """SELECT location, COUNT(*) AS complaints
FROM Complaints
GROUP BY location
HAVING COUNT(*) > 1
ORDER BY complaints DESC"""),
    ("Tickets nobody has picked up", "Correlated nested query, NOT EXISTS",
     """SELECT c.complaint_id AS ticket, c.location, c.created_at
FROM Complaints c
WHERE NOT EXISTS (SELECT 1 FROM Assignments a
                  WHERE a.complaint_id = c.complaint_id)
ORDER BY c.created_at"""),
    ("Technician workload", "Outer join, IN, aggregate",
     """SELECT u.name AS technician, t.speciality, COUNT(c.complaint_id) AS active_tickets
FROM Technicians t
JOIN Users u ON u.user_id = t.user_id
LEFT JOIN Assignments a ON a.technician_id = t.technician_id
LEFT JOIN Complaints c ON c.complaint_id = a.complaint_id
     AND c.current_status IN ('Assigned', 'In Progress')
GROUP BY t.technician_id"""),
    ("Average hours to resolve", "Join on the audit trail, AVG",
     """SELECT ROUND(AVG((julianday(h.changed_at) - julianday(c.created_at)) * 24), 1)
       AS avg_hours, COUNT(*) AS resolved_tickets
FROM Complaints c
JOIN Status_History h ON h.complaint_id = c.complaint_id AND h.new_status = 'Resolved'"""),
    ("Categories busier than average", "Nested query in HAVING",
     """SELECT cat.category_name AS category, COUNT(*) AS total
FROM Complaints c JOIN Categories cat ON cat.category_id = c.category_id
GROUP BY cat.category_id
HAVING COUNT(*) > (SELECT AVG(n) FROM
        (SELECT COUNT(*) AS n FROM Complaints GROUP BY category_id))"""),
]


@app.route("/admin/reports")
@login_required("admin")
def reports():
    db = get_db()
    out = []
    for title, concept, sql in REPORTS:
        cur = db.execute(sql)
        out.append({"title": title, "concept": concept, "sql": sql,
                    "cols": [d[0] for d in cur.description], "rows": cur.fetchall()})
    return render_template("reports.html", reports=out)


PLANS = [
    ("Find one student's tickets (indexed column)", "SELECT * FROM Complaints WHERE student_id = 2"),
    ("Filter by status (indexed column)", "SELECT * FROM Complaints WHERE current_status = 'Reported'"),
    ("Search the description text (no index)", "SELECT * FROM Complaints WHERE description LIKE '%fan%'"),
    ("Join tickets to their assignments", "SELECT c.complaint_id, a.technician_id FROM Complaints c JOIN Assignments a ON a.complaint_id = c.complaint_id"),
]


@app.route("/admin/internals")
@login_required("admin")
def internals():
    db = get_db()
    plans = [(label, sql, [r["detail"] for r in db.execute("EXPLAIN QUERY PLAN " + sql)]) for label, sql in PLANS]
    objects = db.execute(
        "SELECT type, name, tbl_name FROM sqlite_master "
        "WHERE type IN ('index','trigger','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    return render_template("internals.html", plans=plans, objects=objects)


@app.route("/admin/backup")
@login_required("admin")
def backup():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    dest = sqlite3.connect(tmp.name)
    get_db().backup(dest)  # consistent snapshot even while the app is running
    dest.close()

    @after_this_request
    def cleanup(resp):
        try:
            os.remove(tmp.name)
        except OSError:
            pass
        return resp
    return send_file(tmp.name, as_attachment=True, download_name="campusfix_backup.db")


@app.errorhandler(403)
def forbidden(_e):
    return render_template("error.html", code=403, msg="You do not have access to this page."), 403


@app.errorhandler(404)
def not_found(_e):
    return render_template("error.html", code=404, msg="That page does not exist."), 404


init_db()

if __name__ == "__main__":
    app.run(debug=True)
