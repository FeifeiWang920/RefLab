# SPDX-License-Identifier: MIT
"""向量与坐标原语：单位化、反射目标方向、所需法线、坡度与载体高度。"""

from __future__ import annotations

from typing import Tuple
import logging

import numpy as np

from models.enums import (
    EdgeRayMode,
)


logger = logging.getLogger(__name__)

_WARNED_TARGET_FALLBACK = False



def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def _unit_nd(v: np.ndarray) -> np.ndarray:
    """Row-wise unit vectors; zero rows become +Z (same as `_unit`)."""
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    zaxis = np.zeros_like(v)
    zaxis[..., 2] = 1.0
    return np.where(n > 1e-12, v / np.maximum(n, 1e-30), zaxis)


def _target_direction(h_min, h_max, v_min, v_max, edge_ray: EdgeRayMode) -> np.ndarray:
    if edge_ray == EdgeRayMode.MAX:
        h, v = np.deg2rad(h_max), np.deg2rad(v_max)
    elif edge_ray == EdgeRayMode.MIN:
        h, v = np.deg2rad(h_min), np.deg2rad(v_min)
    else:
        h = np.deg2rad(0.5 * (h_min + h_max))
        v = np.deg2rad(0.5 * (v_min + v_max))
    d = np.array([np.sin(h) * np.cos(v), np.sin(v), np.cos(h) * np.cos(v)])
    return _unit(d)


def _target_direction_from_angles(h_deg, v_deg) -> np.ndarray:
    h = np.deg2rad(np.asarray(h_deg, dtype=float))
    v = np.deg2rad(np.asarray(v_deg, dtype=float))
    d = np.stack(
        [np.sin(h) * np.cos(v), np.sin(v), np.cos(h) * np.cos(v)],
        axis=-1,
    )
    return _unit_nd(d)


def _required_normal(source, point, target) -> np.ndarray:
    N = _required_normals(source, np.asarray(point, dtype=float), np.asarray(target, dtype=float))
    return N if N.ndim == 1 else N.reshape(3)


def _required_normals(source, points, targets) -> np.ndarray:
    source = np.asarray(source, dtype=float).reshape(3)
    points = np.asarray(points, dtype=float)
    targets = np.asarray(targets, dtype=float)
    I = _unit_nd(points - source)
    R = _unit_nd(targets)
    N = R - I
    nrm = np.linalg.norm(N, axis=-1, keepdims=True)
    N = np.where(nrm < 1e-9, -I, N / np.maximum(nrm, 1e-30))
    toward = np.sum(N * (source - points), axis=-1, keepdims=True)
    return np.where(toward < 0.0, -N, N)


def _slopes_from_normals(N: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    nz = N[..., 2]
    safe = np.abs(nz) >= 1e-9
    dzx = np.zeros(N.shape[:-1], dtype=float)
    dzy = np.zeros(N.shape[:-1], dtype=float)
    dzx = np.where(safe, -N[..., 0] / np.where(safe, nz, 1.0), 0.0)
    dzy = np.where(safe, -N[..., 1] / np.where(safe, nz, 1.0), 0.0)
    return dzx, dzy


def _eval_target_grid(target_fn, su: int, sv: int) -> Tuple[np.ndarray, np.ndarray]:
    """target_fn(li, lj) does not depend on height — evaluate once per solve.

    target_fn 要么支持整网格数组输入（向量化路径），要么退回逐节点循环。
    形状校验保证错误形状的返回值不会被误用。
    """
    LI, LJ = np.meshgrid(np.arange(su), np.arange(sv))  # (sv, su)
    try:
        hs, vs = target_fn(LI, LJ)
        hs = np.asarray(hs, dtype=float)
        vs = np.asarray(vs, dtype=float)
        if hs.shape == (sv, su) and vs.shape == (sv, su):
            return hs, vs
    except (TypeError, ValueError, IndexError) as exc:
        # 降级必须可诊断：真实 bug 不应被静默吞掉（只告警一次防刷屏）
        global _WARNED_TARGET_FALLBACK
        if not _WARNED_TARGET_FALLBACK:
            logger.warning(
                "target_fn 不支持整网格数组输入，退回逐点循环: %s", exc
            )
            _WARNED_TARGET_FALLBACK = True
    hs = np.empty((sv, su), dtype=float)
    vs = np.empty((sv, su), dtype=float)
    for lj in range(sv):
        for li in range(su):
            hs[lj, li], vs[lj, li] = target_fn(li, lj)
    return hs, vs


def _slopes_on_surface_static(
    xx: np.ndarray,
    yy: np.ndarray,
    z: np.ndarray,
    source: np.ndarray,
    targets: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """坡度场计算；网格坐标与目标方向由调用方提升到迭代循环外
    （每次迭代只有 z 变化）。"""
    pts = np.stack((xx, yy, z), axis=-1)
    return _slopes_from_normals(_required_normals(source, pts, targets))


def _height_slopes(xs: np.ndarray, ys: np.ndarray, z: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Node-centered finite-difference slopes of a height block."""
    z = np.asarray(z, dtype=float)
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    sv, su = z.shape
    zx = np.zeros((sv, su), dtype=float)
    zy = np.zeros((sv, su), dtype=float)
    if su >= 2:
        zx[:, 0] = (z[:, 1] - z[:, 0]) / (xs[1] - xs[0])
        zx[:, -1] = (z[:, -1] - z[:, -2]) / (xs[-1] - xs[-2])
    if su >= 3:
        zx[:, 1:-1] = (z[:, 2:] - z[:, :-2]) / (xs[2:] - xs[:-2])
    if sv >= 2:
        zy[0, :] = (z[1, :] - z[0, :]) / (ys[1] - ys[0])
        zy[-1, :] = (z[-1, :] - z[-2, :]) / (ys[-1] - ys[-2])
    if sv >= 3:
        zy[1:-1, :] = (z[2:, :] - z[:-2, :]) / (ys[2:] - ys[:-2])[:, None]
    return zx, zy


def _node_half_widths(coords: np.ndarray) -> np.ndarray:
    coords = np.asarray(coords, dtype=float)
    n = coords.size
    half = np.ones(n, dtype=float)
    if n <= 1:
        return half
    half[0] = 0.5 * abs(coords[1] - coords[0])
    half[-1] = 0.5 * abs(coords[-1] - coords[-2])
    if n >= 3:
        half[1:-1] = 0.5 * np.abs(coords[2:] - coords[:-2])
    return np.maximum(half, 1e-12)


def _carrier_z(x, y, source, focal) -> float:
    sx, sy, sz = source
    rho2 = (x - sx) ** 2 + (y - sy) ** 2
    return (sz - focal) + rho2 / (4.0 * focal)
