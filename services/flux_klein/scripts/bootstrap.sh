#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${ITP_KLEIN_PYTHON:-/root/miniconda3/bin/python}"
index_url="${ITP_KLEIN_PYPI_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
cd "$service_dir"
"$python_bin" -m venv --system-site-packages .venv
.venv/bin/python -m pip install --index-url "$index_url" --upgrade pip
.venv/bin/python -m pip install --index-url "$index_url" -r requirements.txt
.venv/bin/python scripts/doctor.py
