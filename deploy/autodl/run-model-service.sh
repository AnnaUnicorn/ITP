#!/usr/bin/env bash
# Supervise one local model service (FLUX.2 Klein or FaceVerse).
#
# Two things happen before the service starts. First, the AutoDL container can
# be booted without a GPU, in which case neither service can load its weights;
# waiting for the device node keeps supervisord from crash-looping and starts
# the service automatically once the instance is rebooted with a GPU. Second,
# the bearer token is read from a root-only file so that no secret is stored in
# the checked-in supervisor configuration.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: run-model-service.sh TOKEN_ENV_VAR TOKEN_FILE START_SCRIPT" >&2
  exit 2
fi
token_var="$1"
token_file="$2"
start_script="$3"

while [[ ! -e /dev/nvidia0 ]]; do
  echo "no GPU device node present; waiting for a GPU boot"
  sleep 30
done

if [[ ! -r "$token_file" ]]; then
  echo "token file is missing or unreadable: $token_file" >&2
  exit 1
fi

export "${token_var}=$(tr -d '\n' < "$token_file")"
exec "$start_script"
