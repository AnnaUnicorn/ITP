# FLUX.2 Klein 4B FastAPI service

This directory contains a real Diffusers-backed image-editing service for ITP. It does not contain model weights. The model is [`black-forest-labs/FLUX.2-klein-4B`](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B), licensed under Apache-2.0. The model card states roughly 13 GB VRAM for normal loading; the earlier 12 GB RTX 3080 Ti host therefore needs CPU offload and still requires a measured smoke test. Do not represent configuration alone as a successful deployment.

## Server preparation

The service uses the existing CUDA-enabled PyTorch from `/root/miniconda3/bin/python` through an isolated `--system-site-packages` venv. Set `ITP_KLEIN_PYTHON` if that Python is elsewhere. Before running inference, inspect **all** GPUs with `nvidia-smi`, select a free device using `ITP_KLEIN_GPU`, and make sure the model cache has enough disk space. The bootstrap script uses the Tsinghua PyPI mirror by default; override `ITP_KLEIN_PYPI_INDEX` as needed. It checks CUDA, available GPUs, package versions and the Diffusers pipeline class, but does not claim that inference succeeds.

From the service directory on the server:

```bash
bash scripts/bootstrap.sh
export ITP_KLEIN_GPU=0
export ITP_KLEIN_OFFLOAD=sequential
export ITP_KLEIN_API_TOKEN='set-a-private-token'
bash scripts/start.sh
```

`ITP_KLEIN_OFFLOAD` accepts `sequential` (default for the 12 GB host, slower), `model` (faster, potentially more VRAM) or `none`. Set `ITP_KLEIN_MODEL_PATH` to an existing absolute model directory, or leave it unset to let Diffusers download from the official model repository into the Hugging Face cache. `HF_ENDPOINT` may be set to an accessible compatible mirror; verify its provenance. The token above is only an example: use a private value and never commit it.

The server binds to `127.0.0.1:8788` only. With an SSH tunnel, set ITP's Klein endpoint to `http://127.0.0.1:8788/v1/flux-klein/edit` and enter the same token in the ITP settings page. A public deployment requires an authenticated HTTPS reverse proxy; `scripts/start.sh` intentionally refuses a public bind.

## Contract and validation

- `GET /health` returns `ready`, `model` and a non-sensitive error type. `ready=true` means weights loaded; it does **not** prove visual quality or four-reference inference.
- `POST /v1/flux-klein/edit` requires `Authorization: Bearer ...` and JSON `{ "model": "flux.2-klein-4b", "prompt": "...", "images": ["data:image/jpeg;base64,..."] }`. Supply 1–4 images. It returns `{ "model": "flux.2-klein-4b", "data": [{ "b64_json": "..." }] }` with a PNG result.
- Each input is limited to 10 MiB and validated as a still PNG, JPEG or WebP. The service runs the official 4-step distilled pipeline at 768×1024 and serializes GPU inference. Model errors are logged server-side without returning user images or tokens.

This service was prepared locally while the supplied SSH hostname could not be resolved from the current environment. No weights, CUDA execution, remote health response or image result have yet been verified on that host.
