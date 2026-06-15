#!/usr/bin/env bash
#
# Build and push the Spore app + kernel images to a registry namespace.
#
# Usage:
#   docker/publish.sh                              # app + kernel 3.12; tags version + latest
#   NAMESPACE=myuser docker/publish.sh
#   VERSION=0.6 docker/publish.sh                  # override the version (default: setup.py)
#   PUSH_LATEST=0 docker/publish.sh                # skip the moving "latest" tag
#   KERNEL_PY_VERSIONS="3.11 3.12 3.13" docker/publish.sh   # offer multiple kernels
#
# The app image is published as both <namespace>/spore:<version> and
# <namespace>/spore:latest. The version defaults to the value in setup.py.
#
# Each kernel version is published as <namespace>/spore-kernel:<version>, which
# is exactly what docker-compose.hub.yml pulls when KERNEL_PYTHON_VERSION is set.
#
# Requires: docker login already done for the target namespace.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

NAMESPACE="${NAMESPACE:-anshsharma2903}"
KERNEL_PY_VERSIONS="${KERNEL_PY_VERSIONS:-3.12}"

# Version: env override, else parsed from setup.py, else "dev".
if [[ -z "${VERSION:-}" ]]; then
  VERSION="$(sed -n 's/.*version="\([^"]*\)".*/\1/p' setup.py | head -n1)"
  VERSION="${VERSION:-dev}"
fi

# App tags: always the version; add "latest" unless PUSH_LATEST=0.
APP_TAGS=("${VERSION}")
[[ "${PUSH_LATEST:-1}" == "1" ]] && APP_TAGS+=("latest")

build_args=()
for t in "${APP_TAGS[@]}"; do build_args+=(-t "${NAMESPACE}/spore:${t}"); done

echo ">> Building app image (version ${VERSION}): ${APP_TAGS[*]}"
docker build "${build_args[@]}" -f docker/Dockerfile .

for t in "${APP_TAGS[@]}"; do
  echo ">> Pushing ${NAMESPACE}/spore:${t}"
  docker push "${NAMESPACE}/spore:${t}"
done

for ver in ${KERNEL_PY_VERSIONS}; do
  kernel_image="${NAMESPACE}/spore-kernel:${ver}"
  echo ">> Building kernel image: ${kernel_image} (python:${ver}-slim)"
  docker build --build-arg "KERNEL_BASE_IMAGE=python:${ver}-slim" \
    -f docker/Dockerfile.kernel -t "${kernel_image}" .
  echo ">> Pushing ${kernel_image}"
  docker push "${kernel_image}"
done

echo ">> Done."
echo "   App:    ${NAMESPACE}/spore:{${APP_TAGS[*]// /,}}"
echo "   Kernel: ${NAMESPACE}/spore-kernel:{${KERNEL_PY_VERSIONS// /,}}"
echo "   Run with: docker compose -f docker/docker-compose.hub.yml up -d"
