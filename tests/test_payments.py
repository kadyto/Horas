import io
import json
import sqlite3
from pathlib import Path

from app import create_app
from app.domain import week_start, year_weeks
from app.storage import SCHEMA, connect, period_data, settings
from test_app import app, client, post, backup, token


def restore(client, payload):
    return client.post('/restore', data={'csrf': token(client), 'confirm': 'RESTAURAR',
                       'backup': (io.BytesIO(json.dumps(payload).encode()), 'copy.json')}, follow_redirects=True)


def data(app, frequency, key):
    with connect(app.config['DATA_DIR'] / 'horas.sqlite3') as conn:
        return period_data(conn, frequency, key)


def fixture():
    return json.loads((Path(__file__).parent / 'fixtures/payments-v2.json').read_text())


def test_week_crosses_months_and_shared_payment_states(app, client):
    assert restore(client, fixture()).status_code == 200
    week = data(app, 'weekly', '2026-10-26')
    assert (week['minutes'], week['total'], week['paid_total'], week['pending_total']) == (210, 5500, 1500, 4000)
    assert week['mixed_rates'] and week['partial'] and not week['paid']
    response = client.get('/?month=2026-11&week=2026-10-26')
    assert response.status_code == 200 and '55,00 €' in response.text and 'Varias tarifas' in response.text
    assert '26/10/2026' in response.text and '01/11/2026' in response.text
    assert post(client, '/week/paid', week=week['key'], paid='1', signature=week['signature']).status_code == 200
    assert data(app, 'monthly', '2026-10')['paid'] == 1
    november = data(app, 'monthly', '2026-11')
    assert november['partial'] and november['paid_total'] == 4000 and november['pending_total'] == 3000
    assert post(client, '/payment-frequency', payment_frequency='monthly', month='2026-11', week='2026-10-26').status_code == 200
    assert data(app, 'monthly', '2026-11')['total'] == 7000
    assert data(app, 'weekly', '2026-10-26')['paid'] == 1
    november = data(app, 'monthly', '2026-11')
    post(client, '/month/paid', month='2026-11', paid='1', signature=november['signature'])
    assert data(app, 'weekly', '2026-11-02')['paid'] == 1


def test_weekly_rate_only_changes_its_days_and_mode_switch_preserves_rates(app, client):
    restore(client, fixture())
    post(client, '/week/rate', week='2026-10-26', rate='15')
    week = data(app, 'weekly', '2026-10-26')
    assert week['total'] == 5250 and not week['paid'] and not week['partial'] and not week['mixed_rates']
    assert data(app, 'weekly', '2026-11-02')['total'] == 3000
    before = backup(client)['entries']
    for frequency in ['monthly', 'weekly', 'monthly']:
        post(client, '/payment-frequency', payment_frequency=frequency, month='2026-11', week='2026-10-26')
        assert backup(client)['entries'] == before


def test_new_week_inherits_default_without_repricing_previous_entries(app, client):
    restore(client, fixture())
    post(client, '/entries/quick', day='2026-11-03', hours='2')
    assert next(e for e in backup(client)['entries'] if e['day'] == '2026-11-03')['rate_cents'] == 1500
    post(client, '/settings', default_hours='2', default_rate='25', payment_frequency='weekly')
    post(client, '/entries/quick', day='2026-11-10', hours='1.5')
    assert data(app, 'weekly', '2026-11-09')['total'] == 3750
    assert data(app, 'weekly', '2026-11-02')['total'] == 6000


def test_iso_year_and_no_duplicated_days(app, client):
    post(client, '/settings', default_hours='2', default_rate='10', payment_frequency='weekly')
    post(client, '/entries/quick', day='2020-12-31', hours='2')
    post(client, '/entries/quick', day='2021-01-01', hours='1.5')
    assert week_start('2021-01-01') == '2020-12-28'
    assert len(year_weeks(2020)) == 53 and len(year_weeks(2021)) == 52
    assert '2020-12-28' in year_weeks(2020) and '2020-12-28' not in year_weeks(2021)
    assert data(app, 'weekly', '2020-12-28')['total'] == 3500
    assert '35,00 €' in client.get('/history?year=2020').text
    assert '35,00 €' not in client.get('/history?year=2021').text
    assert client.get('/?month=2000-01&week=1999-12-27').status_code == 200
    assert client.get('/?month=2100-12&week=2100-12-27').status_code == 200


def test_old_json_upgrades_paid_and_rates(app, client):
    legacy={'format':'horas','version':1,'settings':{'default_minutes':120,'default_rate_cents':1000},
            'months':[{'month':'2026-10','rate_cents':1275,'paid':1}],
            'entries':[{'day':'2026-10-31','minutes':90,'note':'Legacy'}]}
    assert restore(client, legacy).status_code == 200
    saved = backup(client)
    assert saved['version'] == 2 and saved['settings']['payment_frequency'] == 'monthly'
    assert saved['entries'][0]['rate_cents'] == 1275 and saved['entries'][0]['paid'] == 1
    assert data(app, 'weekly', '2026-10-26')['paid'] == 1
    assert restore(client, saved).status_code == 200 and backup(client) == saved


def test_legacy_sqlite_migration_is_idempotent(tmp_path):
    path=tmp_path/'horas.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO months VALUES('2026-10',1275,1)")
        conn.execute("INSERT INTO entries VALUES('2026-10-31','2026-10',90,'Legacy',7)")
    for _ in range(2):
        create_app({'DATA_DIR':tmp_path,'APP_PASSWORD':'1234','TESTING':True})
        with connect(path) as conn:
            assert settings(conn)['payment_frequency'] == 'monthly'
            summary=period_data(conn,'monthly','2026-10')
            assert summary['total'] == 1913 and summary['paid'] == 1


def test_weekly_csv_and_bad_backup_are_atomic(app, client):
    restore(client, fixture())
    csv=client.get('/export.csv?month=2026-11&week=2026-10-26')
    text=csv.data.decode('utf-8-sig')
    assert '2026-10-31' in text and '2026-11-01' in text and '2026-11-02' not in text
    assert '10,00' in text and '20,00' in text and '55,00' in text
    original=backup(client)
    invalid=json.loads(json.dumps(original));invalid['weeks'].append({'week':'2026-11-03','rate_cents':1000})
    assert restore(client,invalid).status_code == 400 and backup(client) == original
    assert post(client,'/payment-frequency',payment_frequency='bad',month='2026-11').status_code == 400
    week=data(app,'weekly','2026-10-26')
    post(client,'/entries/quick',day='2026-10-30',hours='2')
    assert post(client,'/week/paid',week=week['key'],paid='1',signature=week['signature']).status_code == 409
