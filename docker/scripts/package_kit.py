"""Build the four-file customer kit without credentials or application source."""

import argparse
import ast
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'ghcr.io/iatoolkit/iatoolkit'
FILES = {
    'compose.client.yaml': 'compose.client.yaml',
    '.env.example': '.env.example',
    'setup.sh': 'setup.sh',
    'README.client.md': 'README.md',
}


def release_version(root=ROOT):
    tree = ast.parse((root / 'src/iatoolkit/__init__.py').read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', value):
                return value
    raise ValueError('A stable X.Y.Z __version__ is required.')


def validate_kit(root=ROOT):
    version = release_version(root)
    docker = root / 'docker'
    compose = (docker / 'compose.client.yaml').read_text()
    tags = re.findall(r'^\s+image:\s+(ghcr\.io/iatoolkit/iatoolkit:[^\s]+)\s*$', compose, re.M)
    if tags != [f'{IMAGE}:{version}']:
        raise ValueError('Update docker/compose.client.yaml to ' + f'{IMAGE}:{version}')
    if re.search(r'^\s*build:', compose, re.M):
        raise ValueError('The client Compose must not require a build.')
    template = (docker / '.env.example').read_text()
    for key in ('POSTGRES_PASSWORD', 'OPENAI_API_KEY'):
        if not re.search(rf'^{key}=\s*$', template, re.M):
            raise ValueError('The kit template must contain an empty ' + key)
    for name in FILES:
        if not (docker / name).is_file():
            raise ValueError('Missing kit file: ' + name)
    return version


def package_kit(output, root=ROOT):
    version = validate_kit(root)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f'iatoolkit-community-{version}.zip'
    # Explicit allowlist: never package docker/.env or an application volume.
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for source, target in FILES.items():
            archive.write(root / 'docker' / source, target)
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.zip.sha256').write_text(f'{checksum}  {path.name}\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'docker/dist')
    args = parser.parse_args()
    try:
        if args.check:
            print(validate_kit())
        else:
            print(package_kit(args.output))
    except ValueError as exc:
        raise SystemExit(str(exc))
