# Publish IAToolkit Community to GHCR

This follows the release mechanism already used by `iatoolkit-bridge`: a local
`release.sh`, Docker Buildx, a public GHCR package, fixed client versions and a
small installation kit. It does not add or change GitHub Actions. The existing
workflow that publishes the Python package to PyPI remains independent.

## Registry, versions and artifacts

- Image: `ghcr.io/iatoolkit/iatoolkit`.
- Version source: `src/iatoolkit/__init__.py`, also used by the installed package
  and `/version`. The Docker distribution does not have a second version counter.
- Publication platforms: `linux/amd64` and `linux/arm64`.
- Image tags: `X.Y.Z`, `MAJOR` and `latest`. Installers use the exact `X.Y.Z` tag.
- Customer Compose: `docker/compose.client.yaml`, with no build context or host
  source mounts. `docker/compose.yaml` is kept for local development.
- Artifact: `docker/dist/iatoolkit-community-X.Y.Z.zip` plus its SHA-256 checksum.
  It includes only Compose, an empty environment template, setup and customer
  instructions. It never includes the developer's `.env`, data volumes or source.

The first image has not been published yet. The current client pin follows the
current source version as a preparation for the dry run; do not advertise that
tag as downloadable until publication and anonymous pull both succeed.

## Prepare a release

From the repository root:

1. Set the next core version in `src/iatoolkit/__init__.py` and the same tag in
   `docker/compose.client.yaml`. Changes after a released core version, including
   the initial Docker work, should get a new version rather than reuse its Git tag.
2. Run the tests and the container checks described in [README.md](README.md):

   ```sh
   uv run pytest
   uv run pytest docker/tests
   ```

3. Build locally without publishing:

   ```sh
   bash docker/release.sh --dry-run
   ```

   This loads the host architecture into Docker and builds the customer ZIP. A
   temporary local tag in the GHCR namespace does not publish anything remotely.
   The image version label must agree with the installed Python package.

4. Commit the tested release files and use the normal package release procedure
   to create/push the matching `vX.Y.Z` tag. This also triggers the existing PyPI
   workflow. The Docker script never commits, creates branches/tags, or pushes Git.

## Publish explicitly

Authenticate once with Docker, using a GitHub token that can publish packages:

```sh
docker login ghcr.io -u <github-user>
```

Use the token as the password prompt; do not put it in shell command arguments
or the kit's `.env`. Docker keeps the login using its configured credential store.

Then run:

```sh
bash docker/release.sh
```

The script requires a clean checkout whose HEAD is the matching `vX.Y.Z` tag.
It checks for registry credentials and refuses to overwrite an existing version.
Network or authorization errors also stop publication: a DNS failure is not
treated as proof that an image tag is available. It builds and pushes both
architectures, then publishes the moving major/latest tags along with the fixed
version. Use `--no-moving-tags` when releasing a patch to an older series:

```sh
bash docker/release.sh --no-moving-tags
```

A version tag is immutable by policy: if a published image needs a correction,
release a new patch. The local script checks for an existing tag before building.

## First publication and verification

The registry package is created by the first successful push. In GitHub's
organization package settings, set `iatoolkit` to **Public**, then confirm:

```sh
docker buildx imagetools inspect ghcr.io/iatoolkit/iatoolkit:X.Y.Z
docker image inspect ghcr.io/iatoolkit/iatoolkit:X.Y.Z \
  --format '{{ index .Config.Labels "org.opencontainers.image.version" }}'
```

The manifest should include both amd64 and arm64. Verify that an installer can
pull without credentials, using an empty temporary Docker config rather than
logging out of your normal session:

```sh
DOCKER_CONFIG=$(mktemp -d) docker pull ghcr.io/iatoolkit/iatoolkit:X.Y.Z
```

Test the four-file kit in an empty directory, outside the source checkout:

```sh
unzip iatoolkit-community-X.Y.Z.zip -d iatoolkit-community
cd iatoolkit-community
sh setup.sh
# Add OPENAI_API_KEY to .env for AI features.
docker compose -f compose.client.yaml pull
docker compose -f compose.client.yaml up -d --wait
```

If a source deployment is already running on port 8080, set another
`IATOOLKIT_PORT` and use `-p iatoolkit-community-kit-test` for every test Compose
command. This keeps its volumes separate from the existing installation.

## Delivering the kit

The bridge mirrors its kit into `iatoolkit-hosted` because its repository is
private. This core repository is public, so the files can instead be downloaded
from a published Git tag, or the ZIP can be attached to a GitHub Release.
Creating a Release, attaching the ZIP and serving a kit from the website are
separate publication steps; `release.sh` only pushes the container image and
prepares the local artifact. No hosted website files are modified here.

The ZIP README is copied from `README.client.md`; the maintainer's documentation,
release script and tests are not part of the customer's kit.
