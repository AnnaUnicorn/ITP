"""Surface deformation, seam construction, colour fusion and collision audit."""

from dataclasses import dataclass

import networkx as nx
import numpy as np
import trimesh
from scipy import sparse
from scipy.sparse.linalg import spsolve
from scipy.spatial import cKDTree

from .geometry import GeometryError


@dataclass(frozen=True)
class FusionQuality:
    boundary_rms: float
    boundary_max: float
    collision_count: int
    sampled_vertices: int
    welded_vertices: int
    bridge_faces: int
    face_triangles: int
    repaired_seam_loops: int
    open_boundary_edges: int


def boundary_edges(mesh: trimesh.Trimesh) -> np.ndarray:
    edges = np.sort(mesh.edges.reshape(-1, 2), axis=1)
    unique, counts = np.unique(edges, axis=0, return_counts=True)
    return unique[counts == 1]


def _ordered_loop(
    edges: np.ndarray, vertices: np.ndarray, preferred: np.ndarray | None = None
) -> np.ndarray:
    adjacency = {}
    for a, b in edges:
        adjacency.setdefault(int(a), []).append(int(b))
        adjacency.setdefault(int(b), []).append(int(a))
    if not adjacency or any(len(neighbors) != 2 for neighbors in adjacency.values()):
        raise GeometryError("Face patch boundary is non-manifold")
    remaining = set(adjacency)
    loops = []
    while remaining:
        start = min(remaining)
        loop = [start]
        previous = None
        current = start
        while True:
            neighbors = adjacency[current]
            following = neighbors[0] if neighbors[0] != previous else neighbors[1]
            if following == start:
                break
            if following in loop:
                raise GeometryError("Face patch boundary self-intersects")
            loop.append(following)
            previous, current = current, following
        loops.append(np.array(loop, dtype=np.int64))
        remaining.difference_update(loop)
    if preferred is not None:
        tree = cKDTree(preferred)
        scores = [float(np.median(tree.query(vertices[loop])[0])) for loop in loops]
        return loops[int(np.argmin(scores))]
    # A front face may contain eye/mouth openings; use the longest outer loop.
    perimeters = [
        np.linalg.norm(np.diff(vertices[np.r_[loop, loop[0]]], axis=0), axis=1).sum()
        for loop in loops
    ]
    return loops[int(np.argmax(perimeters))]


def _laplacian_deform(mesh: trimesh.Trimesh, anchors: np.ndarray, destinations: np.ndarray) -> None:
    n = len(mesh.vertices)
    edges = np.unique(np.sort(mesh.edges, axis=1), axis=0)
    adjacency = sparse.coo_matrix(
        (
            np.ones(len(edges) * 2),
            (np.r_[edges[:, 0], edges[:, 1]], np.r_[edges[:, 1], edges[:, 0]]),
        ),
        shape=(n, n),
    ).tocsr()
    degree = np.asarray(adjacency.sum(axis=1)).reshape(-1)
    laplacian = sparse.diags(degree) - adjacency
    pinned = np.unique(anchors)
    if len(pinned) < 12:
        raise GeometryError("Too few face-seam anchors")
    destination_map = dict(zip(anchors.tolist(), destinations, strict=True))
    free = np.ones(n, dtype=bool)
    free[pinned] = False
    displacement = np.zeros((n, 3), dtype=float)
    displacement[pinned] = np.stack(
        [destination_map[int(index)] - mesh.vertices[index] for index in pinned]
    )
    if np.any(free):
        system = laplacian[free][:, free] + sparse.eye(np.count_nonzero(free)) * 1e-7
        rhs = -(laplacian[free][:, pinned] @ displacement[pinned])
        displacement[free] = np.column_stack([spsolve(system, rhs[:, axis]) for axis in range(3)])
    mesh.vertices = mesh.vertices + displacement


def _remesh_long_edges(mesh: trimesh.Trimesh, max_length: float) -> trimesh.Trimesh:
    """Split triangles above the seam-scale threshold and interpolate their colour."""
    vertices = mesh.vertices.tolist()
    colors = np.asarray(mesh.visual.vertex_colors, dtype=np.uint8).tolist()
    midpoint = {}
    faces = []

    def edge_mid(a: int, b: int) -> int:
        key = tuple(sorted((a, b)))
        if key not in midpoint:
            midpoint[key] = len(vertices)
            vertices.append(((np.asarray(vertices[a]) + vertices[b]) / 2).tolist())
            colors.append(
                np.rint((np.asarray(colors[a], dtype=float) + colors[b]) / 2)
                .astype(np.uint8)
                .tolist()
            )
        return midpoint[key]

    if np.max(mesh.edges_unique_length) <= max_length:
        return mesh
    # Splitting every triangle keeps shared edges conforming (no T-junctions).
    for a, b, c in mesh.faces:
        ab, bc, ca = edge_mid(a, b), edge_mid(b, c), edge_mid(c, a)
        faces.extend(((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)))
    refined = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    refined.visual.vertex_colors = np.asarray(colors, dtype=np.uint8)
    return refined


