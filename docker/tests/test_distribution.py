import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from cryptography.fernet import Fernet
import pytest

from distribution.bootstrap import DATA, NORTHWIND_TABLES, read_snapshot
from distribution.entrypoint import SECRET_NAMES, initialize_state


def test_snapshot_is_the_allowed_northwind_dataset():
    payload, manifest = read_snapshot()
    assert sum(manifest['tables'].values()) == 1303
    assert manifest['tables']['orders'] == 270
    assert manifest['tables']['order_details'] == 855
    created = {
        line.split('"')[3]
        for line in payload.splitlines()
        if line.startswith('CREATE TABLE "public".')
    }
    assert created == set(NORTHWIND_TABLES)
    assert not any(line.startswith('\\') for line in payload.splitlines())
    assert 'OWNER TO' not in payload
    assert 'GRANT ' not in payload
    assert 'render.com' not in payload
    assert 'CREATE ROLE' not in payload
    assert 'iat_users' not in payload


def test_corrupt_archive_is_rejected_before_restore(tmp_path):
    shutil.copy(DATA / 'northwind.manifest.json', tmp_path)
    (tmp_path / 'northwind.sql.gz').write_bytes(b'incomplete download')
    with pytest.raises(RuntimeError, match='archive checksum'):
        read_snapshot(tmp_path)


def test_invalid_sql_checksum_is_rejected(tmp_path):
    archive = gzip.compress(b'SELECT 1;', mtime=0)
    manifest = json.loads((DATA / 'northwind.manifest.json').read_text())
    manifest['archive_sha256'] = hashlib.sha256(archive).hexdigest()
    (tmp_path / 'northwind.sql.gz').write_bytes(archive)
    (tmp_path / 'northwind.manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match='SQL checksum'):
        read_snapshot(tmp_path)


def test_secrets_survive_restarts_and_are_private(tmp_path, monkeypatch):
    for key in SECRET_NAMES:
        monkeypatch.delenv(key, raising=False)
    initialize_state(tmp_path)
    first = {key: os.environ[key] for key in SECRET_NAMES}
    cipher = Fernet(first['FERNET_KEY'].encode())
    encrypted = cipher.encrypt(b'persistent value')
    # A new CLI/web process has no inherited secret variables.
    for key in SECRET_NAMES:
        monkeypatch.delenv(key, raising=False)
    initialize_state(tmp_path)
    assert {key: os.environ[key] for key in SECRET_NAMES} == first
    assert Fernet(os.environ['FERNET_KEY'].encode()).decrypt(encrypted) == b'persistent value'
    assert stat.S_IMODE((tmp_path / 'secrets.json').stat().st_mode) == 0o600
    assert (tmp_path / 'storage').is_dir()


def test_setup_preserves_existing_environment(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for filename in ('setup.sh', '.env.example'):
        shutil.copy(root / filename, tmp_path)
    subprocess.run(['sh', str(tmp_path / 'setup.sh')], check=True, capture_output=True)
    before = (tmp_path / '.env').read_bytes()
    assert b'POSTGRES_PASSWORD=\n' not in before
    assert stat.S_IMODE((tmp_path / '.env').stat().st_mode) == 0o600
    subprocess.run(['sh', str(tmp_path / 'setup.sh')], check=True, capture_output=True)
    assert (tmp_path / '.env').read_bytes() == before
