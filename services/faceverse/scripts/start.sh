#!/usr/bin/env bash
set -euo pipefail

service_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYOPENGL_PLATFORM=egl
export ITP_FACEVERSE_VENDOR_ROOT="${ITP_FACEVERSE_VENDOR_ROOT:-${service_root}/../vendor/FaceVerse_v4}"

if [[ ! -x "${service_root}/.venv/bin/python" ]]; then
  echo "Virtual environment missing; run scripts/bootstrap.sh first" >&2
  exit 1
fi
if [[ -z "${ITP_FACEVERSE_API_TOKEN:-}" && "${ITP_FACEVERSE_HOST:-127.0.0.1}" != "127.0.0.1" ]]; then
  echo "Set ITP_FACEVERSE_API_TOKEN before binding a non-loopback address" >&2
  exit 1
fi

cd "${service_root}"
exec "${service_root}/.venv/bin/python" -m uvicorn itp_faceverse_service.api:app \
  --host "${ITP_FACEVERSE_HOST:-127.0.0.1}" \
  --port "${ITP_FACEVERSE_PORT:-8787}" \
  --workers 1 \
  --no-proxy-headers