def _close_residual_face_seams(
    mesh: trimesh.Trimesh, boundary_center: np.ndarray, head_width: float
) -> tuple[trimesh.Trimesh, int]:
    """Cap only small openings introduced near the face cut."""
    graph = nx.Graph()
    graph.add_edges_from(boundary_edges(mesh))
    loops = nx.cycle_basis(graph)
    for component in nx.connected_components(graph):
        subgraph = graph.subgraph(component)
        endpoints = [vertex for vertex, degree in subgraph.degree() if degree == 1]
        if len(endpoints) == 2 and len(component) >= 3:
            loops.append(nx.shortest_path(subgraph, endpoints[0], endpoints[1]))
    selected = []
    for loop in loops:
        points = mesh.vertices[loop]
        if (
            3 <= len(loop) <= 100
            and np.max(np.linalg.norm(points - boundary_center, axis=1)) < head_width * 1.15
        ):
            selected.append(loop)
    if not selected:
        return mesh, 0
    vertices = mesh.vertices.tolist()
    colors = np.asarray(mesh.visual.vertex_colors, dtype=np.uint8).tolist()
    faces = mesh.faces.tolist()
    normals = mesh.vertex_normals
    for loop in selected:
        ring = np.asarray(loop, dtype=np.int64)
        center = mesh.vertices[ring].mean(axis=0)
        expected = normals[ring].mean(axis=0)
        if len(ring) == 3:
            triangle = tuple(int(index) for index in ring)
            actual = np.cross(
                mesh.vertices[ring[1]] - mesh.vertices[ring[0]],
                mesh.vertices[ring[2]] - mesh.vertices[ring[0]],
            )
            if np.dot(actual, expected) < 0:
                triangle = (triangle[0], triangle[2], triangle[1])
            faces.append(triangle)
            continue
        center_index = len(vertices)
        vertices.append(center.tolist())
        colors.append(np.rint(np.mean(np.asarray(colors)[ring], axis=0)).astype(np.uint8).tolist())
        for a, b in zip(ring, np.roll(ring, -1), strict=True):
            triangle = (int(a), int(b), center_index)
            actual = np.cross(mesh.vertices[b] - mesh.vertices[a], center - mesh.vertices[a])
            if np.dot(actual, expected) < 0:
                triangle = (int(b), int(a), center_index)
            faces.append(triangle)
    closed = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    closed.visual.vertex_colors = np.asarray(colors, dtype=np.uint8)
    return closed, len(selected)


