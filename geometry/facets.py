# SPDX-License-Identifier: MIT
"""面片 NURBS 装配：收缩、拟合、切线连续、无缝边界与缝隙面。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple
import logging

import numpy as np

from models.facet import Facet
from models.reflector import MFReflector
from models.enums import (
    GapSurfaceMode,
    GapType,
    PatchContinuity,
    PatchFitMethod,
)
from geometry.engine import _build_height_field
from geometry.mathutils import _required_normal, _target_direction, _unit
from geometry.nurbs import make_nurbs_from_grid
from geometry.solve import _eval_facet


logger = logging.getLogger(__name__)



def _shrink_grid(
    grid_pts: np.ndarray,
    shrink_left: float = 0.0,
    shrink_right: float = 0.0,
    shrink_bottom: float = 0.0,
    shrink_top: float = 0.0,
) -> np.ndarray:
    """
    Shrink a facet sample grid in parameter space.

    LucidShape: width/height *deltas include the gap*.  Half of each internal
    gap is taken from each adjacent facet, so:
      - middle facet optical width = delta - gap
      - edge facet optical width   = delta - gap/2
    Outer borders (no neighbour) are not shrunk.
    """
    if (
        shrink_left <= 0.0
        and shrink_right <= 0.0
        and shrink_bottom <= 0.0
        and shrink_top <= 0.0
    ):
        return grid_pts.copy()  # 与有收缩分支一致：总是返回新数组
    sv, su, _ = grid_pts.shape
    u0 = float(shrink_left)
    u1 = 1.0 - float(shrink_right)
    v0 = float(shrink_bottom)
    v1 = 1.0 - float(shrink_top)
    if u1 <= u0 or v1 <= v0:
        raise ValueError("gap shrink would consume the entire facet")
    uu = u0 + (u1 - u0) * (np.arange(su) / max(su - 1, 1))
    vv = v0 + (v1 - v0) * (np.arange(sv) / max(sv - 1, 1))
    ii = np.clip(uu * (su - 1), 0, su - 1)
    jj = np.clip(vv * (sv - 1), 0, sv - 1)
    i0 = ii.astype(int)
    j0 = jj.astype(int)
    i1 = np.minimum(i0 + 1, su - 1)
    j1 = np.minimum(j0 + 1, sv - 1)
    du = (ii - i0)[None, :, None]
    dv = (jj - j0)[:, None, None]
    return (
        (1.0 - du) * (1.0 - dv) * grid_pts[j0[:, None], i0[None, :]]
        + du * (1.0 - dv) * grid_pts[j0[:, None], i1[None, :]]
        + (1.0 - du) * dv * grid_pts[j1[:, None], i0[None, :]]
        + du * dv * grid_pts[j1[:, None], i1[None, :]]
    )


def _refresh_facet_geometry(facet: Facet, source, spreads) -> None:
    if facet.ctrl is None:
        return
    corners = np.array(
        [
            _eval_facet(facet, 0.0, 0.0),
            _eval_facet(facet, 1.0, 0.0),
            _eval_facet(facet, 1.0, 1.0),
            _eval_facet(facet, 0.0, 1.0),
        ]
    )
    facet.corners = corners
    facet.center = corners.mean(axis=0)
    facet.size_u = float(np.linalg.norm(corners[1, :2] - corners[0, :2]))
    facet.size_v = float(np.linalg.norm(corners[3, :2] - corners[0, :2]))
    h_min, h_max, v_min, v_max = spreads.get_facet_spread(facet.index_u, facet.index_v)
    target = _target_direction(h_min, h_max, v_min, v_max, spreads.edge_ray)
    facet.h_min, facet.h_max = h_min, h_max
    facet.v_min, facet.v_max = v_min, v_max
    facet.normal = _required_normal(source, facet.center, target)


def _make_facet_nurbs_from_grid(
    sub_pts: np.ndarray,
    iu: int,
    iv: int,
    degree_u: int,
    degree_v: int,
    samples_u: int,
    samples_v: int,
    source,
    spreads,
    shrink_left: float = 0.0,
    shrink_right: float = 0.0,
    shrink_bottom: float = 0.0,
    shrink_top: float = 0.0,
    fit_method: PatchFitMethod = PatchFitMethod.EXACT,
    uniform_parameters: bool = False,
    patch_index_u: int = 0,
    patch_index_v: int = 0,
    z_step: float = 0.0,
) -> Facet:
    pts = _shrink_grid(
        sub_pts, shrink_left, shrink_right, shrink_bottom, shrink_top
    )
    ctrl, du, dv, ku, kv = make_nurbs_from_grid(
        pts, degree_u, degree_v, fit_method, uniform_parameters
    )
    corners = np.array([pts[0, 0], pts[0, -1], pts[-1, -1], pts[-1, 0]])
    center = corners.mean(axis=0)
    h_min, h_max, v_min, v_max = spreads.get_facet_spread(iu, iv)
    target = _target_direction(h_min, h_max, v_min, v_max, spreads.edge_ray)
    return Facet(
        index_u=iu,
        index_v=iv,
        patch_index_u=patch_index_u,
        patch_index_v=patch_index_v,
        center=center,
        normal=_required_normal(source, center, target),
        size_u=float(np.linalg.norm(corners[1, :2] - corners[0, :2])),
        size_v=float(np.linalg.norm(corners[3, :2] - corners[0, :2])),
        corners=corners,
        h_min=h_min,
        h_max=h_max,
        v_min=v_min,
        v_max=v_max,
        z_step=z_step,
        samples_u=max(2, samples_u),
        samples_v=max(2, samples_v),
        is_nurbs=True,
        ctrl=ctrl,
        degree_u=du,
        degree_v=dv,
        knots_u=ku,
        knots_v=kv,
    )


def _patch_ranges(n_samples: int, n_patches: int) -> List[Tuple[int, int]]:
    n_patches = max(1, int(n_patches))
    if n_patches == 1:
        return [(0, n_samples)]
    base, extra = divmod(n_samples - 1, n_patches)
    starts = [0]
    for i in range(n_patches):
        starts.append(starts[-1] + base + (1 if i < extra else 0))
    # 相邻块共享边界采样（区间含端点），最后一块终点 = n_samples。
    # 若最后一块不加 +1，网格最后一行/列不属于任何块——面片远端边界被截断。
    return [(starts[i], starts[i + 1] + 1) for i in range(n_patches)]


def _make_facet_patches(
    sub_pts: np.ndarray,
    iu: int,
    iv: int,
    degree_u: int,
    degree_v: int,
    source,
    spreads,
    shrink_left: float,
    shrink_right: float,
    shrink_bottom: float,
    shrink_top: float,
    fit_method: PatchFitMethod,
    patches_u: int,
    patches_v: int,
    continuity_u: PatchContinuity,
    continuity_v: PatchContinuity,
    z_step: float,
    uniform_parameters: bool,
) -> List[Facet]:
    use_uniform_parameters = uniform_parameters or continuity_u in (
        PatchContinuity.TANGENT,
        PatchContinuity.CURVATURE,
    ) or continuity_v in (
        PatchContinuity.TANGENT,
        PatchContinuity.CURVATURE,
    )
    shrunk_pts = _shrink_grid(
        sub_pts, shrink_left, shrink_right, shrink_bottom, shrink_top
    )
    ranges_u = _patch_ranges(shrunk_pts.shape[1], patches_u)
    ranges_v = _patch_ranges(shrunk_pts.shape[0], patches_v)
    facets: List[Facet] = []
    for pv, (j0, j1) in enumerate(ranges_v):
        for pu, (i0, i1) in enumerate(ranges_u):
            facets.append(
                _make_facet_nurbs_from_grid(
                    shrunk_pts[j0:j1, i0:i1].copy(),
                    iu,
                    iv,
                    degree_u,
                    degree_v,
                    max(2, i1 - i0),
                    max(2, j1 - j0),
                    source,
                    spreads,
                    0.0,
                    0.0,
                    0.0,
                    0.0,
                    fit_method,
                    use_uniform_parameters,
                    pu,
                    pv,
                    z_step,
                )
            )
    _enforce_tangent_continuity(
        facets,
        len(ranges_u),
        len(ranges_v),
        continuity_u,
        continuity_v,
        source,
        spreads,
    )
    return facets


def _enforce_tangent_continuity(
    facets: List[Facet],
    patches_u: int,
    patches_v: int,
    continuity_u: PatchContinuity,
    continuity_v: PatchContinuity,
    source,
    spreads,
) -> None:
    if patches_u <= 1 and patches_v <= 1:
        return
    by_patch = {(f.patch_index_u, f.patch_index_v): f for f in facets}

    if continuity_u in (PatchContinuity.TANGENT, PatchContinuity.CURVATURE):
        for pv in range(patches_v):
            for pu in range(patches_u - 1):
                left = by_patch[(pu, pv)]
                right = by_patch[(pu + 1, pv)]
                if left.ctrl.shape[1] < 2 or right.ctrl.shape[1] < 2:
                    continue
                shared = 0.5 * (left.ctrl[:, -1, :] + right.ctrl[:, 0, :])
                tangent = 0.5 * (
                    (right.ctrl[:, 1, :] - shared)
                    + (shared - left.ctrl[:, -2, :])
                )
                left.ctrl[:, -1, :] = shared
                right.ctrl[:, 0, :] = shared
                left.ctrl[:, -2, :] = shared - tangent
                right.ctrl[:, 1, :] = shared + tangent

    if continuity_v in (PatchContinuity.TANGENT, PatchContinuity.CURVATURE):
        for pu in range(patches_u):
            for pv in range(patches_v - 1):
                lower = by_patch[(pu, pv)]
                upper = by_patch[(pu, pv + 1)]
                if lower.ctrl.shape[0] < 2 or upper.ctrl.shape[0] < 2:
                    continue
                shared = 0.5 * (lower.ctrl[-1, :, :] + upper.ctrl[0, :, :])
                tangent = 0.5 * (
                    (upper.ctrl[1, :, :] - shared)
                    + (shared - lower.ctrl[-2, :, :])
                )
                lower.ctrl[-1, :, :] = shared
                upper.ctrl[0, :, :] = shared
                lower.ctrl[-2, :, :] = shared - tangent
                upper.ctrl[1, :, :] = shared + tangent

    for facet in facets:
        _refresh_facet_geometry(facet, source, spreads)


def _pair_patch_facets(facets: Sequence[Facet], key: str, value: int) -> List[Facet]:
    return sorted(
        [f for f in facets if getattr(f, key) == value],
        key=lambda f: (f.patch_index_v, f.patch_index_u),
    )


def _evaluated_edge(facet: Facet, axis: str, edge: str, count: int) -> np.ndarray:
    ts = np.linspace(0.0, 1.0, max(2, count))
    if axis == "v":
        return np.asarray(
            [_eval_facet(facet, 1.0 if edge == "right" else 0.0, t) for t in ts]
        )
    return np.asarray(
        [_eval_facet(facet, t, 1.0 if edge == "top" else 0.0) for t in ts]
    )


def _edge_control_delta(facet: Facet, axis: str, edge: str, target: np.ndarray) -> np.ndarray:
    """Control-point delta whose evaluated edge becomes target."""
    from geometry.nurbs import _basis_matrix

    if axis == "v":
        current = facet.ctrl[:, -1 if edge == "right" else 0, :]
        degree = facet.degree_v
        knots = facet.knots_v
    else:
        current = facet.ctrl[-1 if edge == "top" else 0, :, :]
        degree = facet.degree_u
        knots = facet.knots_u

    params = np.linspace(0.0, 1.0, len(current))
    matrix = _basis_matrix(params, degree, knots)
    desired = np.linalg.lstsq(matrix, target, rcond=None)[0]
    return desired - current


def _coons_control_delta(
    ctrl: np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
    bottom: np.ndarray,
    top: np.ndarray,
) -> np.ndarray:
    """Blend four edge control-point deltas without destroying any edge."""
    nv, nu, _ = ctrl.shape

    # Make each corner delta unique so the Coons formula reproduces all four
    # edge deltas exactly. Corner conflicts are resolved by averaging.
    c00 = 0.5 * (bottom[0] + left[0])
    c10 = 0.5 * (bottom[-1] + right[0])
    c11 = 0.5 * (top[-1] + right[-1])
    c01 = 0.5 * (top[0] + left[-1])
    bottom[0], left[0] = c00, c00
    bottom[-1], right[0] = c10, c10
    top[-1], right[-1] = c11, c11
    top[0], left[-1] = c01, c01

    u = np.linspace(0.0, 1.0, nu)[None, :, None]
    v = np.linspace(0.0, 1.0, nv)[:, None, None]
    bilinear_corners = (
        (1.0 - u) * (1.0 - v) * c00
        + u * (1.0 - v) * c10
        + u * v * c11
        + (1.0 - u) * v * c01
    )
    return (
        (1.0 - v) * bottom[None, :, :]
        + v * top[None, :, :]
        + (1.0 - u) * left[:, None, :]
        + u * right[:, None, :]
        - bilinear_corners
    )


def _apply_no_gap_borders_once(
    facets: List[Facet],
    n_u: int,
    n_v: int,
    mode: GapSurfaceMode,
    preserve_z: bool,
    source,
    spreads,
) -> None:
    if mode not in (
        GapSurfaceMode.NEW_BORDER,
        GapSurfaceMode.OLD_BORDER,
        GapSurfaceMode.AVERAGE,
    ):
        return
    optical = [f for f in facets if not f.is_gap_surface]
    edge_deltas = {
        id(f): {"left": None, "right": None, "bottom": None, "top": None}
        for f in optical
    }

    def sampled_edge(facet: Facet, axis: str, edge: str, count: int) -> np.ndarray:
        return _evaluated_edge(facet, axis, edge, count)

    def choose_targets(old, new, axis, old_edge_name, new_edge_name):
        old_count = old.ctrl.shape[0] if axis == "v" else old.ctrl.shape[1]
        new_count = new.ctrl.shape[0] if axis == "v" else new.ctrl.shape[1]
        old_edge_for_old = sampled_edge(old, axis, old_edge_name, old_count)
        new_edge_for_new = sampled_edge(new, axis, new_edge_name, new_count)
        old_edge_for_new = sampled_edge(old, axis, old_edge_name, new_count)
        new_edge_for_old = sampled_edge(new, axis, new_edge_name, old_count)
        if mode == GapSurfaceMode.NEW_BORDER:
            old_target = old_edge_for_old
            new_target = old_edge_for_new
        elif mode == GapSurfaceMode.OLD_BORDER:
            old_target = new_edge_for_old
            new_target = new_edge_for_new
        else:
            old_target = 0.5 * (old_edge_for_old + new_edge_for_old)
            new_target = 0.5 * (old_edge_for_new + new_edge_for_new)
        if preserve_z:
            old_target = old_target.copy()
            new_target = new_target.copy()
            old_target[:, 2] = old_edge_for_old[:, 2]
            new_target[:, 2] = new_edge_for_new[:, 2]
        return old_target, new_target

    for iu in range(n_u - 1):
        old_group = _pair_patch_facets(optical, "index_u", iu)
        new_group = _pair_patch_facets(optical, "index_u", iu + 1)
        for old, new in zip(old_group, new_group):
            old_target, new_target = choose_targets(old, new, "v", "right", "left")
            edge_deltas[id(old)]["right"] = _edge_control_delta(
                old, "v", "right", old_target
            )
            edge_deltas[id(new)]["left"] = _edge_control_delta(
                new, "v", "left", new_target
            )

    for iv in range(n_v - 1):
        old_group = _pair_patch_facets(optical, "index_v", iv)
        new_group = _pair_patch_facets(optical, "index_v", iv + 1)
        for old, new in zip(old_group, new_group):
            old_target, new_target = choose_targets(old, new, "u", "top", "bottom")
            edge_deltas[id(old)]["top"] = _edge_control_delta(
                old, "u", "top", old_target
            )
            edge_deltas[id(new)]["bottom"] = _edge_control_delta(
                new, "u", "bottom", new_target
            )

    for facet in optical:
        deltas = edge_deltas[id(facet)]
        ctrl = facet.ctrl
        left = deltas["left"]
        right = deltas["right"]
        bottom = deltas["bottom"]
        top = deltas["top"]
        if left is None:
            left = np.zeros((ctrl.shape[0], 3))
        if right is None:
            right = np.zeros((ctrl.shape[0], 3))
        if bottom is None:
            bottom = np.zeros((ctrl.shape[1], 3))
        if top is None:
            top = np.zeros((ctrl.shape[1], 3))
        facet.ctrl = ctrl + _coons_control_delta(ctrl, left, right, bottom, top)

    for facet in optical:
        _refresh_facet_geometry(facet, source, spreads)


def _apply_no_gap_borders(
    facets: List[Facet],
    n_u: int,
    n_v: int,
    mode: GapSurfaceMode,
    preserve_z: bool,
    source,
    spreads,
) -> None:
    _apply_no_gap_borders_once(
        facets, n_u, n_v, mode, preserve_z, source, spreads
    )


def _reparam_arc_length(edge: np.ndarray, n: int) -> np.ndarray:
    """Resample a polyline edge to n points by normalised arc length."""
    edge = np.asarray(edge, dtype=float)
    if len(edge) == 0:
        return edge
    if len(edge) == 1 or n <= 1:
        return np.repeat(edge[:1], n, axis=0)
    seg = np.linalg.norm(np.diff(edge, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    if cum[-1] < 1e-14:
        return np.repeat(edge[:1], n, axis=0)
    cum /= cum[-1]
    targets = np.linspace(0.0, 1.0, n)
    out = np.zeros((n, 3))
    for k, t in enumerate(targets):
        idx = int(np.searchsorted(cum, t, side="right") - 1)
        idx = min(max(idx, 0), len(edge) - 2)
        t0, t1 = cum[idx], cum[idx + 1]
        alpha = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
        out[k] = (1.0 - alpha) * edge[idx] + alpha * edge[idx + 1]
    return out


def _make_gap_surface(
    edge_a: np.ndarray,
    edge_b: np.ndarray,
    samples_u: int,
    samples_v: int,
    degree: int = 3,
) -> Facet:
    """
    One ruled NURBS face between two facing optical edges.

    Degree-1 poles-on-samples used to produce a polyline strip (CATIA shows
    every span as a separate brick).  Both rails are interpolated with a
    shared knot vector so the loft is a single C2-along-the-seam surface
    that still meets the sampled optical edges.
    """
    from geometry.nurbs import (
        _chord_params,
        _interpolate_curve,
        _interpolating_knots,
        open_uniform_knots,
    )

    n = max(2, max(len(edge_a), len(edge_b)))
    ea = _reparam_arc_length(edge_a, n)
    eb = _reparam_arc_length(edge_b, n)
    deg_u = min(max(1, int(degree)), n - 1)
    deg_v = 1
    params = 0.5 * (_chord_params(ea) + _chord_params(eb))
    params[0], params[-1] = 0.0, 1.0
    knots_u = _interpolating_knots(params, deg_u)
    ctrl_a = _interpolate_curve(ea, deg_u, params, knots_u)
    ctrl_b = _interpolate_curve(eb, deg_u, params, knots_u)
    ctrl = np.stack([ctrl_a, ctrl_b], axis=0)
    knots_v = open_uniform_knots(2, deg_v)
    corners = np.array([ea[0], ea[n - 1], eb[n - 1], eb[0]])
    center = corners.mean(axis=0)
    t1 = ea[n - 1] - ea[0]
    t2 = eb[0] - ea[0]
    nrm = np.cross(t1, t2)
    normal = _unit(nrm) if np.linalg.norm(nrm) > 1e-12 else np.array([0.0, 0.0, 1.0])
    return Facet(
        index_u=-1, index_v=-1,
        center=center, normal=normal,
        size_u=float(np.linalg.norm(ea[n - 1] - ea[0])),
        size_v=float(np.linalg.norm(eb[0] - ea[0])),
        corners=corners,
        samples_u=max(2, n),
        samples_v=2,
        is_nurbs=True,
        ctrl=ctrl, degree_u=deg_u, degree_v=deg_v,
        knots_u=knots_u, knots_v=knots_v,
        is_gap_surface=True,
    )


def _make_gap_corner_surface(
    p00: np.ndarray,
    p10: np.ndarray,
    p11: np.ndarray,
    p01: np.ndarray,
    samples_u: int,
    samples_v: int,
) -> Facet:
    """Bilinear patch closing the small hole where U and V gaps intersect."""
    from geometry.nurbs import open_uniform_knots

    ctrl = np.asarray([[p00, p10], [p01, p11]], dtype=float)
    corners = np.asarray([p00, p10, p11, p01], dtype=float)
    center = corners.mean(axis=0)
    normal = np.cross(p10 - p00, p01 - p00)
    normal = _unit(normal) if np.linalg.norm(normal) > 1e-12 else np.array([0.0, 0.0, 1.0])
    return Facet(
        index_u=-1,
        index_v=-1,
        center=center,
        normal=normal,
        size_u=float(np.linalg.norm(p10 - p00)),
        size_v=float(np.linalg.norm(p01 - p00)),
        corners=corners,
        samples_u=max(2, samples_u),
        samples_v=max(2, samples_v),
        is_nurbs=True,
        ctrl=ctrl,
        degree_u=1,
        degree_v=1,
        knots_u=open_uniform_knots(2, 1),
        knots_v=open_uniform_knots(2, 1),
        is_gap_surface=True,
    )


def _corner_facet(
    facets: Sequence[Facet],
    iu: int,
    iv: int,
    patch_u: int,
    patch_v: int,
) -> Facet:
    return next(
        f
        for f in facets
        if not f.is_gap_surface
        and f.index_u == iu
        and f.index_v == iv
        and f.patch_index_u == patch_u
        and f.patch_index_v == patch_v
    )


def _ensure_patch_samples(
    reflector: MFReflector, samples_u: Optional[int], samples_v: Optional[int]
) -> Tuple[int, int]:
    """把每面片采样数调到能支撑拟合块数/连续性，并同步回 reflector.mesh_u/v。

    Equal sample counts per sub-patch keep shared knot vectors identical,
    which is required for geometric (not merely control-net) continuity.
    """
    grid = reflector.grid
    su = max(2, samples_u if samples_u is not None else reflector.mesh_u)
    sv = max(2, samples_v if samples_v is not None else reflector.mesh_v)
    for patches, degree in (
        (reflector.fit_patches_u, grid.degree_u),
        (reflector.fit_patches_v, grid.degree_v),
    ):
        if patches <= 1:
            continue
        needed = patches * (degree + 1) + 1
        if su < needed:
            su = needed
        if (su - 1) % patches:
            su += patches - ((su - 1) % patches)
        if sv < needed:
            sv = needed
        if (sv - 1) % patches:
            sv += patches - ((sv - 1) % patches)
    reflector.mesh_u = su
    reflector.mesh_v = sv
    return su, sv


def _add_gap_surfaces(
    facets: List[Facet],
    reflector: MFReflector,
    n_u: int,
    n_v: int,
    su: int,
    sv: int,
    gap_u: float,
    gap_v: float,
    degree_u: int,
    degree_v: int,
) -> None:
    """gap 模式：相邻面片间生成 ruled 缝隙面，并封堵 U/V 缝隙交叉点的小孔。"""
    edge_cache: Dict[Tuple[int, int, int, int], Dict[str, np.ndarray]] = {}
    ts_u = np.linspace(0.0, 1.0, su)
    ts_v = np.linspace(0.0, 1.0, sv)
    for facet in facets:
        if facet.is_gap_surface or facet.ctrl is None:
            continue
        key = (
            facet.index_u,
            facet.index_v,
            facet.patch_index_u,
            facet.patch_index_v,
        )
        edge_cache[key] = {
            "left": np.asarray([_eval_facet(facet, 0.0, t) for t in ts_v]),
            "right": np.asarray([_eval_facet(facet, 1.0, t) for t in ts_v]),
            "bottom": np.asarray([_eval_facet(facet, t, 0.0) for t in ts_u]),
            "top": np.asarray([_eval_facet(facet, t, 1.0) for t in ts_u]),
        }

    if gap_u > 0:
        for iv in range(n_v):
            for iu in range(n_u - 1):
                left = sorted(
                    [f for f in facets if not f.is_gap_surface and f.index_u == iu and f.index_v == iv],
                    key=lambda f: f.patch_index_u,
                )
                right = sorted(
                    [f for f in facets if not f.is_gap_surface and f.index_u == iu + 1 and f.index_v == iv],
                    key=lambda f: f.patch_index_u,
                )
                for f_old, f_new in zip(left, right):
                    key_old = (f_old.index_u, f_old.index_v, f_old.patch_index_u, f_old.patch_index_v)
                    key_new = (f_new.index_u, f_new.index_v, f_new.patch_index_u, f_new.patch_index_v)
                    gap_facet = _make_gap_surface(
                        edge_cache[key_old]["right"],
                        edge_cache[key_new]["left"],
                        su,
                        sv,
                        degree=max(degree_u, degree_v, 3),
                    )
                    gap_facet.index_u = iu
                    gap_facet.index_v = iv
                    facets.append(gap_facet)
    if gap_v > 0:
        for iu in range(n_u):
            for iv in range(n_v - 1):
                lower = sorted(
                    [f for f in facets if not f.is_gap_surface and f.index_u == iu and f.index_v == iv],
                    key=lambda f: f.patch_index_v,
                )
                upper = sorted(
                    [f for f in facets if not f.is_gap_surface and f.index_u == iu and f.index_v == iv + 1],
                    key=lambda f: f.patch_index_v,
                )
                for f_old, f_new in zip(lower, upper):
                    key_old = (f_old.index_u, f_old.index_v, f_old.patch_index_u, f_old.patch_index_v)
                    key_new = (f_new.index_u, f_new.index_v, f_new.patch_index_u, f_new.patch_index_v)
                    gap_facet = _make_gap_surface(
                        edge_cache[key_old]["top"],
                        edge_cache[key_new]["bottom"],
                        su,
                        sv,
                        degree=max(degree_u, degree_v, 3),
                    )
                    gap_facet.index_u = iu
                    gap_facet.index_v = iv
                    facets.append(gap_facet)

    # Close the small hole at every intersection of a U gap and a V gap.
    if gap_u > 0 and gap_v > 0:
        max_patch_u = reflector.fit_patches_u - 1
        max_patch_v = reflector.fit_patches_v - 1
        for iv in range(n_v - 1):
            for iu in range(n_u - 1):
                lower_left = _corner_facet(facets, iu, iv, max_patch_u, max_patch_v)
                lower_right = _corner_facet(facets, iu + 1, iv, 0, max_patch_v)
                upper_right = _corner_facet(facets, iu + 1, iv + 1, 0, 0)
                upper_left = _corner_facet(facets, iu, iv + 1, max_patch_u, 0)
                corner = _make_gap_corner_surface(
                    _eval_facet(lower_left, 1.0, 1.0),
                    _eval_facet(lower_right, 0.0, 1.0),
                    _eval_facet(upper_right, 0.0, 0.0),
                    _eval_facet(upper_left, 1.0, 0.0),
                    su,
                    sv,
                )
                corner.index_u = iu
                corner.index_v = iv
                facets.append(corner)


def generate_facets(
    reflector: MFReflector,
    samples_u: int | None = None,
    samples_v: int | None = None,
) -> List[Facet]:
    """Generate NURBS facets and optional gap-surface connectors."""
    grid = reflector.grid
    spreads = reflector.spreads
    source = reflector.source.position.copy()
    gaps = reflector.gaps

    su, sv = _ensure_patch_samples(reflector, samples_u, samples_v)

    n_u, n_v = grid.n_u, grid.n_v
    degree_u, degree_v = grid.degree_u, grid.degree_v
    x_coords, y_coords, z, su_g, sv_g, blocks = _build_height_field(reflector)
    step_u = su_g - 1
    step_v = sv_g - 1

    gap_u = gaps.effective_gap_u()
    gap_v = gaps.effective_gap_v()
    if gap_u < 0 or gap_v < 0:
        raise ValueError("gap sizes must be non-negative for gap / step-back modes")
    use_surface = (
        gaps.enabled
        and gaps.gap_type in (GapType.GAP, GapType.STEP_BACK)
        and gaps.surface_mode == GapSurfaceMode.SURFACE
        and (gap_u > 0 or gap_v > 0)
    )
    no_gap_borders = gaps.gap_type in (GapType.NO_GAP, GapType.STEP_BACK_NO_GAP)

    facets: List[Facet] = []
    z_step_u = reflector.z_step_u + gaps.effective_step_z()
    z_step_v = reflector.z_step_v + gaps.effective_step_z()

    for iv in range(n_v):
        for iu in range(n_u):
            # Sample this facet from its own solved block: neighbours share
            # border columns in the full z array, and the last solver would
            # overwrite them.  Using the per-facet block keeps every facet's
            # sample grid consistent with its own solution.
            blk = blocks[(iu, iv)]
            xs_b = x_coords[iu * step_u:(iu + 1) * step_u + 1]
            ys_b = y_coords[iv * step_v:(iv + 1) * step_v + 1]
            sub = np.asarray(
                [[[xs_b[i], ys_b[j], blk[j, i]] for i in range(su)]
                 for j in range(sv)],
                dtype=float,
            )
            width = grid.width_deltas[iu]
            height = grid.height_deltas[iv]
            # deltas include gap: internal side loses gap/2, outer side loses 0
            half_gu = (gap_u * 0.5 / width) if gap_u and width > 0 else 0.0
            half_gv = (gap_v * 0.5 / height) if gap_v and height > 0 else 0.0
            shrink_left = half_gu if iu > 0 else 0.0
            shrink_right = half_gu if iu < n_u - 1 else 0.0
            shrink_bottom = half_gv if iv > 0 else 0.0
            shrink_top = half_gv if iv < n_v - 1 else 0.0
            if shrink_left + shrink_right >= 1.0 - 1e-9 or shrink_bottom + shrink_top >= 1.0 - 1e-9:
                raise ValueError(
                    "gap size must be smaller than the facet delta; "
                    "derived shrink would consume an entire facet"
                )
            z_step = iu * z_step_u + iv * z_step_v
            if reflector.fit_patches_u == 1 and reflector.fit_patches_v == 1:
                facets.append(
                    _make_facet_nurbs_from_grid(
                        sub,
                        iu,
                        iv,
                        degree_u,
                        degree_v,
                        su,
                        sv,
                        source,
                        spreads,
                        shrink_left,
                        shrink_right,
                        shrink_bottom,
                        shrink_top,
                        reflector.patch_fit_method,
                        uniform_parameters=no_gap_borders,
                        z_step=z_step,
                    )
                )
            else:
                facets.extend(
                    _make_facet_patches(
                        sub,
                        iu,
                        iv,
                        degree_u,
                        degree_v,
                        source,
                        spreads,
                        shrink_left,
                        shrink_right,
                        shrink_bottom,
                        shrink_top,
                        reflector.patch_fit_method,
                        reflector.fit_patches_u,
                        reflector.fit_patches_v,
                        reflector.fit_patch_continuity_u,
                        reflector.fit_patch_continuity_v,
                        z_step,
                        no_gap_borders,
                    )
                )

    if no_gap_borders:
        _apply_no_gap_borders(
            facets,
            n_u,
            n_v,
            gaps.surface_mode,
            preserve_z=abs(z_step_u) > 1e-12 or abs(z_step_v) > 1e-12,
            source=source,
            spreads=spreads,
        )

    if use_surface:
        _add_gap_surfaces(
            facets, reflector, n_u, n_v, su, sv, gap_u, gap_v, degree_u, degree_v
        )

    reflector.facets = facets
    return facets
