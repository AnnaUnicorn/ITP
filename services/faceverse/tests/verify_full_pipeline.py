"""Integration acceptance: refine a real GLB from a real photo."""

import argparse
import base64
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from itp_faceverse_service.api import OPERATIONS, RefineRequest, _run_refinement  # noqa: E402
from itp_faceverse_service.inference import FaceVerseInference  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("body_glb", type=Path)
    parser.add_argument("photo", type=Path)
    parser.add_argument("output_glb", type=Path)
    parser.add_argument("--vendor-root", type=Path, required=True)
    args = parser.parse_args()
    payload = RefineRequest(
        model="faceverse-v4",
        mesh_glb_base64=base64.b64encode(args.body_glb.read_bytes()).decode(),
        face_photo_base64=base64.b64encode(args.photo.read_bytes()).decode(),
        preserve=["hair", "back_head", "neck"],
        alignment_landmarks=["eyes", "nose_tip", "mouth_corners", "chin", "head_width"],
        required_operations=list(OPERATIONS),
    )
    inference = FaceVerseInference(args.vendor_root, args.vendor_root / "data")
    try:
        result = _run_refinement(inference, payload)
    finally:
        inference.close()
    args.output_glb.parent.mkdir(parents=True, exist_ok=True)
    args.output_glb.write_bytes(base64.b64decode(result["glb_base64"]))
    print(json.dumps(result["report"], ensure_ascii=False))


if __name__ == "__main__":
    main()
