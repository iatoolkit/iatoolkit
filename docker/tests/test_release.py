import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package_kit', ROOT / 'docker/scripts/package_kit.py')
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


def test_client_compose_matches_development_services_without_builds():
    source = yaml.safe_load((ROOT / 'docker/compose.yaml').read_text())
    client = yaml.safe_load((ROOT / 'docker/compose.client.yaml').read_text())
    expected = copy.deepcopy(source)
    version = kit.release_version()
    for service in (expected['x-app'], expected['services']['app'], expected['services']['init']):
        service.pop('build')
        service['image'] = f'{kit.IMAGE}:{version}'
    assert client == expected


def test_customer_zip_is_self_contained_and_contains_no_private_environment(tmp_path):
    path = kit.package_kit(tmp_path)
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {'compose.client.yaml', '.env.example', 'setup.sh', 'README.md'}
        assert b'OPENAI_API_KEY=\n' in archive.read('.env.example')
        assert b'POSTGRES_PASSWORD=\n' in archive.read('.env.example')
        archive.extractall(tmp_path / 'customer')
    subprocess.run(['sh', 'setup.sh'], cwd=tmp_path / 'customer', check=True, capture_output=True)
    assert (tmp_path / 'customer/.env').is_file()
    result = subprocess.run(['sh', 'setup.sh'], cwd=tmp_path / 'customer', check=True, capture_output=True, text=True)
    assert 'already exists' in result.stdout


@pytest.fixture
def release_sandbox(tmp_path):
    root = tmp_path / 'repo'
    (root / 'src/iatoolkit').mkdir(parents=True)
    (root / 'docker/scripts').mkdir(parents=True)
    shutil.copy(ROOT / 'src/iatoolkit/__init__.py', root / 'src/iatoolkit/__init__.py')
    for name in (*kit.FILES, 'release.sh'):
        shutil.copy(ROOT / 'docker' / name, root / 'docker' / name)
    shutil.copy(ROOT / 'docker/scripts/package_kit.py', root / 'docker/scripts/package_kit.py')
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    docker = binaries / 'docker'
    docker.write_text('''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['RELEASE_COMMAND_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['manifest', 'inspect']:
    mode = os.environ.get('RELEASE_PROBE', 'missing')
    if mode == 'existing':
        print('{}'); sys.exit(0)
    print({'missing': 'manifest unknown', 'network': 'lookup ghcr.io: host not found', 'forbidden': '403 Forbidden'}[mode], file=sys.stderr)
    sys.exit(1)
if args[:1] == ['version']:
    print('arm64')
''')
    docker.chmod(0o755)
    git = binaries / 'git'
    git.write_text('''#!/usr/bin/env python3
import os, sys
if sys.argv[1] == 'status':
    print(' M pending.py' if os.environ.get('RELEASE_DIRTY') else '', end='')
else:
    print('different' if os.environ.get('RELEASE_WRONG_TAG') and sys.argv[-1] != 'HEAD' else 'commit-sha')
''')
    git.chmod(0o755)
    config = tmp_path / 'docker-config'
    config.mkdir()
    (config / 'config.json').write_text(json.dumps({'auths': {'ghcr.io': {'auth': 'test-only'}}}))
    env = os.environ.copy()
    env.update(PATH=str(binaries) + os.pathsep + env['PATH'], DOCKER_CONFIG=str(config), RELEASE_COMMAND_LOG=str(tmp_path / 'commands.jsonl'))
    return root, env, tmp_path / 'commands.jsonl'


def run_release(sandbox, *args, **variables):
    root, env, log = sandbox
    result = subprocess.run(['bash', str(root / 'docker/release.sh'), *args], env={**env, **variables}, text=True, capture_output=True)
    commands = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, commands


@pytest.mark.parametrize('probe', ['existing', 'network', 'forbidden'])
def test_publish_stops_for_existing_tags_and_uncertain_registry_state(release_sandbox, probe):
    result, commands = run_release(release_sandbox, RELEASE_PROBE=probe)
    assert result.returncode != 0
    assert not any(command[:2] == ['buildx', 'build'] for command in commands)


@pytest.mark.parametrize('variable', ['RELEASE_DIRTY', 'RELEASE_WRONG_TAG'])
def test_publish_requires_a_clean_matching_release_commit(release_sandbox, variable):
    result, commands = run_release(release_sandbox, **{variable: '1'})
    assert result.returncode != 0
    assert not any(command[:2] == ['manifest', 'inspect'] for command in commands)


def test_dry_run_never_pushes_or_requires_registry_access(release_sandbox):
    result, commands = run_release(release_sandbox, '--no-moving-tags', '--dry-run', RELEASE_DIRTY='1')
    assert result.returncode == 0, result.stderr
    build = next(command for command in commands if command[:2] == ['buildx', 'build'])
    assert '--load' in build and '--push' not in build
    assert build[build.index('--platform') + 1] == 'linux/arm64'
    assert build.count('--tag') == 1
    assert not any(command[:2] == ['manifest', 'inspect'] for command in commands)


@pytest.mark.parametrize('options,tag_count', [((), 3), (('--no-moving-tags',), 1)])
def test_publish_uses_both_platforms_and_requested_tags(release_sandbox, options, tag_count):
    result, commands = run_release(release_sandbox, *options)
    assert result.returncode == 0, result.stderr
    build = next(command for command in commands if command[:2] == ['buildx', 'build'])
    assert '--push' in build and '--load' not in build
    assert build[build.index('--platform') + 1] == 'linux/amd64,linux/arm64'
    assert build.count('--tag') == tag_count
