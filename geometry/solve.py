# SPDX-License-Identifier: MIT
"""单面片光学求解与远场校正（目标函数、定态迭代、仿射校准、抛光）。"""

from __future__ import annotations

from typing import Dict, Optional, Tuple
import logging

import numpy as np

from models.facet import Facet
from models.reflector import MFReflector
from models.enums import (
    SolveMethod,
)
from geometry import tuning
from geometry.mathutils import (
    _eval_target_grid,
    _height_slopes,
    _slopes_on_surface_static,
    _target_direction_from_angles,
    _unit_nd,
)
from geometry.reconstruction import _SlopeHeightSolver, _reconstruct_height_by_paths
from geometry.flux import _flux_quantile_map


logger = logging.getLogger(__name__)



def _target_fn_from_fracs(spreads, iu: int, iv: int, frac_u: np.ndarray, frac_v: np.ndarray):
    fu = np.asarray(frac_u, dtype=float)
    fv = np.asarray(frac_v, dtype=float)

    def fn(li, lj, fu=fu, fv=fv, iu=iu, iv=iv):
        array_input = np.ndim(li) > 0 or np.ndim(lj) > 0
        if fu.ndim == 2:
            j = np.clip(lj, 0, fu.shape[0] - 1)
            i = np.clip(li, 0, fu.shape[1] - 1)
            if array_input:
                return spreads.target_angles_on_facet_grid(
                    iu, iv, fu[j.astype(int), i.astype(int)],
                    fv[j.astype(int), i.astype(int)],
                )
            return spreads.target_angles_on_facet(
                iu, iv, float(fu[int(j), int(i)]), float(fv[int(j), int(i)])
            )
        i = np.clip(li, 0, fu.size - 1).astype(int)
        j = np.clip(lj, 0, fv.size - 1).astype(int)
        if array_input:
            return spreads.target_angles_on_facet_grid(iu, iv, fu[i], fv[j])
        return spreads.target_angles_on_facet(iu, iv, float(fu[int(i)]), float(fv[int(j)]))

    return fn


def _apply_affine(h: float, v: float, a1: float, b1: float, a2: float, b2: float) -> Tuple[float, float]:
    if abs(b1) < 1e-6:
        b1 = 1.0
    if abs(b2) < 1e-6:
        b2 = 1.0
    return (h - a1) / b1, (v - a2) / b2


def _level_row_h(
    z: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    source: np.ndarray,
    h0: float,
    h1: float,
    seed_i: int,
    gain: float = 0.45,
) -> np.ndarray:
    """
    Per-row H-endpoint correction.

    A linear Δz = s(y)·(x-xmid) only *shifts* the whole row in H
    (Δzx is constant).  The inverted-trapezoid error is a *span*
    error, so we also add a quadratic stretch
        Δz = c(y)·(x-xmid)²
    which gives opposite Δzx on the two H edges.  A 2×2 Newton per
    row solves (shift, stretch) so both endpoints approach (h0, h1).
    """
    z = np.asarray(z, dtype=float).copy()
    xs = np.asarray(xs, dtype=float)
    nv, nu = z.shape
    if nu < 3:
        return z
    mid_i = nu // 2
    seed_i = int(np.clip(mid_i if seed_i is None else seed_i, 0, nu - 1))
    lever = xs - xs[seed_i]
    quad = lever * lever
    hs, _ = _realized_angles_on_block(z, xs, ys, source)
    eps_s, eps_c = 1e-4, 1e-5
    hs_s, _ = _realized_angles_on_block(z + eps_s * lever[None, :], xs, ys, source)
    hs_c, _ = _realized_angles_on_block(z + eps_c * quad[None, :], xs, ys, source)
    Js0 = (hs_s[:, 0] - hs[:, 0]) / eps_s
    Js1 = (hs_s[:, -1] - hs[:, -1]) / eps_s
    Jc0 = (hs_c[:, 0] - hs[:, 0]) / eps_c
    Jc1 = (hs_c[:, -1] - hs[:, -1]) / eps_c
    e0 = float(h0) - hs[:, 0]
    e1 = float(h1) - hs[:, -1]
    g = float(gain)
    span = float(np.max(np.abs(xs)) + 1.0)
    s = np.zeros(nv, dtype=float)
    c = np.zeros(nv, dtype=float)
    for j in range(nv):
        A = np.array([[Js0[j], Jc0[j]], [Js1[j], Jc1[j]]], dtype=float)
        try:
            det = float(A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0])
        except Exception:
            det = 0.0
        if abs(det) < 1e-10:
            continue
        sc = np.linalg.solve(A, np.array([e0[j], e1[j]], dtype=float))
        s[j] = sc[0]
        c[j] = sc[1]
    s = np.clip(g * s, -0.20, 0.20)
    c = np.clip(g * c, -0.20 / max(span, 1.0), 0.20 / max(span, 1.0))
    z += s[:, None] * lever[None, :] + c[:, None] * quad[None, :]
    return z


