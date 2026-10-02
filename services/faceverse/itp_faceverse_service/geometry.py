"""Camera-space face localization and geometric registration helpers."""

from dataclasses import dataclass
from io import BytesIO

import cv2
import networkx as nx
import numpy as np
import pyrender
import trimesh
from scipy.spatial import cKDTree

from .inference import ReconstructedFace


class GeometryError(ValueError):
    """The supplied body GLB cannot be safely face-refined."""


@dataclass(frozen=True)
class LocatedFace:
    mesh: trimesh.Trimesh
    landmarks: dict[str, np.ndarray]
    face_pixels: np.ndarray
    camera_pose: np.ndarray
    camera_scale: float
    depth: np.ndarray
    image_size: tuple[int, int]
    view_index: int


def flatten_glb(data: bytes) -> trimesh.Trimesh:
    if not data.startswith(b"glTF"):
        raise GeometryError("Input is not a GLB file")
    scene = trimesh.load(BytesIO(data), file_type="glb", force="scene", process=False)
    if not isinstance(scene, trimesh.Scene) or not scene.geometry:
        raise GeometryError("Input GLB contains no mesh")
    meshes = []
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph.get(node)
        source = scene.geometry[name]
        if not isinstance(source, trimesh.Trimesh) or not len(source.faces):
            continue
        mesh = source.copy()
        mesh.apply_transform(transform)
        if mesh.visual.kind == "texture":
            mesh.visual = mesh.visual.to_color()
        if mesh.visual.kind is None:
            mesh.visual.vertex_colors = np.tile([190, 170, 155, 255], (len(mesh.vertices), 1))
        meshes.append(mesh)
    if not meshes:
        raise GeometryError("Input GLB contains no triangle mesh")
    joined = trimesh.util.concatenate(meshes)
    if not np.all(np.isfinite(joined.vertices)) or len(joined.faces) < 100:
        raise GeometryError("Input mesh is too small or contains non-finite vertices")
    return joined


def _camera_pose(center: np.ndarray, radius: float, azimuth: float) -> np.ndarray:
    direction = np.array([np.sin(azimuth), 0.0, np.cos(azimuth)])
    eye = center + direction * (radius * 3.0)
    forward = center - eye
    forward /= np.linalg.norm(forward)
    right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    pose = np.eye(4)
    pose[:3, :3] = np.column_stack((right, up, -forward))
    pose[:3, 3] = eye
    return pose


def _backproject(
    pixels: np.ndarray, depth: np.ndarray, pose: np.ndarray, scale: float
) -> np.ndarray:
    height, width = depth.shape
    xy = np.asarray(pixels, dtype=float)
    ix = np.clip(np.rint(xy[:, 0]).astype(int), 0, width - 1)
    iy = np.clip(np.rint(xy[:, 1]).astype(int), 0, height - 1)
    # Some landmarks sit on the silhouette. Use nearest rendered surface within 4 pixels.
    depths = np.zeros(len(xy))
    for i, (x, y) in enumerate(zip(ix, iy, strict=True)):
        window = depth[max(y - 4, 0) : y + 5, max(x - 4, 0) : x + 5]
        valid = window[window > 0]
        if not len(valid):
            raise GeometryError("Rendered face landmark misses the body mesh")
        depths[i] = float(np.median(valid))
    local = np.column_stack(
        ((xy[:, 0] / width - 0.5) * scale, (0.5 - xy[:, 1] / height) * scale, -depths)
    )
    return local @ pose[:3, :3].T + pose[:3, 3]


