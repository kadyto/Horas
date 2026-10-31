import io
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from app import create_app
from app.domain import earnings, hours_to_minutes, rate_to_cents


@pytest.fixture
def app(tmp_path):
    return create_app({"DATA_DIR": tmp_path, "APP_PASSWORD": "1234", "TESTING": True})


def token(client):
    with client.session_transaction() as session:
        return session["csrf"]


def login(client):
    client.get("/login")
    return client.post("/login", data={"csrf": token(client), "password": "1234"}, follow_redirects=True)


@pytest.fixture
def client(app):
    client = app.test_client()
    response = login(client)
    assert response.status_code == 200
    return client


def post(client, url, **data):
    return client.post(url, data={"csrf": token(client), **data}, follow_redirects=True)


def backup(client):
    return client.get("/backup.json").json


def revision(app, day):
    with sqlite3.connect(app.config["DATA_DIR"] / "horas.sqlite3") as conn:
        return conn.execute("SELECT revision FROM entries WHERE day=?", (day,)).fetchone()[0]


@pytest.mark.parametrize("password", ["", "123"])
def test_start_requires_minimum_password_length(tmp_path, password):
    with pytest.raises(RuntimeError, match="APP_PASSWORD"):
        create_app({"DATA_DIR": tmp_path, "APP_PASSWORD": password})


def test_routes_are_private_and_csrf_is_enforced(app, client):
    stranger = app.test_client()
    for path in ["/", "/history", "/entry", "/settings", "/export.csv", "/backup.json"]:
        assert stranger.get(path).status_code == 302
    assert client.post("/settings", data={"default_hours": 8, "default_rate": 50}).status_code == 400
    assert backup(client)["settings"] == {"default_minutes": 120, "default_rate_cents": 0}
    response = client.get("/")
    assert "no-store" in response.headers["Cache-Control"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_cookie_security_and_logout(app):
    client = app.test_client()
    response = client.get("/login")
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie
    login(client)
    client.get("/")
    post(client, "/logout")
    assert client.get("/").status_code == 302


def test_login_limiter_survives_new_sessions(app):
    for _ in range(10):
        client = app.test_client()
        client.get("/login")
        response = post(client, "/login", password="incorrecta")
        assert response.status_code == 401
    assert login(app.test_client()).status_code == 429


def test_password_rotation_invalidates_sessions(app, client):
    rotated = create_app({"DATA_DIR": app.config["DATA_DIR"], "APP_PASSWORD": "otra-contraseña-muy-larga", "TESTING": True})
    other = rotated.test_client()
    other.set_cookie("session", client.get_cookie("session").value)
    assert other.get("/").status_code == 302


def test_quick_entry_defaults_and_duplicate_click(client):
    assert "habitual" in client.get("/").text
    for _ in range(2):
        assert post(client, "/entries/quick", day="2026-10-05", hours="2").status_code == 200
    data = backup(client)
    assert data["entries"] == [{"day": "2026-10-05", "minutes": 120, "note": ""}]
    assert client.get("/?month=2026-10").status_code == 200


def test_parallel_quick_click_is_idempotent(app, client):
    cookie = client.get_cookie("session").value
    csrf = token(client)

    def click(_):
        with app.test_client() as c:
            c.set_cookie("session", cookie)
            return c.post("/entries/quick", data={"csrf": csrf, "day": "2026-10-10", "hours": "2"}).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(click, range(4))) == [302] * 4
    assert len(backup(client)["entries"]) == 1


def test_fractional_hours_tariff_history_and_rounding(client):
    post(client, "/settings", default_hours="1,5", default_rate="12,75")
    post(client, "/entries/quick", day="2026-10-05", hours="1.5")
    post(client, "/entries/quick", day="2026-10-06", hours="2")
    page = client.get("/?month=2026-10").text
    assert "44,63 €" in page  # 3.5 * 12.75 = 44.625, rounded half up.
    assert "1,5 h · habitual" in page
    post(client, "/settings", default_hours="3", default_rate="20")
    post(client, "/entries/quick", day="2026-11-01", hours="3")
    data = backup(client)
    assert [m["rate_cents"] for m in data["months"]] == [1275, 2000]
    history = client.get("/history?year=2026").text
    assert "104,63 €" in history and "6,5 h" in history
    assert "60,00 €" in history


@pytest.mark.parametrize("value", ["0", "0.25", "1.1", "24.5", "nan", "Infinity", "-1", "", "<script>"])
def test_invalid_hours_rejected(client, value):
    assert post(client, "/entries/quick", day="2026-10-01", hours=value).status_code == 400
    assert backup(client)["entries"] == []


@pytest.mark.parametrize("value", ["nan", "-0.01", "10000.01", "1.001", "Infinity"])
def test_invalid_rates_rejected(client, value):
    assert post(client, "/month/rate", month="2026-10", rate=value).status_code == 400


@pytest.mark.parametrize("day", ["2026-02-30", "2025-02-29", "2026-13-01", "1999-12-01", "2101-01-01", "26-10-01"])
def test_invalid_dates(client, day):
    assert post(client, "/entries/quick", day=day, hours="2").status_code == 400


