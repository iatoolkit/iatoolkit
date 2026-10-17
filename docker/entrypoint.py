"""Persist generated secrets outside the image and never load a host .env file."""

import base64
import fcntl
import json
import os
from pathlib import Path
import secrets
import sys

SECRET_NAMES = ('FLASK_SECRET_KEY', 'IATOOLKIT_SECRET_KEY', 'FERNET_KEY')


def initialize_state(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'storage').mkdir(exist_ok=True)
    # init, CLI and web can all start against the same volume.
    with (directory / '.secrets.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / 'secrets.json'
        values = json.loads(path.read_text()) if path.exists() else {}
        for name in SECRET_NAMES:
            if name not in values:
                values[name] = (
                    base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
                    if name == 'FERNET_KEY' else secrets.token_hex(32)
                )
        temporary = directory / '.secrets.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(values, handle)
        temporary.replace(path)
        for name in SECRET_NAMES:
            # Keep persisted values authoritative across web and one-off commands.
            os.environ[name] = values[name]


if __name__ == '__main__':
    initialize_state(Path(os.environ.get('IATOOLKIT_DATA_DIR', '/var/lib/iatoolkit')))
    if len(sys.argv) < 2:
        raise SystemExit('A command is required.')
    os.execvp(sys.argv[1], sys.argv[1:])