def fuse(
    kept: trimesh.Trimesh, patch: trimesh.Trimesh, target_boundary: np.ndarray, head_width: float
) -> tuple[trimesh.Trimesh, FusionQuality]:
    if head_width <= 0 or len(target_boundary) < 12:
        raise GeometryError("Invalid target face boundary")
    patch = patch.copy()
    # Select the *outer* newly cut contour. Imported face meshes commonly have
    # smaller eye/glasses/mouth islands inside the same oval.
    cut_distance = cKDTree(target_boundary).query(kept.vertices)[0]
    cut_edges = boundary_edges(kept)
    cut_edges = cut_edges[np.all(cut_distance[cut_edges] < max(head_width * 1e-4, 1e-8), axis=1)]
    graph = nx.Graph()
    graph.add_edges_from(cut_edges)
    cycles = nx.cycle_basis(graph)
    if not cycles:
        raise GeometryError("No closed outer face-cut contour")
    target_loop = np.asarray(max(cycles, key=len), dtype=np.int64)
    target_boundary = kept.vertices[target_loop]
    target_tree = cKDTree(target_boundary)
    outer = _ordered_loop(boundary_edges(patch), patch.vertices)
    distance, match = target_tree.query(patch.vertices[outer])
    if np.percentile(distance, 90) > head_width * 0.65:
        raise GeometryError("Reconstructed face does not overlap the cut region")
    destinations = target_boundary[match]
    _laplacian_deform(patch, outer, destinations)

    # Perform a local remesh before welding. Boundary midpoint vertices are added
    # consistently across adjacent triangles by the shared edge cache.
    patch = _remesh_long_edges(patch, head_width / 22)
    outer = _ordered_loop(boundary_edges(patch), patch.vertices)
    seam_distance, _ = target_tree.query(patch.vertices[outer])

    kept_colors = np.asarray(kept.visual.vertex_colors, dtype=np.float64)
    kept_tree = cKDTree(kept.vertices)
    nearest_distance, nearest_index = kept_tree.query(patch.vertices)
    colors = np.asarray(patch.visual.vertex_colors, dtype=np.float64)
    blend_width = max(head_width * 0.075, 1e-7)
    alpha = np.clip(nearest_distance / blend_width, 0, 1)[:, None]
    colors[:, :3] = alpha * colors[:, :3] + (1 - alpha) * kept_colors[nearest_index, :3]
    patch.visual.vertex_colors = np.rint(np.clip(colors, 0, 255)).astype(np.uint8)

    # Join nearest points at the open seam. The bridge triangulates gaps between
    # the source and target boundary rings even when their sampling differs.
    # Original assets can already contain non-manifold garment/hair seams. Use
    # only vertices on our newly cut face boundary, not every boundary in GLB.
    source_points = patch.vertices[outer]
    source_order = outer
    target_order = np.roll(
        target_loop,
        -int(np.argmin(np.linalg.norm(kept.vertices[target_loop] - source_points[0], axis=1))),
    )
    if np.linalg.norm(kept.vertices[target_order[1]] - source_points[1]) > np.linalg.norm(
        kept.vertices[target_order[-1]] - source_points[1]
    ):
        target_order = np.r_[target_order[0], target_order[:0:-1]]
    n_kept = len(kept.vertices)
    vertices = np.vstack((kept.vertices, patch.vertices))
    vertex_colors = np.vstack((kept.visual.vertex_colors, patch.visual.vertex_colors))
    faces = np.vstack((kept.faces, patch.faces + n_kept))

    # Zipper the two *topologically ordered* rings by normalized arc length.
    # Sorting vertices by angle would cross edges at cheeks and leave holes.
    def progress(points: np.ndarray) -> np.ndarray:
        closed = np.vstack((points, points[0]))
        cumulative = np.r_[0, np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))]
        return cumulative / max(cumulative[-1], 1e-12)

    source_progress = progress(patch.vertices[source_order])
    target_progress = progress(kept.vertices[target_order])
    i = j = 0
    bridge = []
    while i < len(source_order) or j < len(target_order):
        si = n_kept + source_order[i % len(source_order)]
        tj = target_order[j % len(target_order)]
        if i < len(source_order) and (
            j == len(target_order) or source_progress[i + 1] <= target_progress[j + 1]
        ):
            snext = n_kept + source_order[(i + 1) % len(source_order)]
            bridge.append((si, tj, snext))
            i += 1
        else:
            tnext = target_order[(j + 1) % len(target_order)]
            bridge.append((si, tj, tnext))
            j += 1
    bridge = np.asarray(bridge, dtype=np.int64)
    # The two rings may have opposite winding in imported assets. Orient each
    # bridge triangle to the adjacent FaceVerse surface before GLB export.
    bridge_centers = vertices[bridge].mean(axis=1)
    _, neighbor_faces = cKDTree(patch.triangles_center).query(bridge_centers)
    expected_normals = patch.face_normals[neighbor_faces]
    actual_normals = np.cross(
        vertices[bridge[:, 1]] - vertices[bridge[:, 0]],
        vertices[bridge[:, 2]] - vertices[bridge[:, 0]],
    )
    reverse = np.einsum("ij,ij->i", expected_normals, actual_normals) < 0
    bridge[reverse] = bridge[reverse][:, [0, 2, 1]]
    faces = np.vstack((faces, bridge))
    output = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    output.visual.vertex_colors = vertex_colors
    before_weld = len(output.vertices)
    output.merge_vertices(digits_vertex=max(0, int(np.ceil(-np.log10(head_width * 1e-5)))))
    output.update_faces(output.nondegenerate_faces())
    output.remove_unreferenced_vertices()
    output, repaired = _close_residual_face_seams(output, target_boundary.mean(axis=0), head_width)

    # A nearest-surface signed-normal audit catches folds intruding into retained
    # hair/neck/back-head geometry; points within the seam band are excluded.
    sample = patch.vertices[np.arange(0, len(patch.vertices), max(1, len(patch.vertices) // 1200))]
    nearby, distance_to_kept, triangle = trimesh.proximity.closest_point(kept, sample)
    normal = kept.face_normals[triangle]
    signed = np.einsum("ij,ij->i", sample - nearby, normal)
    collisions = int(
        np.count_nonzero((signed < -head_width * 0.012) & (distance_to_kept > blend_width))
    )
    if len(output.faces) <= len(kept.faces) or not np.all(np.isfinite(output.vertices)):
        raise GeometryError("Fused face mesh is invalid")
    quality = FusionQuality(
        float(np.sqrt(np.mean(seam_distance**2))),
        float(np.max(seam_distance)),
        collisions,
        len(sample),
        before_weld - len(output.vertices),
        len(bridge),
        len(patch.faces),
        repaired,
        len(boundary_edges(output)),
    )
    return output, quality