def _pin_v_edge_nodes(
    z: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    source: np.ndarray,
    v0: float,
    v1: float,
    gain: float = 0.7,
    zclip: float = 0.25,
) -> np.ndarray:
    """
    Flatten realized V on the top and bottom *bands* (not a single row).

    A one-row z bump is invisible to a degree-5 interpolating NURBS, so
    the exported surface keeps the FFD smile (corners at V≈−17°, centre
    at −11°).  Spreading the same Newton step over a few rows keeps zy
    after the fit.
    """
    z = np.asarray(z, dtype=float).copy()
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    nv, nu = z.shape
    if nv < 2:
        return z
    _, vs = _realized_angles_on_block(z, xs, ys, source)
    eps = 1e-4
    g = float(gain)
    z_b = z.copy()
    z_b[0, :] += eps
    _, vs_b = _realized_angles_on_block(z_b, xs, ys, source)
    dV = (vs_b[0, :] - vs[0, :]) / eps
    dV = np.where(np.abs(dV) < 1e-8, 1e-8, dV)
    z[0, :] += np.clip(g * (float(v0) - vs[0, :]) / dV, -zclip, zclip)

    z_t = z.copy()
    z_t[-1, :] += eps
    _, vs_t = _realized_angles_on_block(z_t, xs, ys, source)
    dV = (vs_t[-1, :] - vs[-1, :]) / eps
    dV = np.where(np.abs(dV) < 1e-8, 1e-8, dV)
    z[-1, :] += np.clip(g * (float(v1) - vs[-1, :]) / dV, -zclip, zclip)
    return z


