#!/usr/bin/env bash
set -euo pipefail
exec /root/miniconda3/bin/supervisord -n -c /root/autodl-tmp/itp-app/deploy/autodl/supervisord.conf
