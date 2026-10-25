import os, re, sqlite3
from datetime import datetime, date, timedelta, timezone
from functools import wraps
from flask import Flask, g, request, session, redirect, url_for, render_template, flash, abort, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

DB = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "request-system.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
  pw TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'requestor', department TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL,
  kind TEXT NOT NULL, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
  resource_id INTEGER NOT NULL, department TEXT, activity TEXT NOT NULL,
  start_at TEXT NOT NULL, end_at TEXT NOT NULL, participants INTEGER DEFAULT 0,
  equipment TEXT DEFAULT '', remarks TEXT DEFAULT '', status TEXT DEFAULT 'pending',
  decided_by INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS ix_req ON requests(resource_id, start_at);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, request_id INTEGER, title TEXT NOT NULL,
  body TEXT DEFAULT '', created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS event_dismissed(user_id INTEGER NOT NULL, event_id INTEGER NOT NULL,
  PRIMARY KEY(user_id, event_id));
"""


def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB, isolation_level=None, timeout=10)
        g.db.row_factory = sqlite3.Row
    return g.db


def _t12(v):
    h, m = int(v[-5:-3]), v[-2:]
    return f"{(h % 12) or 12}:{m} {'AM' if h < 12 else 'PM'}"


@app.template_filter("t12")
def t12(v):
    return _t12(v)


@app.template_filter("dt12")
def dt12(v):
    return f"{v[5:7]}/{v[8:10]}/{v[:4]} " + _t12(v)


@app.template_filter("local12")
def local12(v):
    if not v:
        return ""
    d = datetime.fromisoformat(v).replace(tzinfo=timezone.utc).astimezone()  # stored as UTC
    return f"{d:%m/%d/%Y} {(d.hour % 12) or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'}"


@app.after_request
def no_cache(r):
    if request.endpoint != "static":
        r.headers["Cache-Control"] = "no-store"
    return r


@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d:
        d.close()


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    if c.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:  # first run only
        c.execute("INSERT OR IGNORE INTO users(username,pw,role,department) VALUES('admin',?, 'admin','Admin')",
                  (generate_password_hash(os.environ.get("ADMIN_PASSWORD", "Admin2026!")),))
        for n, k in [("Conference Room", "room"), ("Training Room", "room"), ("Van 1", "vehicle")]:
            c.execute("INSERT OR IGNORE INTO resources(name,kind) VALUES(?,?)", (n, k))
    c.commit(); c.close()


def login_required(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if "uid" not in session:
                return redirect(url_for("login"))
            if roles and session["role"] not in roles:
                abort(403)
            return f(*a, **k)
        return w
    return deco


def conflict(rid, s, e, exclude=0):
    return db().execute(
        "SELECT 1 FROM requests WHERE resource_id=? AND status IN('pending','approved') "
        "AND start_at<? AND end_at>? AND id!=?", (rid, e, s, exclude)).fetchone()


def notify(rid, title):
    """Record a notification (shown to every logged-in user by the browser poller)."""
    r = db().execute(LIST_SQL + "WHERE r.id=?", (rid,)).fetchone()
    if not r:
        return
    body = (f"{r['rname']} - {dt12(r['start_at'])} to {_t12(r['end_at'])}\n{r['activity']}\n"
            f"Requested by {r['username']} ({r['department']})")
    if r["status"] != "pending" and r["decider"]:
        body += f"\nStatus: {r['status'].capitalize()} by {r['decider']}"
    else:
        body += f"\nStatus: {r['status'].capitalize()}"
    db().execute("DELETE FROM events WHERE created<datetime('now','-7 days')")
    db().execute("DELETE FROM event_dismissed WHERE event_id NOT IN (SELECT id FROM events)")
    db().execute("INSERT INTO events(request_id,title,body) VALUES(?,?,?)", (rid, title, body))


def unread_count():
    return db().execute("SELECT COUNT(*) n FROM events e WHERE NOT EXISTS(SELECT 1 FROM event_dismissed d "
                        "WHERE d.event_id=e.id AND d.user_id=?)", (session["uid"],)).fetchone()["n"]


@app.route("/events")
def events():
    if "uid" not in session:
        return jsonify(error="login"), 401
    c = db()
    newest = c.execute("SELECT COALESCE(MAX(id),0) m FROM events").fetchone()["m"]
    after = request.args.get("after", type=int)
    if after is None:  # first visit: set a baseline so old events are not replayed as pop-ups
        return jsonify(last=newest, events=[], unread=unread_count())
    rows = c.execute("SELECT id,title,body FROM events WHERE id>? "
                     "AND created>=datetime('now','-10 minutes') ORDER BY id LIMIT 20", (after,)).fetchall()
    last = rows[-1]["id"] if len(rows) == 20 else newest
    return jsonify(last=last, events=[dict(r) for r in rows], unread=unread_count())


@app.route("/notifications")
def notifications():
    """Notifications this user has not closed yet (newest first) for the bell panel."""
    if "uid" not in session:
        return jsonify(error="login"), 401
    rows = db().execute("SELECT e.id,e.title,e.body,e.created FROM events e WHERE NOT EXISTS("
                        "SELECT 1 FROM event_dismissed d WHERE d.event_id=e.id AND d.user_id=?) "
                        "ORDER BY e.id DESC LIMIT 50", (session["uid"],)).fetchall()
    return jsonify(items=[dict(r) for r in rows], unread=unread_count())


@app.route("/events/<int:eid>/dismiss", methods=["POST"])
def dismiss_event(eid):
    if "uid" not in session:
        return jsonify(error="login"), 401
    db().execute("INSERT OR IGNORE INTO event_dismissed(user_id,event_id) VALUES(?,?)", (session["uid"], eid))
    return jsonify(unread=unread_count())


@app.route("/sw.js")
def service_worker():
    return app.send_static_file("sw.js"), 200, {"Content-Type": "application/javascript"}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = db().execute("SELECT * FROM users WHERE username=?", (request.form["username"],)).fetchone()
        if u and check_password_hash(u["pw"], request.form["password"]):
            session.update(uid=u["id"], role=u["role"], name=u["username"], dept=u["department"])
            return redirect(url_for("calendar"))
        flash("Invalid username or password")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def calendar():
    d = request.args.get("d") or date.today().isoformat()
    start = datetime.fromisoformat(d).date()
    v = "month" if request.args.get("v") == "month" else "week"
    if v == "month":
        start = start.replace(day=1)
        nxt_m = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        days = [start + timedelta(days=i) for i in range((nxt_m - start).days)]
        prev, nxt = (start - timedelta(days=1)).replace(day=1).isoformat(), nxt_m.isoformat()
    else:
        days = [start + timedelta(days=i) for i in range(7)]
        prev, nxt = (start - timedelta(days=7)).isoformat(), (start + timedelta(days=7)).isoformat()
    res = db().execute("SELECT * FROM resources WHERE active=1 ORDER BY kind,name").fetchall()
    rows = db().execute(
        "SELECT r.*, u.username, d.username AS decider FROM requests r JOIN users u ON u.id=r.user_id "
        "LEFT JOIN users d ON d.id=r.decided_by "
        "WHERE status IN('pending','approved') AND start_at>=? AND start_at<? ORDER BY start_at",
        (days[0].isoformat(), (days[-1] + timedelta(days=1)).isoformat())).fetchall()
    cal = {}
    for r in rows:
        cal.setdefault((r["resource_id"], r["start_at"][:10]), []).append(r)
    return render_template("calendar.html", days=days, res=res, cal=cal, d=start,
                           prev=prev, nxt=nxt, v=v)


@app.route("/request", methods=["GET", "POST"])
@login_required()
def new_request():
    res = db().execute("SELECT * FROM resources WHERE active=1 ORDER BY kind,name").fetchall()
    if request.method == "POST":
        f = request.form
        s, e = f"{f['date']}T{f['start']}", f"{f['date']}T{f['end']}"
        if e <= s:
            flash("End time must be after start time")
        else:
            c = db()
            c.execute("BEGIN IMMEDIATE")
            if not c.execute("SELECT 1 FROM resources WHERE id=? AND active=1", (f["resource_id"],)).fetchone():
                c.execute("ROLLBACK")
                flash("That item is no longer available. Please choose another.")
            elif conflict(f["resource_id"], s, e):
                c.execute("ROLLBACK")
                flash("That slot is already reserved or pending for this resource")
            else:
                cur = c.execute("INSERT INTO requests(user_id,resource_id,department,activity,start_at,end_at,"
                          "participants,equipment,remarks) VALUES(?,?,?,?,?,?,?,?,?)",
                          (session["uid"], f["resource_id"], f["department"], f["activity"], s, e,
                           f.get("participants") or 0, f.get("equipment", ""), f.get("remarks", "")))
                rid = cur.lastrowid
                c.execute("COMMIT")
                notify(rid, "New request submitted")
                flash("Request submitted and awaiting approval")
                return redirect(url_for("my_requests"))
    return render_template("form.html", res=res, today=date.today().isoformat())


LIST_SQL = ("SELECT r.*, s.name AS rname, s.kind, u.username, d.username AS decider FROM requests r "
            "JOIN resources s ON s.id=r.resource_id JOIN users u ON u.id=r.user_id "
            "LEFT JOIN users d ON d.id=r.decided_by ")


@app.route("/my")
@login_required()
def my_requests():
    rows = db().execute(LIST_SQL + "WHERE r.user_id=? ORDER BY r.start_at DESC", (session["uid"],)).fetchall()
    return render_template("list.html", rows=rows, title="My requests", manage=False)


@app.route("/all")
@login_required()
def all_requests():
    rows = db().execute(LIST_SQL + "ORDER BY r.start_at DESC LIMIT 300").fetchall()
    return render_template("list.html", rows=rows, title="All requests", manage=False)


@app.route("/approvals")
@login_required("approver", "admin")
def approvals():
    rows = db().execute(LIST_SQL + "WHERE r.status='pending' ORDER BY r.start_at").fetchall()
    return render_template("list.html", rows=rows, title="Pending approvals", manage=True)


@app.route("/action/<int:rid>/<act>", methods=["POST"])
@login_required()
def action(rid, act):
    r = db().execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone() or abort(404)
    staff = session["role"] in ("approver", "admin")
    if act == "cancel" and (r["user_id"] == session["uid"] or staff):
        new = "cancelled"
    elif act in ("approve", "reject") and staff:
        new = "approved" if act == "approve" else "rejected"
    else:
        abort(403)
    db().execute("UPDATE requests SET status=?, decided_by=? WHERE id=?", (new, session["uid"], rid))
    notify(rid, f"Request {new}")
    return redirect(request.referrer or url_for("my_requests"))


@app.route("/admin/requests/<int:rid>/delete", methods=["POST"])
@login_required("admin")
def delete_request(rid):
    db().execute("DELETE FROM requests WHERE id=?", (rid,))
    flash("Request deleted")
    return redirect(request.referrer or url_for("all_requests"))


@app.route("/admin/requests/purge", methods=["POST"])
@login_required("admin")
def purge_requests():
    before = request.form.get("before", "")
    if not before or before > date.today().isoformat():
        flash("Choose a date that is today or earlier")
    else:
        n = db().execute("DELETE FROM requests WHERE end_at<?", (before + "T00:00",)).rowcount
        flash(f"Deleted {n} request(s) that ended before {datetime.fromisoformat(before):%m/%d/%Y}")
    return redirect(url_for("admin"))


@app.route("/admin")
@login_required("admin")
def admin():
    q = lambda s, *a: db().execute(s, a).fetchall()
    today, month = date.today().isoformat(), date.today().strftime("%Y-%m")
    return render_template(
        "admin.html", today_date=date.today().isoformat(),
        today=q(LIST_SQL + "WHERE r.status='approved' AND r.start_at LIKE ? ORDER BY r.start_at", today + "%"),
        pending=q("SELECT COUNT(*) n FROM requests WHERE status='pending'")[0]["n"],
        upcoming=q(LIST_SQL + "WHERE r.status='approved' AND r.start_at>? ORDER BY r.start_at LIMIT 10",
                   datetime.now().strftime("%Y-%m-%dT%H:%M")),
        util=q("SELECT s.name, ROUND(COALESCE(SUM((julianday(r.end_at)-julianday(r.start_at))*24),0),1) h "
               "FROM resources s LEFT JOIN requests r ON r.resource_id=s.id AND r.status='approved' "
               "AND r.start_at LIKE ? GROUP BY s.id ORDER BY h DESC", month + "%"),
        dept=q("SELECT department, status, COUNT(*) n FROM requests GROUP BY department, status "
               "ORDER BY department"),
        resources=q("SELECT * FROM resources ORDER BY kind,name"),
        users=q("SELECT * FROM users ORDER BY username"))


def pw_error(p):
    if len(p) < 8:
        return "Password must be at least 8 characters"
    if not (re.search(r"[A-Za-z]", p) and re.search(r"\d", p) and re.search(r"[^A-Za-z0-9\s]", p)):
        return "Password must contain letters, numbers and at least one special character (for example @ # $ !)"
    return None


def admins_left(excl):
    return db().execute("SELECT COUNT(*) n FROM users WHERE role='admin' AND id!=?", (excl,)).fetchone()["n"]


@app.route("/admin/users", methods=["GET", "POST"])
@login_required("admin")
def users():
    if request.method == "POST":
        f = request.form
        if pw_error(f["password"]):
            flash(pw_error(f["password"]))
            return redirect(url_for("users"))
        try:
            db().execute("INSERT INTO users(username,pw,role,department) VALUES(?,?,?,?)",
                         (f["username"].strip(), generate_password_hash(f["password"]), f["role"], f["department"]))
            flash("User added")
        except sqlite3.IntegrityError:
            flash("Username already exists")
        return redirect(url_for("users"))
    return render_template("users.html", rows=db().execute("SELECT * FROM users ORDER BY username").fetchall())


@app.route("/admin/users/<int:uid>/edit", methods=["GET", "POST"])
@login_required("admin")
def edit_user(uid):
    u = db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() or abort(404)
    if request.method == "POST":
        f = request.form
        if u["role"] == "admin" and f["role"] != "admin" and not admins_left(uid):
            flash("At least one admin is required")
            return redirect(request.url)
        if f["password"] and pw_error(f["password"]):
            flash(pw_error(f["password"]))
            return redirect(request.url)
        pw = generate_password_hash(f["password"]) if f["password"] else u["pw"]
        try:
            db().execute("UPDATE users SET username=?,pw=?,role=?,department=? WHERE id=?",
                         (f["username"].strip(), pw, f["role"], f["department"], uid))
        except sqlite3.IntegrityError:
            flash("Username already exists")
            return redirect(request.url)
        if uid == session["uid"]:
            session.update(role=f["role"], name=f["username"].strip(), dept=f["department"])
        flash("User updated")
        return redirect(url_for("users"))
    return render_template("edit_user.html", u=u)


@app.route("/admin/users/<int:uid>/delete", methods=["POST"])
@login_required("admin")
def delete_user(uid):
    if uid == session["uid"]:
        flash("You cannot delete your own account")
    else:
        db().execute("DELETE FROM requests WHERE user_id=?", (uid,))
        db().execute("DELETE FROM users WHERE id=?", (uid,))
        flash("User deleted")
    return redirect(url_for("users"))


@app.route("/admin/resources", methods=["GET", "POST"])
@login_required("admin")
def resources():
    if request.method == "POST":
        try:
            db().execute("INSERT INTO resources(name,kind) VALUES(?,?)",
                         (request.form["name"].strip(), request.form["kind"]))
            flash("Added")
        except sqlite3.IntegrityError:
            flash("A resource with that name already exists")
        return redirect(url_for("resources"))
    return render_template("resources.html",
                           rows=db().execute("SELECT * FROM resources ORDER BY kind,name").fetchall())


@app.route("/admin/resources/<int:rid>/edit", methods=["GET", "POST"])
@login_required("admin")
def edit_resource(rid):
    r = db().execute("SELECT * FROM resources WHERE id=?", (rid,)).fetchone() or abort(404)
    if request.method == "POST":
        f = request.form
        try:
            db().execute("UPDATE resources SET name=?,kind=?,active=? WHERE id=?",
                         (f["name"].strip(), f["kind"], 1 if f.get("active") else 0, rid))
        except sqlite3.IntegrityError:
            flash("A resource with that name already exists")
            return redirect(request.url)
        flash("Saved")
        return redirect(url_for("resources"))
    return render_template("edit_resource.html", r=r)


@app.route("/admin/resources/<int:rid>/delete", methods=["POST"])
@login_required("admin")
def delete_resource(rid):
    db().execute("DELETE FROM requests WHERE resource_id=?", (rid,))
    db().execute("DELETE FROM resources WHERE id=?", (rid,))
    flash("Deleted")
    return redirect(url_for("resources"))


init_db()


if __name__ == "__main__":  # local testing: python app.py
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5051)), debug=True)
