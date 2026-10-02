"""Verify the GPU runtime, service dependencies, and FaceVerse asset integrity."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

EXPECTED_FILES = {
    # The first two digests are from the third-party v4.1.0 GitHub release,
    # not from the FaceVerse authors. They prove transfer integrity only.
    "faceverse_v4_2.npy": (
        173_330_032,
        "077df2658add90ea22ac9675967e38edf56170822c2a7acfe40bda55a9ed3702",
    ),
    "faceverse_resnet50.pth": (
        99_454_687,
        "9d57cbe82061694cccc40c44db6ab9d22dc72f4e9fc0f9c84197564bde4c9d98",
    ),
    "face_landmarker.task": (
        3_758_596,
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    import cv2
    import fastapi
    import mediapipe
    import numpy
    import pyrender
    import scipy
    import torch
    import trimesh

    result = {
        "python": sys.version.split()[0],
        "versions": {
            "torch": torch.__version__,
            "torch_cuda": torch.version.cuda,
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "mediapipe": mediapipe.__version__,
            "opencv": cv2.__version__,
            "trimesh": trimesh.__version__,
            "pyrender": pyrender.__version__,
            "fastapi": fastapi.__version__,
        },
        "cuda_available": torch.cuda.is_available(),
        "files": {},
    }
    if result["cuda_available"]:
        result["gpu"] = torch.cuda.get_device_name(0)
        result["gpu_count"] = torch.cuda.device_count()
        result["cuda_smoke"] = float((torch.ones(2, device="cuda") + 1).sum().item())

    for filename, (expected_size, expected_hash) in EXPECTED_FILES.items():
        path = args.models_dir / filename
        found = path.is_file()
        size = path.stat().st_size if found else 0
        actual_hash = sha256(path) if found and size == expected_size else None
        result["files"][filename] = {
            "exists": found,
            "size": size,
            "sha256": actual_hash,
            "valid": found
            and size == expected_size
            and (expected_hash is None or actual_hash == expected_hash),
        }

    result["ready"] = result["cuda_available"] and all(
        item["valid"] for item in result["files"].values()
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