def locate_face(mesh: trimesh.Trimesh, detector) -> LocatedFace:
    """Render four head views and use real face landmarks on the model surface."""
    bounds = mesh.bounds
    height = bounds[1, 1] - bounds[0, 1]
    width = max(bounds[1, 0] - bounds[0, 0], bounds[1, 2] - bounds[0, 2])
    if height <= 0 or width <= 0:
        raise GeometryError("Degenerate body bounds")
    center = np.array(
        [
            (bounds[0, 0] + bounds[1, 0]) / 2,
            bounds[1, 1] - height * 0.15,
            (bounds[0, 2] + bounds[1, 2]) / 2,
        ]
    )
    scale = min(max(height * 0.43, width * 0.65), height * 0.7)
    resolution = 1024
    rendered_mesh = pyrender.Mesh.from_trimesh(mesh, smooth=False)
    camera = pyrender.OrthographicCamera(
        xmag=scale / 2, ymag=scale / 2, znear=0.01, zfar=max(height, width) * 10
    )
    renderer = pyrender.OffscreenRenderer(resolution, resolution)
    candidates = []
    try:
        for view_index, angle in enumerate((0, np.pi / 2, np.pi, 3 * np.pi / 2)):
            scene = pyrender.Scene(bg_color=[255, 255, 255, 255], ambient_light=[0.9, 0.9, 0.9])
            scene.add(rendered_mesh)
            pose = _camera_pose(center, max(height, width), angle)
            scene.add(camera, pose=pose)
            scene.add(pyrender.DirectionalLight(color=np.ones(3), intensity=1.5), pose=pose)
            image, depth = renderer.render(scene)
            # pyrender 0.1.45 decodes every depth buffer as perspective depth,
            # even for OrthographicCamera. Invert that decoding before using it.
            visible_depth = depth > 0
            depth[visible_depth] = (
                camera.znear + camera.zfar - (camera.znear * camera.zfar / depth[visible_depth])
            )
            result = detector.detect_landmarks(image)
            if len(result) != 1:
                continue
            pixels = result[0]
            bbox = np.ptp(pixels, axis=0)
            if min(bbox) < 80:
                continue
            score = float(bbox[0] * bbox[1])
            candidates.append((score, view_index, pixels, pose, depth))
    finally:
        renderer.delete()
    if not candidates:
        raise GeometryError("No identifiable frontal face on the rendered body GLB")
    _, view_index, pixels, pose, depth = max(candidates, key=lambda item: item[0])
    from .inference import LANDMARK_IDS

    names = list(LANDMARK_IDS)
    points = _backproject(pixels[list(LANDMARK_IDS.values())], depth, pose, scale)
    return LocatedFace(
        mesh,
        dict(zip(names, points, strict=True)),
        pixels,
        pose,
        scale,
        depth,
        (resolution, resolution),
        view_index,
    )


def similarity_alignment(
    source: dict[str, np.ndarray], target: dict[str, np.ndarray]
) -> tuple[float, np.ndarray, np.ndarray, float]:
    """Weighted 3-D Umeyama fit; use eyes, nose, mouth, chin and head width."""
    names = [
        "left_eye_outer",
        "left_eye_inner",
        "right_eye_inner",
        "right_eye_outer",
        "nose_tip",
        "mouth_left",
        "mouth_right",
        "chin",
        "head_left",
        "head_right",
    ]
    source_points = np.stack([source[name] for name in names])
    target_points = np.stack([target[name] for name in names])
    weights = np.array([1.5, 1.5, 1.5, 1.5, 2, 1.5, 1.5, 1.5, 1, 1], dtype=float)
    weights /= weights.sum()
    source_center = np.sum(source_points * weights[:, None], axis=0)
    target_center = np.sum(target_points * weights[:, None], axis=0)
    a, b = source_points - source_center, target_points - target_center
    covariance = (a * weights[:, None]).T @ b
    u, singular, vt = np.linalg.svd(covariance)
    correction = np.diag([1, 1, np.sign(np.linalg.det(u @ vt))])
    rotation = u @ correction @ vt
    scale = float(np.sum(singular * np.diag(correction)) / np.sum(weights * np.sum(a * a, axis=1)))
    if not 0.01 < scale < 100 or not np.isfinite(scale):
        raise GeometryError("Face-to-body similarity alignment is degenerate")
    translation = target_center - scale * source_center @ rotation
    residual = float(
        np.sqrt(
            np.sum(
                weights
                * np.sum(
                    (scale * source_points @ rotation + translation - target_points) ** 2, axis=1
                )
            )
        )
    )
    return scale, rotation, translation, residual


