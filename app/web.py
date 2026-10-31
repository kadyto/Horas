import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import time
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, Response, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.security import check_password_hash, generate_password_hash

from .domain import (MONTHS, adjacent_month, calendar_weeks, day_label, day_value, earnings,
                     hours_text, hours_to_minutes, money_text, month_label, month_value, rate_to_cents)
from .storage import connect, ensure_month, initialize, month_data, settings


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        DATA_DIR=os.getenv("DATA_DIR", "data"),
        APP_PASSWORD=os.getenv("APP_PASSWORD", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    password = app.config.pop("APP_PASSWORD")
    if len(password) < 4 or len(password) > 1024:
        raise RuntimeError("APP_PASSWORD debe tener entre 4 y 1024 caracteres.")
    data_dir = Path(app.config["DATA_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    key_path = data_dir / ".session-key"
    try:
        with key_path.open("xb") as file:
            os.chmod(key_path, 0o600)
            file.write(secrets.token_bytes(32))
    except FileExistsError:
        pass
    # All production workers load the same key before serving traffic.
    key = key_path.read_bytes()
    if len(key) != 32:
        raise RuntimeError("La clave de sesión no es válida. Restaura una copia de .session-key.")
    app.secret_key = key
    password_hash = generate_password_hash(password)
    credential_version = hmac.new(key, password.encode(), hashlib.sha256).hexdigest()
    del password
    db_path = data_dir / "horas.sqlite3"
    initialize(db_path)

    def authorized():
        return hmac.compare_digest(str(session.get("auth", "")), credential_version)

    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return session["csrf"]

    def protected(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if not authorized():
                return redirect(url_for("login"))
            return func(*args, **kwargs)
        return wrapped

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            token = request.form.get("csrf", "")
            if not session.get("csrf") or not hmac.compare_digest(token, session["csrf"]):
                abort(400, "La sesión del formulario ha caducado. Recarga la página e inténtalo de nuevo.")

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def template_context():
        return {"authenticated": authorized(), "csrf": csrf_token, "today": date.today().isoformat(),
                "current_month": date.today().strftime("%Y-%m"), "version": "1.0.2"}

    app.jinja_env.filters.update(hours=hours_text, money=money_text, month_label=month_label, day_label=day_label)

    @app.errorhandler(ValueError)
    def invalid_input(error):
        return render_template("error.html", message=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        messages = {404: "Esta página no existe.", 413: "La copia supera el límite de 2 MB.",
                    405: "Esta acción no está disponible."}
        return render_template("error.html", message=messages.get(error.code, error.description)), error.code

    @app.get("/healthz")
    def health():
        with connect(db_path) as conn:
            conn.execute("SELECT 1 FROM settings").fetchone()
        return {"status": "ok"}

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return redirect(url_for("calendar_page")) if authorized() else render_template("login.html")
        address = request.remote_addr or "unknown"
        bucket = hashlib.sha256(address.encode()).hexdigest()
        now = time.time()
        # Persist the limiter and reserve attempts under a write lock, across workers.
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM login_limits WHERE started < ?", (now - 900,))
            row = conn.execute("SELECT attempts FROM login_limits WHERE bucket=?", (bucket,)).fetchone()
            if row and row["attempts"] >= 10:
                response = app.make_response((render_template("login.html", error="Demasiados intentos. Espera 15 minutos antes de volver a intentarlo."), 429))
                response.headers["Retry-After"] = "900"
                return response
            conn.execute("INSERT INTO login_limits VALUES (?,1,?) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1", (bucket, now))
        supplied = request.form.get("password", "")
        if len(supplied) > 1024 or not check_password_hash(password_hash, supplied):
            return render_template("login.html", error="La contraseña no es correcta."), 401
        with connect(db_path) as conn:
            conn.execute("DELETE FROM login_limits WHERE bucket=?", (bucket,))
        session.clear()
        session["auth"] = credential_version
        session.permanent = True
        return redirect(url_for("calendar_page"))

    @app.post("/logout")
    @protected
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @protected
    def calendar_page():
        month = month_value(request.args.get("month", date.today().strftime("%Y-%m")))
        with connect(db_path) as conn:
            prefs = settings(conn)
            data = month_data(conn, month)
        selected = request.args.get("hours", hours_text(prefs["default_minutes"]))
        quick_minutes = hours_to_minutes(selected)
        return render_template("calendar.html", active="calendar", month=month, data=data, prefs=prefs,
                               entries={e["day"]: e for e in data["entries"]}, weeks=calendar_weeks(month),
                               previous=adjacent_month(month, -1), following=adjacent_month(month, 1),
                               total=earnings(data["minutes"], data["rate_cents"]), quick_minutes=quick_minutes)

    @app.post("/entries/quick")
    @protected
    def quick_entry():
        day = day_value(request.form.get("day"))
        minutes = hours_to_minutes(request.form.get("hours"))
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            ensure_month(conn, day[:7])
            cursor = conn.execute("INSERT OR IGNORE INTO entries(day,month,minutes,revision) VALUES (?,?,?,?)", (day, day[:7], minutes, secrets.randbits(52)))
            if cursor.rowcount:
                conn.execute("UPDATE months SET paid=0 WHERE month=?", (day[:7],))
        if not cursor.rowcount:
            flash("Este día ya tenía horas. Puedes editarlas sin duplicar el registro.", "info")
            return redirect(url_for("entry", day=day))
        flash(f"Guardado: {hours_text(minutes).replace('.', ',')} h el {date.fromisoformat(day).day} de {MONTHS[int(day[5:7])]}. Puedes tocar el día para editarlo.", "success")
        return redirect(url_for("calendar_page", month=day[:7], hours=hours_text(minutes)))

    @app.route("/entry", methods=["GET", "POST"])
    @protected
    def entry():
        day = day_value(request.values.get("day", date.today().isoformat()))
        with connect(db_path) as conn:
            row = conn.execute("SELECT * FROM entries WHERE day=?", (day,)).fetchone()
            prefs = settings(conn)
            rate = month_data(conn, day[:7])["rate_cents"]
        if request.method == "GET":
            return render_template("entry.html", active="calendar", day=day, entry=dict(row) if row else None,
                                   minutes=row["minutes"] if row else prefs["default_minutes"], rate=rate)
        minutes = hours_to_minutes(request.form.get("hours"))
        note = request.form.get("note", "").strip()
        if len(note) > 500:
            raise ValueError("La nota puede tener como máximo 500 caracteres.")
        revision = request.form.get("revision", "0")
        if not revision.isdecimal():
            raise ValueError("La versión del registro no es válida.")
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM entries WHERE day=?", (day,)).fetchone()
            if (current["revision"] if current else 0) != int(revision):
                return render_template("error.html", message="Este día ha cambiado en otra pestaña. Vuelve al calendario y abre el registro para ver la última versión."), 409
            ensure_month(conn, day[:7])
            conn.execute("""INSERT INTO entries(day,month,minutes,note,revision) VALUES (?,?,?,?,?)
                         ON CONFLICT(day) DO UPDATE SET minutes=excluded.minutes,note=excluded.note,revision=entries.revision+1""",
                         (day, day[:7], minutes, note, secrets.randbits(52)))
            if not current or current["minutes"] != minutes:
                conn.execute("UPDATE months SET paid=0 WHERE month=?", (day[:7],))
        flash("Registro guardado.", "success")
        return redirect(url_for("calendar_page", month=day[:7]))

    @app.post("/entries/delete")
    @protected
    def delete_entry():
        day = day_value(request.form.get("day"))
        revision = request.form.get("revision", "")
        with connect(db_path) as conn:
            cursor = conn.execute("DELETE FROM entries WHERE day=? AND revision=?", (day, revision))
            if not cursor.rowcount:
                return render_template("error.html", message="El registro ha cambiado o ya se ha eliminado. Vuelve al calendario para comprobarlo."), 409
            conn.execute("UPDATE months SET paid=0 WHERE month=?", (day[:7],))
        flash("Registro eliminado.", "success")
        return redirect(url_for("calendar_page", month=day[:7]))

    @app.post("/month/rate")
    @protected
    def month_rate():
        month = month_value(request.form.get("month"))
        cents = rate_to_cents(request.form.get("rate"))
        with connect(db_path) as conn:
            ensure_month(conn, month)
            conn.execute("UPDATE months SET paid=CASE WHEN rate_cents != ? THEN 0 ELSE paid END,rate_cents=? WHERE month=?", (cents, cents, month))
        flash("Tarifa del mes actualizada. Los demás meses conservan su tarifa.", "success")
        return redirect(url_for("calendar_page", month=month))

    @app.post("/month/paid")
    @protected
    def month_paid():
        month = month_value(request.form.get("month"))
        paid = request.form.get("paid")
        if paid not in ("0", "1"):
            raise ValueError("El estado de cobro no es válido.")
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            data = month_data(conn, month)
            if not data["entries"]:
                raise ValueError("Añade horas antes de marcar el mes como cobrado.")
            # Do not confirm payment against a stale total from another tab.
            if request.form.get("minutes") != str(data["minutes"]) or request.form.get("rate_cents") != str(data["rate_cents"]):
                return render_template("error.html", message="El total ha cambiado. Revisa el mes antes de marcar el cobro."), 409
            conn.execute("UPDATE months SET paid=? WHERE month=?", (int(paid), month))
        flash("Mes marcado como cobrado." if paid == "1" else "Mes marcado como pendiente.", "success")
        return redirect(url_for("calendar_page", month=month))

    @app.get("/history")
    @protected
    def history():
        raw_year = request.args.get("year", str(date.today().year))
        if not raw_year.isdecimal() or not 2000 <= int(raw_year) <= 2100:
            raise ValueError("El año debe estar entre 2000 y 2100.")
        year = int(raw_year)
        with connect(db_path) as conn:
            years = {int(row[0][:4]) for row in conn.execute("SELECT month FROM months")}
            months = [month_data(conn, f"{year}-{m:02d}") for m in range(1, 13)]
        for item in months:
            item["total"] = earnings(item["minutes"], item["rate_cents"])
        total = sum(item["total"] for item in months)
        pending = sum(item["total"] for item in months if not item["paid"])
        return render_template("history.html", active="history", year=year, years=sorted(years | {year, date.today().year}, reverse=True),
                               months=months, total=total, pending=pending, minutes=sum(item["minutes"] for item in months))

    @app.get("/export.csv")
    @protected
    def export_csv():
        month = month_value(request.args.get("month", date.today().strftime("%Y-%m")))
        with connect(db_path) as conn:
            data = month_data(conn, month)
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Fecha", "Horas", "Tarifa (EUR/h)", "Nota", "Mes cobrado"])
        for item in data["entries"]:
            note = item["note"]
            if note.lstrip().startswith(("=", "+", "-", "@")) or note.startswith(("\t", "\r", "\n")):
                note = "'" + note
            writer.writerow([item["day"], hours_text(item["minutes"]).replace(".", ","), f"{data['rate_cents'] / 100:.2f}".replace(".", ","), note, "Sí" if data["paid"] else "No"])
        writer.writerow([])
        writer.writerow(["TOTAL", hours_text(data["minutes"]).replace(".", ","), "Importe (EUR)", f"{earnings(data['minutes'], data['rate_cents']) / 100:.2f}".replace(".", ",")])
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="horas-{month}.csv"'})

    @app.route("/settings", methods=["GET", "POST"])
    @protected
    def settings_page():
        if request.method == "POST":
            minutes = hours_to_minutes(request.form.get("default_hours"))
            cents = rate_to_cents(request.form.get("default_rate"))
            with connect(db_path) as conn:
                conn.execute("UPDATE settings SET default_minutes=?,default_rate_cents=? WHERE id=1", (minutes, cents))
            flash("Preferencias guardadas. La tarifa se aplicará a los meses nuevos.", "success")
            return redirect(url_for("settings_page"))
        with connect(db_path) as conn:
            prefs = settings(conn)
        return render_template("settings.html", active="settings", prefs=prefs)

    @app.get("/backup.json")
    @protected
    def backup():
        with connect(db_path) as conn:
            conn.execute("BEGIN")
            payload = {"format": "horas", "version": 1, "settings": settings(conn),
                       "months": [dict(row) for row in conn.execute("SELECT month,rate_cents,paid FROM months ORDER BY month")],
                       "entries": [dict(row) for row in conn.execute("SELECT day,minutes,note FROM entries ORDER BY day")]}
        return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype="application/json",
                        headers={"Content-Disposition": f'attachment; filename="horas-copia-{date.today().isoformat()}.json"'})

    @app.post("/restore")
    @protected
    def restore():
        if request.form.get("confirm") != "RESTAURAR":
            raise ValueError("Escribe RESTAURAR para confirmar la sustitución de los datos.")
        upload = request.files.get("backup")
        try:
            payload = json.load(upload) if upload else None
        except (ValueError, UnicodeError):
            raise ValueError("El archivo no es una copia JSON válida.") from None
        prefs, months, entries = validate_backup(payload)
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Preserve a server-side copy before the atomic replacement.
            safety = data_dir / "before-restore.sqlite3"
            with sqlite3.connect(safety) as destination:
                # Use a separate reader: backing up our write transaction would block.
                with sqlite3.connect(db_path) as source:
                    source.backup(destination)
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM months")
            conn.execute("UPDATE settings SET default_minutes=?,default_rate_cents=? WHERE id=1", prefs)
            conn.executemany("INSERT INTO months(month,rate_cents,paid) VALUES (?,?,?)", months)
            conn.executemany("INSERT INTO entries(day,month,minutes,note,revision) VALUES (?,?,?,?,?)", [(*row, secrets.randbits(52)) for row in entries])
        flash("Copia restaurada. Se ha conservado una copia de seguridad previa en el volumen de datos.", "success")
        return redirect(url_for("calendar_page"))

    return app


def validate_backup(payload):
    def integer(value, low, high, step=1):
        if type(value) is not int or not low <= value <= high or value % step:
            raise ValueError("La copia contiene una cantidad no válida.")
        return value

    if not isinstance(payload, dict) or payload.get("format") != "horas" or type(payload.get("version")) is not int or payload.get("version") != 1:
        raise ValueError("La copia no tiene un formato compatible con Horas.")
    try:
        pref = payload["settings"]
        prefs = (integer(pref["default_minutes"], 30, 1440, 30), integer(pref["default_rate_cents"], 0, 1000000))
        if not isinstance(payload["months"], list) or not isinstance(payload["entries"], list) or len(payload["months"]) > 1212 or len(payload["entries"]) > 37000:
            raise ValueError("La copia contiene demasiados registros o un formato incorrecto.")
        months, entries, seen_months, seen_days = [], [], set(), set()
        for row in payload["months"]:
            month = month_value(row["month"])
            if month in seen_months:
                raise ValueError("La copia contiene meses duplicados.")
            seen_months.add(month)
            months.append((month, integer(row["rate_cents"], 0, 1000000), integer(row["paid"], 0, 1)))
        for row in payload["entries"]:
            day = day_value(row["day"])
            if day in seen_days or day[:7] not in seen_months:
                raise ValueError("La copia contiene días duplicados o sin mes asociado.")
            note = row["note"]
            if not isinstance(note, str) or len(note) > 500:
                raise ValueError("La copia contiene una nota no válida.")
            seen_days.add(day)
            entries.append((day, day[:7], integer(row["minutes"], 30, 1440, 30), note))
        return prefs, months, entries
    except (KeyError, TypeError):
        raise ValueError("La copia está incompleta o tiene un formato incorrecto.") from None
