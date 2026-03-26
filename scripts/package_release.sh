#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || -z "${1:-}" ]]; then
  echo "Usage: $0 <version>"
  exit 1
fi

VERSION="$1"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
PKG_NAME="decision-platform-${VERSION}"
PKG_DIR="${DIST_DIR}/${PKG_NAME}"

mkdir -p "${DIST_DIR}"
rm -rf "${PKG_DIR}"
mkdir -p "${PKG_DIR}"

copy_path() {
  local src="$1"
  local src_path="${ROOT_DIR}/${src}"
  local dest_path="${PKG_DIR}/${src}"

  if [[ -d "${src_path}" ]]; then
    mkdir -p "${dest_path}"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a \
        --exclude '.DS_Store' \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude '*.pyo' \
        --exclude '.pytest_cache' \
        --exclude '.mypy_cache' \
        --exclude '.ruff_cache' \
        "${src_path}/" "${dest_path}/"
    else
      cp -R "${src_path}/." "${dest_path}/"
    fi
  else
    mkdir -p "$(dirname "${dest_path}")"
    cp "${src_path}" "${dest_path}"
  fi
}

copy_path "app"
copy_path "artifacts"
copy_path "docs"
copy_path "mcp_server"
copy_path "migrations"
copy_path "model_server"
copy_path "observability"
copy_path "policy"
copy_path "scripts"
copy_path "tests"
copy_path ".env.example"
copy_path "Dockerfile"
copy_path "docker-compose.yml"
copy_path "Makefile"
copy_path "README.md"
copy_path "requirements.txt"
copy_path "requirements-optional.txt"

find "${PKG_DIR}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${PKG_DIR}" -type f \( -name '.DS_Store' -o -name '*.pyc' -o -name '*.pyo' \) -delete

cat > "${PKG_DIR}/RELEASE_INFO.txt" <<INFO
Package: ${PKG_NAME}
Version: ${VERSION}
Build timestamp (UTC): $(date -u +"%Y-%m-%dT%H:%M:%SZ")
INFO

ARCHIVE_PATH="${DIST_DIR}/${PKG_NAME}.tar.gz"
CHECKSUM_PATH="${DIST_DIR}/${PKG_NAME}.sha256"

rm -f "${ARCHIVE_PATH}" "${CHECKSUM_PATH}"

tar -czf "${ARCHIVE_PATH}" -C "${DIST_DIR}" "${PKG_NAME}"

if command -v sha256sum >/dev/null 2>&1; then
  (
    cd "${DIST_DIR}"
    sha256sum "${PKG_NAME}.tar.gz" > "${PKG_NAME}.sha256"
  )
else
  (
    cd "${DIST_DIR}"
    shasum -a 256 "${PKG_NAME}.tar.gz" > "${PKG_NAME}.sha256"
  )
fi

echo "Release package created: ${ARCHIVE_PATH}"
echo "Checksum created: ${CHECKSUM_PATH}"