def project(vertices: np.ndarray, located: LocatedFace) -> tuple[np.ndarray, np.ndarray]:
    local = (vertices - located.camera_pose[:3, 3]) @ located.camera_pose[:3, :3]
    width, height = located.image_size
    pixels = np.column_stack(
        (
            (local[:, 0] / located.camera_scale + 0.5) * width,
            (0.5 - local[:, 1] / located.camera_scale) * height,
        )
    )
    return pixels, -local[:, 2]


def remove_face_region(located: LocatedFace) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray]:
    """Remove only visible front-face triangles inside the detected face oval."""
    mesh = located.mesh
    # MediaPipe face oval, from forehead through cheeks and chin.
    oval_indices = [
        10,
        338,
        297,
        332,
        284,
        251,
        389,
        356,
        454,
        323,
        361,
        288,
        397,
        365,
        379,
        378,
        400,
        377,
        152,
        148,
        176,
        149,
        150,
        136,
        172,
        58,
        132,
        93,
        234,
        127,
        162,
        21,
        54,
        103,
        67,
        109,
    ]
    polygon = located.face_pixels[oval_indices].astype(np.int32)
    mask = np.zeros(located.depth.shape, dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 1)
    centroids = mesh.triangles_center
    pixels, camera_depth = project(centroids, located)
    ix = np.clip(np.rint(pixels[:, 0]).astype(int), 0, mask.shape[1] - 1)
    iy = np.clip(np.rint(pixels[:, 1]).astype(int), 0, mask.shape[0] - 1)
    head_width = np.linalg.norm(located.landmarks["head_left"] - located.landmarks["head_right"])
    # Remove all *front-half* layers, not merely the first visible layer.
    # This also removes glasses or old eyelids above the low-quality face while
    # retaining hair outside the oval and the rear skull behind the cut plane.
    _, landmark_depths = project(np.stack(list(located.landmarks.values())), located)
    front_limit = float(np.median(landmark_depths) + head_width * 0.38)
    remove = (mask[iy, ix] > 0) & (camera_depth < front_limit)
    if np.count_nonzero(remove) < 20:
        raise GeometryError("Face region could not be isolated without removing preserved geometry")
    kept = mesh.copy()
    kept.update_faces(~remove)
    kept.remove_unreferenced_vertices()
    # Boundary vertices of the removed patch in the original coordinate frame.
    edge_counts = {}
    for tri in mesh.faces[remove]:
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edge = tuple(sorted((int(a), int(b))))
            edge_counts[edge] = edge_counts.get(edge, 0) + 1
    boundaries = np.array(
        [edge for edge, count in edge_counts.items() if count == 1], dtype=np.int64
    )
    if len(boundaries) < 12:
        raise GeometryError("Face cut has no usable boundary")
    target_boundary = mesh.vertices[np.unique(boundaries)]

    # The front-half cut can create tiny disconnected openings around glasses,
    # ear rims and hair strands. Cap only those small loops; leave the largest
    # face opening for FaceVerse patch insertion.
    kept_edges = np.sort(kept.edges, axis=1)
    unique_kept, counts_kept = np.unique(kept_edges, axis=0, return_counts=True)
    open_edges = unique_kept[counts_kept == 1]
    distances = cKDTree(target_boundary).query(kept.vertices)[0]
    cut_edges = open_edges[np.all(distances[open_edges] < max(head_width * 1e-4, 1e-8), axis=1)]
    cut_graph = nx.Graph()
    cut_graph.add_edges_from(cut_edges)
    components = sorted(nx.connected_components(cut_graph), key=len, reverse=True)
    if components:
        extra_vertices = []
        extra_colors = []
        extra_faces = []
        colors = np.asarray(kept.visual.vertex_colors)
        normals = kept.vertex_normals
        for component in components[1:]:
            for ring in nx.cycle_basis(cut_graph.subgraph(component)):
                if not 3 <= len(ring) <= 32:
                    continue
                indices = np.asarray(ring, dtype=np.int64)
                center = kept.vertices[indices].mean(axis=0)
                center_index = len(kept.vertices) + len(extra_vertices)
                extra_vertices.append(center)
                extra_colors.append(np.rint(colors[indices].mean(axis=0)).astype(np.uint8))
                expected = normals[indices].mean(axis=0)
                for a, b in zip(indices, np.roll(indices, -1), strict=True):
                    triangle = (int(a), int(b), center_index)
                    actual = np.cross(
                        kept.vertices[b] - kept.vertices[a], center - kept.vertices[a]
                    )
                    if np.dot(actual, expected) < 0:
                        triangle = (int(b), int(a), center_index)
                    extra_faces.append(triangle)
        if extra_faces:
            updated = trimesh.Trimesh(
                vertices=np.vstack((kept.vertices, extra_vertices)),
                faces=np.vstack((kept.faces, extra_faces)),
                process=False,
            )
            updated.visual.vertex_colors = np.vstack((colors, extra_colors))
            kept = updated
    return kept, target_boundary, remove


