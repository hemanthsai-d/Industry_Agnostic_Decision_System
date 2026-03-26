# CI/CD and Release Packaging

## Workflows

1. CI workflow: `.github/workflows/ci.yml`
- Trigger: pull requests and pushes to `main`
- Runs:
- test suite (`pytest`)
- Docker image build validation (`Dockerfile`, `model_server/Dockerfile`)
- release package smoke build (`scripts/package_release.sh`)

2. Release workflow: `.github/workflows/release.yml`
- Triggers:
- tag push: `v*`
- manual run (`workflow_dispatch`) with `version` input
- Runs:
- release verification gate (static checks + tests + prod preflight sanity)
- release bundle creation (`dist/decision-platform-<version>.tar.gz`)
- Docker image publish to GHCR
- Docker image publish to Docker Hub (when Docker Hub secrets are configured)
- GitHub Release creation for tag-triggered runs

## Published Docker images

GHCR (always):
1. `ghcr.io/<owner>/decision-platform-api:<version>`
2. `ghcr.io/<owner>/decision-model-serving:<version>`

Docker Hub (optional when secrets are set):
1. `docker.io/<dockerhub-username>/decision-platform-api:<version>`
2. `docker.io/<dockerhub-username>/decision-model-serving:<version>`

`latest` is also published for version tags.

## Release bundle

`./scripts/package_release.sh <version>` creates:

1. `dist/decision-platform-<version>.tar.gz`
2. `dist/decision-platform-<version>.sha256`

The tarball includes application code, model server, observability assets, migrations, scripts, and deployment files.
Local development artifacts (`.DS_Store`, `__pycache__`, `*.pyc`, cache folders) are excluded.

## Required repository settings

1. Actions enabled for the repository.
2. Package permissions enabled for GHCR publish.
3. Default `GITHUB_TOKEN` with package write permission (set by workflow permissions).

Docker Hub publish (optional):
1. Add repository secret `DOCKERHUB_USERNAME`.
2. Add repository secret `DOCKERHUB_TOKEN` (recommended: Docker Hub access token).

If these secrets are missing, Docker Hub publish steps are skipped and release continues with GHCR publish.

## Manual local checks

```bash
cd "/Users/hemanthsai/Desktop/decision-platform"
./scripts/package_release.sh v0.1.0-local
ls -la dist/
```
