#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$service_dir"
host="${ITP_KLEIN_HOST:-127.0.0.1}"
port="${ITP_KLEIN_PORT:-8788}"
if [[ -z "${ITP_KLEIN_API_TOKEN:-}" ]]; then
  echo "ITP_KLEIN_API_TOKEN is required" >&2
  exit 1
fi
if [[ "$host" != "127.0.0.1" && "$host" != "localhost" && "$host" != "::1" ]]; then
  echo "Public binding is disabled; use an authenticated HTTPS reverse proxy" >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn itp_flux_klein_service.api:app \
  --host "$host" \
  --port "$port" \
  --workers 1 \
  --no-proxy-headers
