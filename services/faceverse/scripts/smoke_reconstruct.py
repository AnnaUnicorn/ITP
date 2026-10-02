"""Reconstruct one actual photo with FaceVerse V4 and export an inspectable mesh."""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from itp_faceverse_service.inference import FaceVerseInference  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("photo", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--vendor-root", type=Path, required=True)
    args = parser.parse_args()

    service = FaceVerseInference(args.vendor_root, args.vendor_root / "data")
    try:
        with Image.open(args.photo) as photo:
            face = service.reconstruct(photo)
    finally:
        service.close()

    mesh = trimesh.Trimesh(
        vertices=face.vertices,
        faces=face.faces[np.all(face.face_mask[face.faces], axis=1)],
        vertex_colors=np.rint(np.clip(face.colors, 0, 1) * 255).astype(np.uint8),
        process=False,
    )
    if len(mesh.faces) < 1000 or not np.all(np.isfinite(mesh.vertices)):
        raise RuntimeError("FaceVerse reconstruction produced an invalid face mesh")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(args.output)
    print(json.dumps({"bbox": face.bbox, "vertices": len(mesh.vertices), "faces": len(mesh.faces), "output": str(args.output)}))


if __name__ == "__main__":
    main()
