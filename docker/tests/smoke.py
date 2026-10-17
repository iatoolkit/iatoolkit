"""Run inside the app container; real HTTP, SQL, Redis and local storage, no AI calls."""

import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import sys
import urllib.parse
import urllib.request

import psycopg2
from psycopg2 import sql

from distribution.bootstrap import initialize_database, read_snapshot
from distribution.entrypoint import initialize_state

state_dir = Path(os.environ['IATOOLKIT_DATA_DIR'])
initialize_state(state_dir)
keys_before = (state_dir / 'secrets.json').read_bytes()
initialize_state(state_dir)
assert (state_dir / 'secrets.json').read_bytes() == keys_before

initialize_database()
payload, manifest = read_snapshot()
with psycopg2.connect(os.environ['SAMPLE_DATABASE_URI']) as connection:
    with connection.cursor() as cursor:
        for table, count in manifest['tables'].items():
            cursor.execute(sql.SQL('SELECT count(*) FROM public.{}').format(sql.Identifier(table)))
            assert cursor.fetchone()[0] == count, table
        cursor.execute('SELECT count(*), sum(unit_price * quantity * (1 - discount)) FROM public.order_details')
        result = cursor.fetchone()
        assert result[0] == 855 and result[1] > 0
print('PASS: Northwind row counts, sales SQL and repeated initialization')

session_path = state_dir / '.smoke-session.txt'
cookies = http.cookiejar.LWPCookieJar(str(session_path))
if session_path.exists():
    cookies.load(ignore_discard=True)
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
base = 'http://127.0.0.1:8000'


def request(path, form=None):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    with client.open(base + path, data=data, timeout=30) as response:
        assert response.status == 200
        return response.read()


assert json.loads(request('/healthz'))['status'] == 'ok'
request('/sample_company/home')
request('/sample_company/signup')

# Keep one test account to check that it still logs in after container recreation.
credentials_path = state_dir / '.smoke-user.json'
if credentials_path.exists():
    credentials = json.loads(credentials_path.read_text())
    if session_path.exists():
        assert credentials['email'].encode() in request('/sample_company/account')
        print('PASS: session survives recreation of PostgreSQL, Redis and web containers')
else:
    credentials = {'email': 'docker-smoke@example.invalid', 'password': 'Docker9!' + secrets.token_urlsafe(24)}
    request('/sample_company/signup', {
        **credentials, 'confirm_password': credentials['password'],
        'first_name': 'Docker', 'last_name': 'Smoke', 'lang': 'en',
    })
    credentials_path.touch(mode=0o600)
    credentials_path.write_text(json.dumps(credentials))

# The next target bypasses chat context preparation, so login tests require no LLM.
request('/sample_company/login', {**credentials, 'next': '/sample_company/account', 'lang': 'en'})
assert len(cookies) > 0
assert b'docker-smoke@example.invalid' in request('/sample_company/account')
cookies.save(ignore_discard=True)
print('PASS: real HTTP signup/login, Redis session and persistent user')

from distribution.app import create_app
from iatoolkit.core import current_iatoolkit
from iatoolkit.services.storage_service import StorageService

app = create_app()
with app.app_context():
    storage = current_iatoolkit().get_injector().get(StorageService)
    key = 'companies/sample_company/documents/docker-smoke/persistence.txt'
    try:
        previous = storage.get_document_content('sample_company', key)
        assert previous == b'IAToolkit Docker persistent storage'
        print('PASS: stored document survives container recreation')
    except Exception as exc:
        from iatoolkit.common.exceptions import IAToolkitException
        if not isinstance(exc, IAToolkitException):
            raise
        storage.upload_bytes('sample_company', key, b'IAToolkit Docker persistent storage', 'text/plain')
    assert storage.get_document_content('sample_company', key) == b'IAToolkit Docker persistent storage'
    token = storage.create_download_token('sample_company', key, 'persistence.txt')
    assert app.test_client().get('/download/' + token).data == b'IAToolkit Docker persistent storage'
print('PASS: local document upload/read and signed download')

if '--keep-state' not in sys.argv:
    with psycopg2.connect(os.environ['DATABASE_URI']) as connection:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM iatoolkit.iat_users WHERE email = %s', (credentials['email'],))
    credentials_path.unlink()
    session_path.unlink(missing_ok=True)
    print('Removed the temporary smoke-test account.')
