#!/usr/bin/env bash
set -euo pipefail

service_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${ITP_FACEVERSE_PYTHON:-/root/miniconda3/bin/python}"
models_dir="${ITP_FACEVERSE_MODELS_DIR:-${service_root}/vendor/FaceVerse_v4/data}"

"${python_bin}" -m venv --system-site-packages "${service_root}/.venv"
"${service_root}/.venv/bin/python" -m pip install --upgrade pip
"${service_root}/.venv/bin/python" -m pip install -r "${service_root}/requirements.txt"
"${service_root}/.venv/bin/python" "${service_root}/scripts/doctor.py" --models-dir "${models_dir}"
