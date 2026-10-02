# FaceVerse V4 refinement service

This directory contains the server-side implementation of the ITP `/v1/face-refine` contract. It is deployed separately from the ITP web application. Never commit model weights, face photos, bearer tokens, or generated meshes.

## Environment

Target: Ubuntu 22.04, NVIDIA RTX 3080 Ti, NVIDIA driver with CUDA 12.8-capable PyTorch. The deployment uses a virtual environment with access to the server's existing CUDA-enabled PyTorch installation; it does not replace the system driver or base Conda packages. Run `scripts/bootstrap.sh` on the server after the three model files exist. The script verifies the GPU runtime, packages, file sizes, and available SHA-256 digests with `scripts/doctor.py`.

The upstream FaceVerse V4 source is pinned to [`19c67cc4d7234b1ea7d55a185a2cb55fd49bb877`](https://github.com/LizhenWangT/FaceVerse_v4/tree/19c67cc4d7234b1ea7d55a185a2cb55fd49bb877). Its required files are `faceverse_v4_2.npy`, `faceverse_resnet50.pth`, and `face_landmarker.task` in `vendor/FaceVerse_v4/data/`. The first two files are distributed by the authors through OneDrive; the target server cannot currently reach that host. A third-party GitHub release has matching filenames and supplies transfer checksums, but those checksums do **not** establish that the files are identical to the authors' releases. Do not treat this service as model-verified until weights pass structural and inference checks.

The full HTTP protocol and output requirements are documented in [the ITP face-refinement module](../../docs/modules/FACE_REFINEMENT.md). API tokens and input photos are deliberately excluded from this repository.
