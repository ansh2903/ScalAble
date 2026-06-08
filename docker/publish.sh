#!/usr/bin/env bash
#
# Build and push the Spore app + kernel images to a registry namespace.
#
# Usage:
#   docker/publish.sh                              # app + kernel 3.12, latest
#   NAMESPACE=myuser docker/publish.sh
#   TAG=v0.5 docker/publish.sh
#   KERNEL_PY_VERSIONS="3.11 3.12 3.13" docker/publish.sh   # offer multiple kernels
#
# Each kernel version is published as <namespace>/spore-kernel:<version>, which
# is exactly what docker-compose.hub.yml pulls when KERNEL_PYTHON_VERSION is set.
#
# Requires: docker login already done for the target namespace.
set -euo pipefail

NAMESPACE="${NAMESPACE:-anshsharma2903}"
TAG="${TAG:-latest}"
KERNEL_PY_VERSIONS="${KERNEL_PY_VERSIONS:-3.12}"

APP_IMAGE="${NAMESPACE}/spore:${TAG}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ">> Building app image:    ${APP_IMAGE}"
docker build -f docker/Dockerfile -t "${APP_IMAGE}" .

echo ">> Pushing ${APP_IMAGE}"
docker push "${APP_IMAGE}"

for ver in ${KERNEL_PY_VERSIONS}; do
  kernel_image="${NAMESPACE}/spore-kernel:${ver}"
  echo ">> Building kernel image: ${kernel_image} (python:${ver}-slim)"
  docker build --build-arg "KERNEL_BASE_IMAGE=python:${ver}-slim" \
    -f docker/Dockerfile.kernel -t "${kernel_image}" .
  echo ">> Pushing ${kernel_image}"
  docker push "${kernel_image}"
done

echo ">> Done."
echo "   App:    ${APP_IMAGE}"
echo "   Kernel: ${NAMESPACE}/spore-kernel:{${KERNEL_PY_VERSIONS// /,}}"
echo "   Run with: docker compose -f docker/docker-compose.hub.yml up -d"
