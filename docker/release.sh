#!/usr/bin/env bash
# Same release mechanism as iatoolkit-bridge: local buildx -> GHCR.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
IMAGE="ghcr.io/iatoolkit/iatoolkit"
BUILDER="iatoolkit-community-builder"
DRY_RUN=false
MOVING_TAGS=true

usage() {
    cat <<'HELP'
Usage: bash docker/release.sh [--dry-run] [--no-moving-tags]

  --dry-run          Build and load the host architecture and create the kit;
                     do not push, tag Git commits or modify GitHub.
  --no-moving-tags   Publish X.Y.Z only, preserving :MAJOR and :latest.
  --help            Show this help.

Version: src/iatoolkit/__init__.py (must match compose.client.yaml).
Publishing needs a clean checkout tagged vX.Y.Z and Docker login to ghcr.io.
HELP
}

for argument in "$@"; do
    case "${argument}" in
        --dry-run) DRY_RUN=true ;;
        --no-moving-tags) MOVING_TAGS=false ;;
        --help|-h) usage; exit 0 ;;
        *) echo "Unknown option: ${argument}" >&2; usage >&2; exit 1 ;;
    esac
done

cd "${ROOT}"
for tool in docker python3; do
    command -v "${tool}" >/dev/null || { echo "Missing required tool: ${tool}" >&2; exit 1; }
done
VERSION="$(python3 docker/scripts/package_kit.py --check)"
MAJOR="${VERSION%%.*}"
docker info >/dev/null
docker buildx version >/dev/null

if [[ "${DRY_RUN}" == true ]]; then
    PLATFORMS="linux/$(docker version --format '{{.Server.Arch}}')"
    OUTPUT=(--load)
    echo "DRY RUN: ${IMAGE}:${VERSION} for ${PLATFORMS}; nothing will be published."
else
    # Publishing must describe a committed, recoverable version. The script
    # deliberately never commits, creates branches/tags, or pushes Git refs.
    if [[ -n "$(git status --porcelain)" ]]; then
        echo 'Commit the release files before publishing. Dry runs allow local changes.' >&2
        exit 1
    fi
    if [[ "$(git rev-parse HEAD)" != "$(git rev-parse "v${VERSION}^{commit}" 2>/dev/null || true)" ]]; then
        echo "HEAD must match the release tag v${VERSION}; this script does not create Git tags." >&2
        exit 1
    fi

    python3 - "${DOCKER_CONFIG:-${HOME}/.docker}/config.json" <<'PY'
import json, sys
try:
    with open(sys.argv[1]) as handle:
        config = json.load(handle)
except (OSError, ValueError):
    config = {}
helper = config.get('credsStore') or config.get('credHelpers', {}).get('ghcr.io')
auth = config.get('auths', {}).get('ghcr.io', {}).get('auth')
if not (helper or auth):
    raise SystemExit('Log in first: docker login ghcr.io -u <github-user> (PAT with write:packages).')
PY
    if probe="$(docker manifest inspect "${IMAGE}:${VERSION}" 2>&1)"; then
        echo "${IMAGE}:${VERSION} already exists. Release a new version instead of overwriting it." >&2
        exit 1
    fi
    # Fail closed. A DNS 'host not found', 403 or a timeout is not evidence
    # that this version tag is available.
    case "${probe}" in
        *"manifest unknown"*|*"MANIFEST_UNKNOWN"*|*"NAME_UNKNOWN"*|*"no such manifest"*) ;;
        *) echo "Unable to confirm that ${IMAGE}:${VERSION} is absent; publication stopped." >&2; exit 1 ;;
    esac
    PLATFORMS='linux/amd64,linux/arm64'
    OUTPUT=(--push)
fi

if ! docker buildx inspect "${BUILDER}" >/dev/null 2>&1; then
    docker buildx create --name "${BUILDER}" --driver docker-container >/dev/null
fi
docker buildx inspect "${BUILDER}" --bootstrap >/dev/null

TAGS=(--tag "${IMAGE}:${VERSION}")
if [[ "${MOVING_TAGS}" == true ]]; then
    TAGS+=(--tag "${IMAGE}:${MAJOR}" --tag "${IMAGE}:latest")
fi

# Create and validate the client artifact before any irreversible push.
python3 docker/scripts/package_kit.py
docker buildx build \
    --builder "${BUILDER}" \
    --platform "${PLATFORMS}" \
    --file docker/Dockerfile \
    --build-arg "VERSION=${VERSION}" \
    "${TAGS[@]}" "${OUTPUT[@]}" .

if [[ "${DRY_RUN}" == true ]]; then
    echo "Built locally: ${IMAGE}:${VERSION}. Kit: docker/dist/iatoolkit-community-${VERSION}.zip"
else
    echo "Published: ${IMAGE}:${VERSION} (${PLATFORMS})."
    echo 'On the first push, make the package public in https://github.com/orgs/iatoolkit/packages'
    echo 'Check anonymous pull using a temporary Docker config; do not log out of your current session:'
    echo "  DOCKER_CONFIG=\$(mktemp -d) docker pull ${IMAGE}:${VERSION}"
fi