def _polish_farfield_rectangle(
    z: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    source: np.ndarray,
    h0: float,
    h1: float,
    v0: float,
    v1: float,
    passes: int = 6,
) -> np.ndarray:
    """
    Surface-space outline lock.

    1. Per-row H shift+stretch kills the off-axis inverted trapezoid.
    2. Pin first/last V rows to (Vmin, Vmax).  Needed when F.Start
       sits on the +V edge and that row overshoots the angle list.
    3. Light four-edge Newton cleans leftover corner errors.
    """
    z = np.asarray(z, dtype=float).copy()
    nu = z.shape[1]
    # Keep this mild.  Stacking H-quadratic + multi-row V pin + four-edge
    # Newton made the NURBS corners spray rays (the two "legs" at ±15°, −25°).
    npass = min(3, max(1, int(passes)))
    for k in range(npass):
        g = tuning.POLISH_GAIN_BASE * (tuning.POLISH_GAIN_DECAY ** k)
        z = _level_row_h(z, xs, ys, source, h0, h1, seed_i=nu // 2, gain=g)
    for k in range(3):
        z = _pin_v_edge_nodes(
            z, xs, ys, source, v0, v1,
            gain=tuning.POLISH_PIN_GAIN_BASE * (tuning.POLISH_GAIN_DECAY ** k),
            zclip=tuning.POLISH_ZCLIP,
        )
    return z


def _solve_facet_optical(
    reflector: MFReflector,
    xs: np.ndarray,
    ys: np.ndarray,
    source: np.ndarray,
    target_fn,
    su: int,
    sv: int,
    z_seed: float,
    seed_i: int,
    seed_j: int,
    z_init: np.ndarray,
) -> np.ndarray:
    """
    Single surface from a seed height.

    Uniform-intensity / LucidShape FFD: path-integrate the reflection-law
    slopes in the user's FunGeo order and lock the four graph edges.
    Least-squares averaging of those slopes is what flattened every row
    onto the same zx and left the inverted trapezoid LucidShape does not
    produce on the same inputs.

    Off (legacy): conservative LS projection only.
    """
    max_iter = max(1, int(reflector.solver_iterations))
    tol = max(0.0, float(reflector.solver_tolerance))
    z_loc = np.asarray(z_init, dtype=float).copy()
    h_grid, v_grid = _eval_target_grid(target_fn, su, sv)
    # 设计矩阵只依赖网格几何：整个迭代序列复用一次预分解。
    ls_solver = _SlopeHeightSolver.for_seed(
        xs, ys, z_seed, seed_i, seed_j, edge_weight=tuning.EDGE_WEIGHT
    )
    # 网格坐标与目标方向在迭代间不变，一并提到循环外。
    xx, yy = np.meshgrid(xs, ys)
    targets = _target_direction_from_angles(h_grid, v_grid)
    use_sep = bool(reflector.spreads.uniform_intensity)
    for _ in range(max_iter):
        dzx, dzy = _slopes_on_surface_static(xx, yy, z_loc, source, targets)
        if use_sep:
            z_u = _reconstruct_height_by_paths(
                dzx, dzy, xs, ys, z_seed, seed_i, seed_j, SolveMethod.U_FIRST,
            )
            z_ls = ls_solver.solve(dzx, dzy)
            # Paths keep iso-V from smiling; LS keeps a single smooth
            # graph.  FFD border-lock + heavy polish sprayed the corners.
            w_paths, w_ls = tuning.PATHS_LS_BLEND
            z_new = w_paths * z_u + w_ls * z_ls
        else:
            z_new = ls_solver.solve(dzx, dzy)
        delta = float(np.max(np.abs(z_new - z_loc)))
        z_loc = z_new
        if delta <= tol:
            break
    return z_loc


def _realized_angles_on_block(
    blk: np.ndarray,
    xs: np.ndarray,
    ys: np.ndarray,
    source: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Reflected (h, v) deg at every node of a height-field block."""
    sv, su = blk.shape
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    blk = np.asarray(blk, dtype=float)
    zx, zy = _height_slopes(xs, ys, blk)
    n = np.stack((-zx, -zy, np.ones((sv, su), dtype=float)), axis=-1)
    ln = np.linalg.norm(n, axis=-1, keepdims=True)
    valid = ln[..., 0] >= 1e-14
    n = np.divide(n, np.maximum(ln, 1e-30))
    xx, yy = np.meshgrid(xs, ys)
    pts = np.stack((xx, yy, blk), axis=-1)
    I = pts - np.asarray(source, dtype=float).reshape(3)
    I = _unit_nd(I)
    dots = np.sum(I * n, axis=-1, keepdims=True)
    R = I - 2.0 * dots * n
    R = _unit_nd(R)
    hs = np.rad2deg(np.arctan2(R[..., 0], R[..., 2]))
    vs = np.rad2deg(np.arcsin(np.clip(R[..., 1], -1.0, 1.0)))
    hs = np.where(valid, hs, 0.0)
    vs = np.where(valid, vs, 0.0)
    return hs, vs


def _table_target_fn(asked_h: np.ndarray, asked_v: np.ndarray, su: int, sv: int):
    """1-D 查表目标闭包：H 只依赖 li、V 只依赖 lj；标量与整网格数组双路径。"""
    ah = np.asarray(asked_h, dtype=float)
    av = np.asarray(asked_v, dtype=float)

    def fn(li, lj):
        ci = np.clip(li, 0, su - 1)
        cj = np.clip(lj, 0, sv - 1)
        if np.ndim(li) > 0 or np.ndim(lj) > 0:
            return ah[ci.astype(int)], av[cj.astype(int)]
        return float(ah[int(ci)]), float(av[int(cj)])

    return fn


def _row_h_preemphasis(
    inner_fn,
    realized_h: np.ndarray,
    h0: float,
    h1: float,
    gain: float = tuning.PREEMPHASIS_GAIN,
):
    """
    Per-row H-span calibration in angle space.

    Off-axis LS realizes a slightly wider top than bottom.  Scale each
    row's asked H toward (h1-h0)/realized_span so the next solve
    straightens the sides without a z-space warp.
    """
    rh = np.asarray(realized_h, dtype=float)
    nv = rh.shape[0]
    want = float(h1) - float(h0)
    got = rh[:, -1] - rh[:, 0]
    scale = np.ones(nv, dtype=float)
    ok = np.abs(got) > 1e-6
    scale[ok] = want / got[ok]
    scale = 1.0 + float(gain) * (scale - 1.0)
    scale = np.clip(scale, *tuning.PREEMPHASIS_SCALE_CLIP)
    mid = 0.5 * (float(h0) + float(h1))
    half = 0.5 * abs(want) * tuning.PREEMPHASIS_HALF_FACTOR

    def fn(li, lj, inner=inner_fn, sc=scale, mid=mid, half=half):
        h, v = inner(li, lj)
        cj = np.clip(lj, 0, sc.size - 1)
        if np.ndim(li) > 0 or np.ndim(lj) > 0:
            s = sc[cj.astype(int)]
        else:
            s = float(sc[int(cj)])
            return float(np.clip(mid + s * (h - mid), mid - half, mid + half)), v
        return np.clip(mid + s * (h - mid), mid - half, mid + half), v

    return fn


def _spatial_intensity_inverse(
    iu: int,
    iv: int,
    su: int,
    sv: int,
    spreads,
    realized_h: np.ndarray,
    realized_v: np.ndarray,
    flux: np.ndarray,
    gain: float = 0.8,
    target_min: float = 0.1,
):
    """
    One FFD-style spatial step: flatten I(H,V) by equalizing flux vs
    realized H and vs realized V, keeping a rectangular outline.
    """
    h0, _ = spreads.target_angles_on_facet(iu, iv, 0.0, 0.5)
    h1, _ = spreads.target_angles_on_facet(iu, iv, 1.0, 0.5)
    _, v0 = spreads.target_angles_on_facet(iu, iv, 0.5, 0.0)
    _, v1 = spreads.target_angles_on_facet(iu, iv, 0.5, 1.0)
    rh = np.asarray(realized_h, dtype=float)
    rv = np.asarray(realized_v, dtype=float)
    w = np.maximum(np.asarray(flux, dtype=float), 0.0)
    h_des = _flux_quantile_map(rh, w, h0, h1, target_min).reshape(rh.shape)
    v_des = _flux_quantile_map(rv, w, v0, v1, target_min).reshape(rv.shape)
    col = np.maximum(w.sum(axis=0), 1e-30)
    row = np.maximum(w.sum(axis=1), 1e-30)
    eq_h = (h_des * w).sum(axis=0) / col
    eq_v = (v_des * w).sum(axis=1) / row
    real_h = (rh * w).sum(axis=0) / col
    real_v = (rv * w).sum(axis=1) / row
    asked_h = eq_h + float(gain) * (eq_h - real_h)
    asked_v = eq_v + float(gain) * (eq_v - real_v)
    h_lo, h_hi = (h0, h1) if h0 <= h1 else (h1, h0)
    v_lo, v_hi = (v0, v1) if v0 <= v1 else (v1, v0)
    asked_h = np.clip(asked_h, h_lo, h_hi)
    asked_v = np.clip(asked_v, v_lo, v_hi)
    asked_h[0] = h0
    asked_h[-1] = h1
    asked_v[0] = v0
    asked_v[-1] = v1

    return _row_h_preemphasis(
        _table_target_fn(asked_h, asked_v, su, sv),
        rh, h0, h1, gain=tuning.PREEMPHASIS_GAIN,
    )


def _separable_inverse_target(
    iu: int,
    iv: int,
    su: int,
    sv: int,
    spreads,
    realized_h: np.ndarray,
    realized_v: np.ndarray,
    a1: float,
    b1: float,
    a2: float,
    b2: float,
    gain: float = 0.85,
    frac_u: Optional[np.ndarray] = None,
    frac_v: Optional[np.ndarray] = None,
):
    """
    Build H(u), V(v) asked-angle maps by inverting the measured
    column-mean / row-mean realised angles.

    asked(u) = affine(target(u)) + gain * (target(u) - realised_mean(u))
    so interior nodes that currently undershoot +V request a larger V.
    """
    if abs(b1) < 1e-6:
        b1 = 1.0
    if abs(b2) < 1e-6:
        b2 = 1.0

    tgt_h = np.zeros(su)
    tgt_v = np.zeros(sv)
    fu = np.asarray(frac_u, dtype=float) if frac_u is not None else None
    fv = np.asarray(frac_v, dtype=float) if frac_v is not None else None
    for i in range(su):
        lu = float(fu[i]) if fu is not None else i / max(su - 1, 1)
        tgt_h[i] = spreads.target_angles_on_facet(iu, iv, lu, 0.5)[0]
    for j in range(sv):
        lv = float(fv[j]) if fv is not None else j / max(sv - 1, 1)
        tgt_v[j] = spreads.target_angles_on_facet(iu, iv, 0.5, lv)[1]

    # Mean realised profile (separable)
    real_h = np.mean(realized_h, axis=0)
    real_v = np.mean(realized_v, axis=1)

    asked_h = (tgt_h - a1) / b1 + gain * (tgt_h - real_h)
    asked_v = (tgt_v - a2) / b2 + gain * (tgt_v - real_v)

    # Keep a bounded overdrive so the surface cannot fold.
    # Use min/max of the list.  A decreasing list such as V=(10,-10)
    # makes tgt[0]-span / tgt[-1]+span collapse to ~[-2,+2] and the
    # far-field squashes into two thin horizontal bands.
    h_span = max(abs(tgt_h[-1] - tgt_h[0]), tuning.SEP_SPAN_FLOOR)
    v_span = max(abs(tgt_v[-1] - tgt_v[0]), tuning.SEP_SPAN_FLOOR)
    h_lo, h_hi = float(np.min(tgt_h)), float(np.max(tgt_h))
    v_lo, v_hi = float(np.min(tgt_v)), float(np.max(tgt_v))
    asked_h = np.clip(asked_h, h_lo, h_hi)
    asked_v = np.clip(asked_v, v_lo, v_hi)
    # Soft endpoint blend.  Hard-pinning dumped leftover +V into the last
    # grid row; NURBS then wiped that strip and the far-field clipped ~+6°.
    keep, tgt_w = tuning.SEP_ENDPOINT_KEEP, 1.0 - tuning.SEP_ENDPOINT_KEEP
    asked_h[0] = keep * asked_h[0] + tgt_w * tgt_h[0]
    asked_h[-1] = keep * asked_h[-1] + tgt_w * tgt_h[-1]
    asked_v[0] = keep * asked_v[0] + tgt_w * tgt_v[0]
    asked_v[-1] = keep * asked_v[-1] + tgt_w * tgt_v[-1]
    ka, kb, kc = tuning.SEP_SMOOTH_KERNEL
    if su >= 3:
        asked_h[1:-1] = ka * asked_h[:-2] + kb * asked_h[1:-1] + kc * asked_h[2:]
    if sv >= 3:
        asked_v[1:-1] = ka * asked_v[:-2] + kb * asked_v[1:-1] + kc * asked_v[2:]

    return _table_target_fn(asked_h, asked_v, su, sv)


def _calibrate_facets(
    blocks: Dict[Tuple[int, int], np.ndarray],
    grids: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]],
    source: np.ndarray,
    spreads,
    su: int,
    sv: int,
) -> Dict[Tuple[int, int], Tuple[float, float, float, float]]:
    """
    Per-facet affine calibration of the spread mapping.

    Priority is matching the *boundary extrema* of the realised far-field to
    the requested (h_min, h_max, v_min, v_max) so the spot is a hard rectangle.
    Interior nodes are used only as a fallback when edges are degenerate.

    Model:  realized ≈ a + b · target
    Inverse map used on the next solve:  target' = (desired - a) / b
    """
    calib: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
    for key, blk in blocks.items():
        xs, ys = grids[key]
        iu, iv = key
        hs, vs = _realized_angles_on_block(blk, xs, ys, source)

        # Requested corner angles of this facet
        h00, v00 = spreads.target_angles_on_facet(iu, iv, 0.0, 0.0)
        h10, v10 = spreads.target_angles_on_facet(iu, iv, 1.0, 0.0)
        h01, v01 = spreads.target_angles_on_facet(iu, iv, 0.0, 1.0)
        h11, v11 = spreads.target_angles_on_facet(iu, iv, 1.0, 1.0)
        th_min = min(h00, h10, h01, h11)
        th_max = max(h00, h10, h01, h11)
        tv_min = min(v00, v10, v01, v11)
        tv_max = max(v00, v10, v01, v11)

        # Realised extrema on the four edges (more stable than single corners)
        # left i=0, right i=-1, bottom j=0, top j=-1
        rh_left = float(np.mean(hs[:, 0]))
        rh_right = float(np.mean(hs[:, -1]))
        rv_bot = float(np.mean(vs[0, :]))
        rv_top = float(np.mean(vs[-1, :]))
        rh_min = min(rh_left, rh_right)
        rh_max = max(rh_left, rh_right)
        rv_min = min(rv_bot, rv_top)
        rv_max = max(rv_bot, rv_top)

        def edge_fit(t_min: float, t_max: float, r_min: float, r_max: float):
            dt = t_max - t_min
            if abs(dt) < 1e-9:
                return 0.0, 1.0
            # r = a + b * t  matched at the two ends
            b = (r_max - r_min) / dt
            # keep a mild clip so a bad first pass cannot invert the map
            b = float(np.clip(b, 0.4, 2.5))
            a = r_min - b * t_min
            return float(a), b

        # Orient so that left→th_min side, right→th_max side
        if rh_left <= rh_right:
            ah, bh = edge_fit(th_min, th_max, rh_left, rh_right)
        else:
            ah, bh = edge_fit(th_min, th_max, rh_right, rh_left)
        if rv_bot <= rv_top:
            av, bv = edge_fit(tv_min, tv_max, rv_bot, rv_top)
        else:
            av, bv = edge_fit(tv_min, tv_max, rv_top, rv_bot)

        calib[key] = (ah, bh, av, bv)
    return calib


def _solve_facet_with_borders(
    reflector: MFReflector,
    ref_block,
    spread_target,
    xs: np.ndarray,
    ys: np.ndarray,
    source: np.ndarray,
    zb: Dict[str, Optional[np.ndarray]],
    su: int,
    sv: int,
    z_step: float,
) -> np.ndarray:
    """Fixed-point solve of one facet with fixed border curves (+ z step)."""
    max_iter = max(1, int(reflector.solver_iterations))
    tol = max(0.0, float(reflector.solver_tolerance))
    if all(arr is None for arr in zb.values()):
        # Single-facet reflector (or fully free borders): nothing to stitch —
        # keep the absolute pass-1 solution, only add the Z step.
        return np.asarray(ref_block, dtype=float) + z_step
    # Initial guess: the pass-1 block (its borders are replaced by zb below).
    z_loc = np.asarray(ref_block, dtype=float).copy()
    for side, arr in zb.items():
        if arr is None:
            continue
        arr = np.asarray(arr, dtype=float)
        if side in ("left", "right"):
            idx = 0 if side == "left" else su - 1
            z_loc[:, idx] = arr
        else:
            idx = 0 if side == "bottom" else sv - 1
            z_loc[idx, :] = arr
    h_grid, v_grid = _eval_target_grid(spread_target, su, sv)
    xx, yy = np.meshgrid(xs, ys)
    targets = _target_direction_from_angles(h_grid, v_grid)
    ls_solver = _SlopeHeightSolver.for_borders(xs, ys, zb)
    for _ in range(max_iter):
        dzx, dzy = _slopes_on_surface_static(xx, yy, z_loc, source, targets)
        z_new = ls_solver.solve(dzx, dzy)
        delta = float(np.max(np.abs(z_new - z_loc)))
        z_loc = z_new
        if delta <= tol:
            break
    return z_loc + z_step


def _eval_facet(facet: Facet, u: float, v: float) -> np.ndarray:
    from geometry.nurbs import eval_surface
    return eval_surface(
        facet.ctrl,
        facet.degree_u,
        facet.degree_v,
        facet.knots_u,
        facet.knots_v,
        u,
        v,
    )
