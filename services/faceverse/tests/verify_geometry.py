"""Regression check: flatten_glb welds seam-duplicated vertices.

AI3D exports repeat a vertex wherever a UV or normal seam splits it. While the
mesh stays split its surface is full of false open edges, fuse() cannot tell the
face-cut contour from them, and refinement fails with
"No closed outer face-cut contour". This check flattens a deliberately unwelded
GLB and asserts the result is a manifold surface again.
"""

import sys
from pathlib import Path

import numpy as np
import trimesh

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))
from itp_faceverse_service.geometry import flatten_glb  # noqa: E402


def unwelded_glb() -> tuple[bytes, int]:
    """Export a closed sphere with every triangle carrying its own vertices."""
    sphere = trimesh.creation.icosphere(subdivisions=2)
    split = trimesh.Trimesh(
        vertices=sphere.vertices[sphere.faces].reshape(-1, 3),
        faces=np.arange(sphere.faces.size, dtype=np.int64).reshape(-1, 3),
        process=False,
    )
    if split.is_watertight or len(split.faces) < 100:
        raise RuntimeError("Test fixture is not a usable unwelded mesh")
    return split.export(file_type="glb"), len(sphere.vertices)


def main() -> None:
    data, welded_vertices = unwelded_glb()
    flattened = flatten_glb(data)
    if not flattened.is_watertight:
        raise RuntimeError(
            f"flatten_glb left the surface open: {len(flattened.faces)} faces, not watertight"
        )
    if len(flattened.vertices) != welded_vertices:
        raise RuntimeError(
            f"expected {welded_vertices} welded vertices, got {len(flattened.vertices)}"
        )
    print(f"flatten_glb welded {welded_vertices} vertices; surface is watertight")


if __name__ == "__main__":
    main()
