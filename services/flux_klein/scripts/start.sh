#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$service_dir"
host="${ITP_KLEIN_HOST:-127.0.0.1}"
export ITP_KLEIN_MODEL_ID="${ITP_KLEIN_MODEL_ID:-flux.2-klein-4b}"
case "$ITP_KLEIN_MODEL_ID" in
  flux.2-klein-4b) default_port=8788 ;;
  flux.2-klein-9b) default_port=8789 ;;
  *) echo "ITP_KLEIN_MODEL_ID must be flux.2-klein-4b or flux.2-klein-9b" >&2; exit 1 ;;
esac
port="${ITP_KLEIN_PORT:-$default_port}"
python_bin="${ITP_KLEIN_SERVICE_PYTHON:-${service_dir}/.venv/bin/python}"
if [[ -z "${ITP_KLEIN_API_TOKEN:-}" ]]; then
  echo "ITP_KLEIN_API_TOKEN is required" >&2
  exit 1
fi
if [[ "$host" != "127.0.0.1" && "$host" != "localhost" && "$host" != "::1" ]]; then
  echo "Public binding is disabled; use an authenticated HTTPS reverse proxy" >&2
  exit 1
fi
exec "$python_bin" -m uvicorn itp_flux_klein_service.api:app \
  --host "$host" \
  --port "$port" \
  --workers 1 \
  --no-proxy-headers
