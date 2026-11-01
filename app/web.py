import calendar
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

from .domain import (MONTHS, adjacent_month, day_label, day_value,
                     hours_text, hours_to_minutes, money_text, month_label, month_value, rate_to_cents)
from .storage import (connect, ensure_month, initialize, month_data, settings, period_data,
                      entry_rate, set_period_rate, set_period_paid)
from .domain import frequency_value, week_start, week_value, week_label, year_weeks
from .backups import validate_backup


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
        with connect(db_path) as conn:
            frequency = settings(conn)["payment_frequency"] if authorized() else "monthly"
        return {"authenticated": authorized(), "csrf": csrf_token, "today": date.today().isoformat(),
                "current_month": date.today().strftime("%Y-%m"), "version": "1.1.0", "frequency": frequency}

    app.jinja_env.filters.update(hours=hours_text, money=money_text, month_label=month_label, day_label=day_label)
    app.jinja_env.filters["week_label"] = week_label

    def calendar_redirect(day, **extra):
        return redirect(url_for("calendar_page", month=day[:7], week=week_start(day), **extra))

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
            frequency = prefs["payment_frequency"]
            selected_week = week_value(request.args.get("week", week_start(date.today().isoformat() if month == date.today().strftime("%Y-%m") else month + "-01")))
            data = period_data(conn, frequency, selected_week if frequency == "weekly" else month)
            dates = list(calendar.Calendar().itermonthdates(int(month[:4]), int(month[5:])))
            all_entries = {r["day"]: dict(r) for r in conn.execute("SELECT * FROM entries WHERE day BETWEEN ? AND ?", (dates[0].isoformat(), dates[-1].isoformat()))}
        rows = []
        for i in range(0, len(dates), 7):
            cells = [{"day": d.isoformat(), "n": d.day, "in_month": d.strftime("%Y-%m") == month,
                      "allowed": "2000-01-01" <= d.isoformat() <= "2100-12-31"} for d in dates[i:i+7]]
            rows.append({"week": dates[i].isoformat(), "cells": cells})
        start = date.fromisoformat(selected_week)
        prior_week, next_week = (start - timedelta(days=7)).isoformat(), (start + timedelta(days=7)).isoformat()
        selected = request.args.get("hours", hours_text(prefs["default_minutes"]))
        quick_minutes = hours_to_minutes(selected)
        return render_template("calendar.html", active="calendar", month=month, data=data, prefs=prefs,
                               entries=all_entries, rows=rows, selected_week=selected_week,
                               prior_week=prior_week if prior_week >= "1999-12-27" else None,
                               next_week=next_week if next_week <= "2100-12-27" else None,
                               previous=adjacent_month(month, -1), following=adjacent_month(month, 1),
                               total=data["total"], quick_minutes=quick_minutes)

    @app.post("/payment-frequency")
    @protected
    def payment_frequency():
        frequency = frequency_value(request.form.get("payment_frequency"))
        month = month_value(request.form.get("month", date.today().strftime("%Y-%m")))
        selected = week_value(request.form.get("week", week_start(month + "-01")))
        with connect(db_path) as conn:
            conn.execute("UPDATE settings SET payment_frequency=? WHERE id=1", (frequency,))
        flash("Forma de pago actualizada. Se conservan las horas, tarifas y cobros de cada día.", "success")
        return redirect(url_for("calendar_page", month=month, week=selected))

    @app.post("/entries/quick")
    @protected
    def quick_entry():
        day = day_value(request.form.get("day"))
        minutes = hours_to_minutes(request.form.get("hours"))
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            ensure_month(conn, day[:7])
            cents = entry_rate(conn, day)
            cursor = conn.execute("INSERT OR IGNORE INTO entries(day,month,minutes,revision,rate_cents,paid) VALUES (?,?,?,?,?,0)", (day, day[:7], minutes, secrets.randbits(52), cents))
        if not cursor.rowcount:
            flash("Este día ya tenía horas. Puedes editarlas sin duplicar el registro.", "info")
            return redirect(url_for("entry", day=day))
        flash(f"Guardado: {hours_text(minutes).replace('.', ',')} h el {date.fromisoformat(day).day} de {MONTHS[int(day[5:7])]}. Puedes tocar el día para editarlo.", "success")
        return calendar_redirect(day, hours=hours_text(minutes))

    @app.route("/entry", methods=["GET", "POST"])
    @protected
    def entry():
        day = day_value(request.values.get("day", date.today().isoformat()))
        with connect(db_path) as conn:
            row = conn.execute("SELECT * FROM entries WHERE day=?", (day,)).fetchone()
            prefs = settings(conn)
            rate = row["rate_cents"] if row else prefs["default_rate_cents"]
        if request.method == "GET":
            return render_template("entry.html", active="calendar", day=day, entry=dict(row) if row else None,
                                   minutes=row["minutes"] if row else prefs["default_minutes"], rate=rate, day_week=week_start(day))
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
            cents = current["rate_cents"] if current else entry_rate(conn, day)
            conn.execute("""INSERT INTO entries(day,month,minutes,note,revision,rate_cents,paid) VALUES (?,?,?,?,?,?,0)
                         ON CONFLICT(day) DO UPDATE SET paid=CASE WHEN entries.minutes!=excluded.minutes THEN 0 ELSE entries.paid END,
                         minutes=excluded.minutes,note=excluded.note,revision=entries.revision+1""",
                         (day, day[:7], minutes, note, secrets.randbits(52), cents))
        flash("Registro guardado.", "success")
        return calendar_redirect(day)

    @app.post("/entries/delete")
    @protected
    def delete_entry():
        day = day_value(request.form.get("day"))
        revision = request.form.get("revision", "")
        with connect(db_path) as conn:
            cursor = conn.execute("DELETE FROM entries WHERE day=? AND revision=?", (day, revision))
            if not cursor.rowcount:
                return render_template("error.html", message="El registro ha cambiado o ya se ha eliminado. Vuelve al calendario para comprobarlo."), 409
        flash("Registro eliminado.", "success")
        return calendar_redirect(day)

    @app.post("/month/rate")
    @protected
    def month_rate():
        month = month_value(request.form.get("month"))
        cents = rate_to_cents(request.form.get("rate"))
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            set_period_rate(conn, "monthly", month, cents)
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
            try:
                set_period_paid(conn, "monthly", month, int(paid), request.form.get("signature"), request.form.get("minutes"), request.form.get("rate_cents"))
            except ValueError as error:
                return render_template("error.html", message=str(error)), 409
        flash("Mes marcado como cobrado." if paid == "1" else "Mes marcado como pendiente.", "success")
        return redirect(url_for("calendar_page", month=month))

    @app.post("/week/rate")
    @protected
    def week_rate():
        key = week_value(request.form.get("week"))
        cents = rate_to_cents(request.form.get("rate"))
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            set_period_rate(conn, "weekly", key, cents)
        flash("Tarifa aplicada a todos los días de la semana completa.", "success")
        return calendar_redirect(max(key, "2000-01-01"))

    @app.post("/week/paid")
    @protected
    def week_paid():
        key = week_value(request.form.get("week"))
        paid = request.form.get("paid")
        if paid not in ("0", "1"):
            raise ValueError("El estado de cobro no es válido.")
        with connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                set_period_paid(conn, "weekly", key, int(paid), request.form.get("signature"), request.form.get("minutes"), request.form.get("rate_cents"))
            except ValueError as error:
                return render_template("error.html", message=str(error)), 409
        flash("Estado de cobro de la semana actualizado.", "success")
        return calendar_redirect(max(key, "2000-01-01"))

    @app.get("/history")
    @protected
    def history():
        with connect(db_path) as conn:
            frequency = settings(conn)["payment_frequency"]
            default_year = date.today().isocalendar().year if frequency == "weekly" else date.today().year
            raw_year = request.args.get("year", str(default_year))
            minimum = 1999 if frequency == "weekly" else 2000
            if not raw_year.isdecimal() or not minimum <= int(raw_year) <= 2100:
                raise ValueError(f"El año debe estar entre {minimum} y 2100.")
            year = int(raw_year)
            keys = year_weeks(year) if frequency == "weekly" else [f"{year}-{m:02d}" for m in range(1, 13)]
            periods = [period_data(conn, frequency, key) for key in keys]
            years = {date.fromisoformat(row[0]).isocalendar().year if frequency == "weekly" else int(row[0][:4]) for row in conn.execute("SELECT day FROM entries")}
        total = sum(item["total"] for item in periods)
        pending = sum(item["pending_total"] for item in periods)
        return render_template("history.html", active="history", year=year, minimum=minimum,
                               years=sorted(years | {year, default_year}, reverse=True), periods=periods,
                               total=total, pending=pending, minutes=sum(item["minutes"] for item in periods))

    @app.get("/export.csv")
    @protected
    def export_csv():
        month = month_value(request.args.get("month", date.today().strftime("%Y-%m")))
        with connect(db_path) as conn:
            frequency = settings(conn)["payment_frequency"]
            key = week_value(request.args.get("week", week_start(date.today().isoformat() if month == date.today().strftime("%Y-%m") else month + "-01"))) if frequency == "weekly" else month
            data = period_data(conn, frequency, key)
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Fecha", "Horas", "Tarifa (EUR/h)", "Nota", "Día cobrado"])
        for item in data["entries"]:
            note = item["note"]
            if note.lstrip().startswith(("=", "+", "-", "@")) or note.startswith(("\t", "\r", "\n")):
                note = "'" + note
            writer.writerow([item["day"], hours_text(item["minutes"]).replace(".", ","), f"{item['rate_cents'] / 100:.2f}".replace(".", ","), note, "Sí" if item["paid"] else "No"])
        writer.writerow([])
        writer.writerow(["TOTAL", hours_text(data["minutes"]).replace(".", ","), "Importe (EUR)", f"{data['total'] / 100:.2f}".replace(".", ",")])
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="horas-{key}.csv"'})

    @app.route("/settings", methods=["GET", "POST"])
    @protected
    def settings_page():
        if request.method == "POST":
            minutes = hours_to_minutes(request.form.get("default_hours"))
            cents = rate_to_cents(request.form.get("default_rate"))
            with connect(db_path) as conn:
                frequency = frequency_value(request.form.get("payment_frequency", settings(conn)["payment_frequency"]))
                conn.execute("UPDATE settings SET default_minutes=?,default_rate_cents=?,payment_frequency=? WHERE id=1", (minutes, cents, frequency))
            flash("Preferencias guardadas. La tarifa se aplicará a los periodos nuevos.", "success")
            return redirect(url_for("settings_page"))
        with connect(db_path) as conn:
            prefs = settings(conn)
        return render_template("settings.html", active="settings", prefs=prefs)

    @app.get("/backup.json")
    @protected
    def backup():
        with connect(db_path) as conn:
            conn.execute("BEGIN")
            payload = {"format": "horas", "version": 2, "settings": settings(conn),
                       "months": [{"month": row["month"], "rate_cents": row["rate_cents"], "paid": month_data(conn, row["month"])["paid"]} for row in conn.execute("SELECT month,rate_cents FROM months ORDER BY month")],
                       "weeks": [dict(row) for row in conn.execute("SELECT * FROM weeks ORDER BY week")],
                       "entries": [dict(row) for row in conn.execute("SELECT day,minutes,note,rate_cents,paid FROM entries ORDER BY day")]}
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
        prefs, months, weeks, entries = validate_backup(payload)
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
            conn.execute("DELETE FROM weeks")
            conn.execute("UPDATE settings SET default_minutes=?,default_rate_cents=?,payment_frequency=? WHERE id=1", prefs)
            conn.executemany("INSERT INTO months(month,rate_cents,paid) VALUES (?,?,?)", months)
            conn.executemany("INSERT INTO weeks(week,rate_cents) VALUES (?,?)", weeks)
            conn.executemany("INSERT INTO entries(day,month,minutes,note,rate_cents,paid,revision) VALUES (?,?,?,?,?,?,?)", [(*row, secrets.randbits(52)) for row in entries])
        flash("Copia restaurada. Se ha conservado una copia de seguridad previa en el volumen de datos.", "success")
        return redirect(url_for("calendar_page"))

    return app
