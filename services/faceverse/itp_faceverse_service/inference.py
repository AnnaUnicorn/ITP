"""Detect one face and reconstruct its real FaceVerse V4 surface."""

import logging
import sys
from dataclasses import dataclass
from pathlib import Path

import mediapipe as mp
import numpy as np
import torch
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from PIL import Image

logger = logging.getLogger(__name__)

LANDMARK_IDS = {
    "left_eye_outer": 33,
    "left_eye_inner": 133,
    "right_eye_inner": 362,
    "right_eye_outer": 263,
    "nose_tip": 1,
    "mouth_left": 61,
    "mouth_right": 291,
    "chin": 152,
    "head_left": 234,
    "head_right": 454,
}


class FaceDetectionError(ValueError):
    """The supplied photo does not contain exactly one usable frontal face."""


@dataclass(frozen=True)
class ReconstructedFace:
    vertices: np.ndarray
    faces: np.ndarray
    colors: np.ndarray
    face_mask: np.ndarray
    landmarks_3d: dict[str, np.ndarray]
    landmarks_2d: dict[str, np.ndarray]
    bbox: tuple[int, int, int, int]
    photo_size: tuple[int, int]


class FaceVerseInference:
    def __init__(self, upstream_root: Path, models_dir: Path, device: str = "cuda:0"):
        if not torch.cuda.is_available() and device.startswith("cuda"):
            raise RuntimeError("CUDA is not available to FaceVerse V4")
        for name in ("faceverse_v4_2.npy", "faceverse_resnet50.pth", "face_landmarker.task"):
            if not (models_dir / name).is_file():
                raise FileNotFoundError(models_dir / name)

        upstream = str(upstream_root.resolve())
        if upstream not in sys.path:
            sys.path.insert(0, upstream)
        from faceversev4 import FaceVerseRecon  # noqa: PLC0415

        self.device = torch.device(device)
        self.recon = FaceVerseRecon(
            str(models_dir / "faceverse_v4_2.npy"),
            str(models_dir / "faceverse_resnet50.pth"),
            self.device,
        )
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(
                model_asset_path=str(models_dir / "face_landmarker.task")
            ),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=2,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self.detector = vision.FaceLandmarker.create_from_options(options)
        logger.info("FaceVerse V4 loaded on %s", self.device)

    def close(self) -> None:
        self.detector.close()

    def detect_landmarks(self, rgb: np.ndarray) -> list[np.ndarray]:
        image = np.ascontiguousarray(rgb[:, :, :3], dtype=np.uint8)
        result = self.detector.detect(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=image)
        )
        return [
            np.array(
                [(point.x * image.shape[1], point.y * image.shape[0]) for point in face],
                dtype=np.float64,
            )
            for face in result.face_landmarks
        ]

    def reconstruct(self, photo: Image.Image) -> ReconstructedFace:
        rgb = np.ascontiguousarray(photo.convert("RGB"), dtype=np.uint8)
        detected = self.detect_landmarks(rgb)
        if len(detected) != 1:
            raise FaceDetectionError("Exactly one clear frontal face is required")

        points = detected[0].astype(np.float32)
        if len(points) < 478:
            raise FaceDetectionError("Face landmark detector returned incomplete landmarks")
        x1, y1 = np.floor(points.min(axis=0)).astype(int)
        x2, y2 = np.ceil(points.max(axis=0)).astype(int)
        bbox = (
            max(0, int(x1)),
            max(0, int(y1)),
            min(rgb.shape[1], int(x2)),
            min(rgb.shape[0], int(y2)),
        )
        if min(bbox[2] - bbox[0], bbox[3] - bbox[1]) < 96:
            raise FaceDetectionError("Detected face is too small for high-detail reconstruction")

        with torch.inference_mode():
            coeffs, crop_boxes = self.recon.process_imgs(rgb, np.asarray([bbox]))
            vertices, _, _, colors = self.recon.from_coeffs(coeffs, crop_boxes)
        fvd = self.recon.fvd
        mesh_indices = np.asarray(fvd["keypoints_mediapipe"], dtype=np.int64).reshape(-1)
        if len(mesh_indices) < 478:
            raise RuntimeError("FaceVerse V4 model lacks MediaPipe landmark mapping")
        landmarks_3d = {
            name: vertices[0, int(mesh_indices[index])].astype(np.float64)
            for name, index in LANDMARK_IDS.items()
        }
        landmarks_2d = {
            name: points[index].astype(np.float64) for name, index in LANDMARK_IDS.items()
        }
        face_mask = np.asarray(fvd["face_mask"]).reshape(-1) > 0
        faces = np.asarray(fvd["tri"], dtype=np.int64)
        if len(face_mask) < vertices.shape[1] or faces.max() >= vertices.shape[1]:
            raise RuntimeError("FaceVerse V4 geometry and mask are inconsistent")

        logger.info(
            "Reconstructed face bbox=%s vertices=%d triangles=%d",
            bbox,
            vertices.shape[1],
            len(faces),
        )
        return ReconstructedFace(
            vertices=vertices[0].astype(np.float64),
            faces=faces,
            colors=np.clip(colors[0], 0, 1).astype(np.float64),
            face_mask=face_mask[: vertices.shape[1]],
            landmarks_3d=landmarks_3d,
            landmarks_2d=landmarks_2d,
            bbox=bbox,
            photo_size=(rgb.shape[1], rgb.shape[0]),
        )