def test_leap_year_and_calendar_navigation(client):
    assert post(client, "/entries/quick", day="2028-02-29", hours="0.5").status_code == 200
    page = client.get("/?month=2028-02").text
    assert "2028-02-29" in page and "2028-01" in page and "2028-03" in page
    assert client.get("/?month=2000-01").status_code == 200
    assert client.get("/?month=2100-12").status_code == 200
    assert client.get("/?month=2026-13").status_code == 400


def test_notes_escape_and_edit_conflict(app, client):
    day = "2026-10-05"
    post(client, "/entry", day=day, hours="1.5", note="<script>alert(1)</script>", revision=0)
    rev = revision(app, day)
    page = client.get("/?month=2026-10").text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert post(client, "/entry", day=day, hours="2.5", note="Revisión", revision=rev).status_code == 200
    assert post(client, "/entry", day=day, hours="8", note="Obsoleta", revision=rev).status_code == 409
    assert post(client, "/entries/delete", day=day, revision=rev).status_code == 409
    assert backup(client)["entries"][0]["minutes"] == 150
    assert post(client, "/entries/delete", day=day, revision=revision(app, day)).status_code == 200
    assert backup(client)["entries"] == []


def test_month_payment_resets_only_on_amount_change(app, client):
    day = "2026-10-05"
    post(client, "/month/rate", month="2026-10", rate="15")
    post(client, "/entries/quick", day=day, hours="2")
    assert post(client, "/month/paid", month="2026-10", paid="1", minutes="120", rate_cents="1500").status_code == 200
    assert backup(client)["months"][0]["paid"] == 1
    post(client, "/entry", day=day, hours="2", note="Solo una nota", revision=revision(app, day))
    assert backup(client)["months"][0]["paid"] == 1
    post(client, "/entry", day=day, hours="1.5", note="", revision=revision(app, day))
    assert backup(client)["months"][0]["paid"] == 0
    assert post(client, "/month/paid", month="2026-10", paid="1", minutes="120", rate_cents="1500").status_code == 409


def test_csv_export_and_formula_injection(client):
    post(client, "/month/rate", month="2026-10", rate="10,01")
    post(client, "/entry", day="2026-10-01", hours="0.5", note='=HYPERLINK("bad")', revision=0)
    post(client, "/entries/quick", day="2026-10-02", hours="0.5")
    response = client.get("/export.csv?month=2026-10")
    text = response.data.decode("utf-8-sig")
    assert "attachment" in response.headers["Content-Disposition"]
    assert "10,01" in text and "TOTAL;1;Importe (EUR);10,01" in text
    assert "'=HYPERLINK" in text


def test_backup_restore_is_atomic_and_persistent(app, client):
    post(client, "/settings", default_hours="1.5", default_rate="15.50")
    post(client, "/entry", day="2026-10-01", hours="1.5", note="Prueba", revision=0)
    saved = backup(client)
    assert not any(secret in json.dumps(saved) for secret in ["password", "csrf", "auth"])
    post(client, "/entries/quick", day="2026-10-02", hours="8")
    response = client.post("/restore", data={"csrf": token(client), "confirm": "RESTAURAR", "backup": (io.BytesIO(json.dumps(saved).encode()), "copia.json")}, follow_redirects=True)
    assert response.status_code == 200
    assert backup(client) == saved
    assert (app.config["DATA_DIR"] / "before-restore.sqlite3").exists()
    restarted = create_app({"DATA_DIR": app.config["DATA_DIR"], "APP_PASSWORD": "1234", "TESTING": True})
    with restarted.test_client() as new:
        login(new)
        assert backup(new) == saved


@pytest.mark.parametrize("bad", [None, [], {}, {"format": "horas", "version": 1}, {"format": "horas", "version": True}])
def test_malformed_restore_leaves_data_unchanged(client, bad):
    original = backup(client)
    response = client.post("/restore", data={"csrf": token(client), "confirm": "RESTAURAR", "backup": (io.BytesIO(json.dumps(bad).encode()), "copia.json")})
    assert response.status_code == 400
    assert backup(client) == original


def test_restore_rejects_duplicate_dates(client):
    post(client, "/entries/quick", day="2026-10-01", hours="2")
    original = backup(client)
    invalid = {**original, "entries": original["entries"] * 2}
    response = client.post("/restore", data={"csrf": token(client), "confirm": "RESTAURAR", "backup": (io.BytesIO(json.dumps(invalid).encode()), "copia.json")})
    assert response.status_code == 400
    assert backup(client) == original


def test_restore_invalidates_old_entry_forms(app, client):
    day = "2026-10-01"
    post(client, "/entries/quick", day=day, hours="2")
    old_revision = revision(app, day)
    saved = backup(client)
    response = client.post("/restore", data={"csrf": token(client), "confirm": "RESTAURAR", "backup": (io.BytesIO(json.dumps(saved).encode()), "copia.json")})
    assert response.status_code == 302
    assert post(client, "/entry", day=day, hours="8", note="Obsoleta", revision=old_revision).status_code == 409
    assert backup(client) == saved


def test_exact_money_and_half_hours():
    assert hours_to_minutes("1,5") == 90
    assert rate_to_cents("12,75") == 1275
    assert earnings(210, 1275) == 4463
    assert earnings(60, 1001) == 1001
    assert Decimal(earnings(30, 1001)) == Decimal(501)
