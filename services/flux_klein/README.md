# FLUX.2 Klein 4B FastAPI service

This directory contains a real Diffusers-backed image-editing service for ITP. It does not contain model weights. The model is [`black-forest-labs/FLUX.2-klein-4B`](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B), licensed under Apache-2.0. The model card states roughly 13 GB VRAM for normal loading. The validated 32 GB RTX 4080 SUPER host runs without CPU offload; smaller hosts may need offload and separate validation.

## Server preparation

The service uses the existing CUDA-enabled PyTorch from `/root/miniconda3/bin/python` through an isolated `--system-site-packages` venv. Set `ITP_KLEIN_PYTHON` if that Python is elsewhere. Before running inference, inspect **all** GPUs with `nvidia-smi`, select a free device using `ITP_KLEIN_GPU`, and make sure the model cache has enough disk space. The bootstrap script uses the Tsinghua PyPI mirror by default; override `ITP_KLEIN_PYPI_INDEX` as needed. It checks CUDA, available GPUs, package versions and the Diffusers pipeline class, but does not claim that inference succeeds.

From the service directory on the server:

```bash
bash scripts/bootstrap.sh
export ITP_KLEIN_GPU=0
export ITP_KLEIN_OFFLOAD=none
export ITP_KLEIN_API_TOKEN='set-a-private-token'
bash scripts/start.sh
```

`ITP_KLEIN_OFFLOAD` accepts `sequential` (the default and slowest), `model`, or `none` (the validated 32 GB setting). Set `ITP_KLEIN_MODEL_PATH` to an existing absolute model snapshot directory, or leave it unset to let Diffusers download into the Hugging Face cache. `HF_ENDPOINT` may be set to an accessible compatible mirror; verify its provenance. The token above is only an example: use a private value and never commit it.

The server binds to `127.0.0.1:8788` only. With an SSH tunnel, set ITP's Klein endpoint to `http://127.0.0.1:8788/v1/flux-klein/edit` and enter the same token in the ITP settings page. A public deployment requires an authenticated HTTPS reverse proxy; `scripts/start.sh` intentionally refuses a public bind.

## Contract and validation

- `GET /health` returns `ready`, `model` and a non-sensitive error type. `ready=true` means weights loaded; it does **not** prove visual quality or four-reference inference.
- `POST /v1/flux-klein/edit` requires `Authorization: Bearer ...` and JSON `{ "model": "flux.2-klein-4b", "prompt": "...", "images": ["data:image/jpeg;base64,..."] }`. Supply 1–4 images. It returns `{ "model": "flux.2-klein-4b", "data": [{ "b64_json": "..." }] }` with a PNG result.
- Each input is limited to 10 MiB and validated as a still PNG, JPEG or WebP. The service runs the official 4-step distilled pipeline at 768×1024 and serializes GPU inference. Model errors are logged server-side without returning user images or tokens.

## Deployment validation (2026-10-03)

On the current 32 GB RTX 4080 SUPER host, the service loaded model snapshot `e7b7dc27f91deacad38e78976d1f2b499d76a294` with PyTorch 2.8.0+cu128 and Diffusers 0.40.0. Only the 18 Diffusers component files were downloaded (about 15 GB in the cache); the separate monolithic checkpoint was omitted. The server could not reach `huggingface.co` directly, so `hf-mirror.com` was used. The mirror's provenance was not independently checked against upstream file hashes.

The live `/health` response reported `ready=true`. Real `POST /v1/flux-klein/edit` requests with one and four references each returned HTTP 200 and valid 768×1024 PNG images. A request without a Bearer token returned HTTP 401. The one-reference cat-to-dog edit visibly changed the subject while retaining a similar composition. This verifies image generation and the four-reference API path, **not** identity consistency or garment fidelity on real virtual-try-on photographs; those need representative user images for evaluation.
