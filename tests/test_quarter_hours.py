import io
import json
import sqlite3
from pathlib import Path

import pytest

from app import create_app
from app.domain import hours_to_minutes
from app.storage import connect, period_data
from test_app import app, client, post, backup, token, login


@pytest.mark.parametrize('hours,minutes', [('0.25',15),('0,75',45),('1.25',75),('23.75',1425),('24',1440)])
def test_quarter_hours_save_to_sqlite(client, hours, minutes):
    assert post(client,'/entries/quick',day='2026-11-02',hours=hours).status_code == 200
    assert backup(client)['entries'][0]['minutes'] == minutes
    assert hours_to_minutes(hours) == minutes


def test_quarter_default_weekly_totals_csv_and_backup(app, client):
    assert post(client,'/settings',default_hours='0.25',default_rate='12,75',payment_frequency='weekly').status_code == 200
    for day,hours in [('2026-11-02','0.25'),('2026-11-03','0.75'),('2026-11-04','1.25')]:
        assert post(client,'/entries/quick',day=day,hours=hours).status_code == 200
    with connect(app.config['DATA_DIR']/'horas.sqlite3') as conn:
        week=period_data(conn,'weekly','2026-11-02')
    assert week['minutes']==135 and week['total']==2869
    csv=client.get('/export.csv?month=2026-11&week=2026-11-02').data.decode('utf-8-sig')
    assert '0,25' in csv and '0,75' in csv and '1,25' in csv and '28,69' in csv
    original=backup(client)
    response=client.post('/restore',data={'csrf':token(client),'confirm':'RESTAURAR','backup':(io.BytesIO(json.dumps(original).encode()),'copy.json')})
    assert response.status_code==302 and backup(client)==original
    assert backup(client)['settings']['default_minutes']==15


def test_legacy_thirty_minute_constraints_are_rebuilt_without_data_loss(tmp_path):
    path=tmp_path/'horas.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.executescript("""
          CREATE TABLE settings(id INTEGER PRIMARY KEY,default_minutes INTEGER CHECK(default_minutes BETWEEN 30 AND 1440 AND default_minutes%30=0),default_rate_cents INTEGER,payment_frequency TEXT);
          INSERT INTO settings VALUES(1,90,2000,'weekly');
          CREATE TABLE months(month TEXT PRIMARY KEY,rate_cents INTEGER,paid INTEGER);
          INSERT INTO months VALUES('2026-11',1000,1);
          CREATE TABLE weeks(week TEXT PRIMARY KEY,rate_cents INTEGER);
          INSERT INTO weeks VALUES('2026-11-02',1800);
          CREATE TABLE entries(day TEXT PRIMARY KEY,month TEXT REFERENCES months(month),minutes INTEGER CHECK(minutes BETWEEN 30 AND 1440 AND minutes%30=0),note TEXT,revision INTEGER,rate_cents INTEGER,paid INTEGER);
          INSERT INTO entries VALUES('2026-11-02','2026-11',90,'Registro conservado',88,1275,1);
          CREATE INDEX entries_month ON entries(month);
        """)
    for _ in range(2):
        migrated=create_app({'DATA_DIR':tmp_path,'APP_PASSWORD':'1234','TESTING':True})
        with connect(path) as conn:
            row=dict(conn.execute('SELECT * FROM entries').fetchone())
            assert row=={'day':'2026-11-02','month':'2026-11','minutes':90,'note':'Registro conservado','revision':88,'rate_cents':1275,'paid':1}
            assert conn.execute('PRAGMA foreign_key_check').fetchone() is None
            assert conn.execute("SELECT payment_frequency FROM settings").fetchone()[0]=='weekly'
    c=migrated.test_client();login(c)
    assert post(c,'/settings',default_hours='0.25',default_rate='20',payment_frequency='weekly').status_code==200
    assert post(c,'/entries/quick',day='2026-11-03',hours='0.25').status_code==200
    saved=backup(c)
    assert saved['entries'][0]['paid']==1 and saved['entries'][0]['rate_cents']==1275
    assert saved['entries'][1]['minutes']==15 and saved['entries'][1]['rate_cents']==1800
    with connect(path) as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute('UPDATE entries SET minutes=20')


def test_quarter_controls_and_invalid_non_quarter_values(client):
    page=client.get('/entry?day=2026-11-02').text
    assert 'step="0.25"' in page and 'min="0.25"' in page and 'Añadir 15 minutos' in page
    calendar=client.get('/?month=2026-11').text
    assert 'value="0.25"' in calendar and 'value="0.75"' in calendar and 'value="1.25"' in calendar
    for value in ['0.1','0.3','0.3333333333','24.25']:
        assert post(client,'/entries/quick',day='2026-11-02',hours=value).status_code==400


def test_shared_android_quarter_hour_fixture(app, client):
    payload=json.loads((Path(__file__).parent/'fixtures/quarter-hours-v2.json').read_text())
    response=client.post('/restore',data={'csrf':token(client),'confirm':'RESTAURAR','backup':(io.BytesIO(json.dumps(payload).encode()),'copy.json')})
    assert response.status_code==302 and backup(client)==payload
    with connect(app.config['DATA_DIR']/'horas.sqlite3') as conn:
        week=period_data(conn,'weekly','2026-11-02')
    assert (week['minutes'],week['total'],week['paid_total'],week['pending_total'])==(135,2869,319,2550)