def source_patch(
    face: ReconstructedFace, scale: float, rotation: np.ndarray, translation: np.ndarray
) -> trimesh.Trimesh:
    select = np.all(face.face_mask[face.faces], axis=1)
    masked = trimesh.Trimesh(vertices=face.vertices, faces=face.faces[select], process=False)
    edges = np.sort(masked.edges, axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    graph = nx.Graph()
    graph.add_edges_from(unique[counts == 1])
    loops = sorted(nx.cycle_basis(graph), key=len, reverse=True)
    mouth_ring = None
    if len(loops) > 1:
        # FaceVerse's face_mask leaves an inner-mouth hole. Fill it with the
        # model's actual oral-cavity triangles rather than inventing a cap.
        mouth_ring = np.asarray(loops[1], dtype=np.int64)
        mouth = face.vertices[mouth_ring]
    vertices = face.vertices.copy()
    faces = face.faces[select].copy()
    colors = np.rint(np.clip(face.colors, 0, 1) * 255).astype(np.uint8)
    if mouth_ring is not None:
        center_vertex = vertices[mouth_ring].mean(axis=0)
        center_vertex[2] = np.max(vertices[mouth_ring, 2]) + 0.015
        cap_index = len(vertices)
        vertices = np.vstack((vertices, center_vertex))
        cap_color = np.mean(colors[mouth_ring], axis=0)
        cap_color[:3] *= 0.65
        colors = np.vstack((colors, np.rint(cap_color).astype(np.uint8)))
        signed_area = np.sum(
            mouth[:, 0] * np.roll(mouth[:, 1], -1) - np.roll(mouth[:, 0], -1) * mouth[:, 1]
        )
        cap_faces = np.array(
            [
                (int(mouth_ring[(i + 1) % len(mouth_ring)]), int(mouth_ring[i]), cap_index)
                if signed_area > 0
                else (int(mouth_ring[i]), int(mouth_ring[(i + 1) % len(mouth_ring)]), cap_index)
                for i in range(len(mouth_ring))
            ],
            dtype=np.int64,
        )
        faces = np.vstack((faces, cap_faces))
    patch = trimesh.Trimesh(
        vertices=scale * vertices @ rotation + translation, faces=faces, process=False
    )
    patch.visual.vertex_colors = colors
    patch.remove_unreferenced_vertices()
    if len(patch.faces) < 1000:
        raise GeometryError("FaceVerse reconstruction has no usable front-face patch")
    return patch
