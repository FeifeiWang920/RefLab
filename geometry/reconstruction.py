# SPDX-License-Identifier: MIT
"""坡度场 → 高度场：最小二乘预分解重建器与路径积分。"""

from __future__ import annotations

from typing import Dict, Optional, Sequence
import logging

import numpy as np

from models.enums import (
    SolveMethod,
)
from geometry import tuning


logger = logging.getLogger(__name__)



def _integrate_relative(
    dzx: np.ndarray,
    dzy: np.ndarray,
    x_coords: Sequence[float],
    y_coords: Sequence[float],
    z_carrier: np.ndarray,
    order: SolveMethod,
    start_i: int = -1,
    start_j: int = -1,
) -> np.ndarray:
    nv, nu = dzx.shape
    z_rel = np.zeros((nv, nu), dtype=float)
    ci = max(0, min(nu - 1, start_i if start_i >= 0 else nu // 2))
    cj = max(0, min(nv - 1, start_j if start_j >= 0 else nv // 2))

    if order == SolveMethod.V_FIRST:
        for j in range(cj + 1, nv):
            dy = y_coords[j] - y_coords[j - 1]
            z_rel[j, ci] = z_rel[j - 1, ci] + 0.5 * (dzy[j, ci] + dzy[j - 1, ci]) * dy
        for j in range(cj - 1, -1, -1):
            dy = y_coords[j] - y_coords[j + 1]
            z_rel[j, ci] = z_rel[j + 1, ci] + 0.5 * (dzy[j, ci] + dzy[j + 1, ci]) * dy
        for j in range(nv):
            for i in range(ci + 1, nu):
                dx = x_coords[i] - x_coords[i - 1]
                z_rel[j, i] = z_rel[j, i - 1] + 0.5 * (dzx[j, i] + dzx[j, i - 1]) * dx
            for i in range(ci - 1, -1, -1):
                dx = x_coords[i] - x_coords[i + 1]
                z_rel[j, i] = z_rel[j, i + 1] + 0.5 * (dzx[j, i] + dzx[j, i + 1]) * dx
    else:
        for i in range(ci + 1, nu):
            dx = x_coords[i] - x_coords[i - 1]
            z_rel[cj, i] = z_rel[cj, i - 1] + 0.5 * (dzx[cj, i] + dzx[cj, i - 1]) * dx
        for i in range(ci - 1, -1, -1):
            dx = x_coords[i] - x_coords[i + 1]
            z_rel[cj, i] = z_rel[cj, i + 1] + 0.5 * (dzx[cj, i] + dzx[cj, i + 1]) * dx
        for i in range(nu):
            for j in range(cj + 1, nv):
                dy = y_coords[j] - y_coords[j - 1]
                z_rel[j, i] = z_rel[j - 1, i] + 0.5 * (dzy[j, i] + dzy[j - 1, i]) * dy
            for j in range(cj - 1, -1, -1):
                dy = y_coords[j] - y_coords[j + 1]
                z_rel[j, i] = z_rel[j + 1, i] + 0.5 * (dzy[j, i] + dzy[j + 1, i]) * dy
    return z_carrier + z_rel


def _reconstruct_height_by_paths(
    dzx: np.ndarray,
    dzy: np.ndarray,
    x_coords: Sequence[float],
    y_coords: Sequence[float],
    z_seed: float,
    seed_i: int,
    seed_j: int,
    order: SolveMethod,
) -> np.ndarray:
    """
    LucidShape-style relative (here: absolute) slope integration.

    Least-squares projection of a non-conservative reflection-law slope
    field damps |∇z| and packs rays toward the mean angle (hot centre).
    Path integration along the FunGeo solve order keeps the designed
    H(u)/V(v) sweep, which is what FFD uses to fill the rectangle.
    """
    base = np.full(np.asarray(dzx).shape, float(z_seed))
    return _integrate_relative(
        dzx, dzy, x_coords, y_coords, base, order,
        start_i=seed_i, start_j=seed_j,
    )


class _SlopeHeightSolver:
    """Pre-factorised least-squares height reconstruction for one facet grid.

    The design matrix depends only on the grid geometry (xs, ys,
    edge_weight) — never on the slopes — so the linear map from slope
    fields to heights is factorised once and every subsequent solve
    reduces to building the right-hand side plus one matvec.  Dirichlet
    constraints are either a single seed node (`for_seed`) or fixed
    border rows/columns (`for_borders`; uniform weights, matching the
    historical border solver).  Degenerate grids (rank-deficient normal
    equations) fall back to the SVD lstsq path.
    """

    def __init__(
        self,
        xs: np.ndarray,
        ys: np.ndarray,
        edge_weight: Optional[float],
        fixed_mask: np.ndarray,
        fixed_vals: np.ndarray,
    ) -> None:
        xs = np.asarray(xs, dtype=float)
        ys = np.asarray(ys, dtype=float)
        nv = int(ys.size)
        nu = int(xs.size)
        N = nv * nu
        self.nv, self.nu, self.N = nv, nu, N
        self._fixed = fixed_mask
        self._fixed_vals = fixed_vals

        A, self._sel, self._sw_sel = self._build_design_matrix(xs, ys, edge_weight)

        free = ~fixed_mask
        self._all_fixed = not free.any()
        self._K: Optional[np.ndarray] = None
        self._Am: Optional[np.ndarray] = None
        self._fixed_part: Optional[np.ndarray] = None
        if self._all_fixed:
            return
        Am = A[:, free]
        self._fixed_part = A[:, fixed_mask] @ fixed_vals[fixed_mask]
        # 预分解：K = (AmᵀAm)⁻¹ Amᵀ，每次 solve 只需一次 matvec。
        # 数值上与 SVD lstsq 同解（差 ~κ·eps）；正规方程奇异时退回 lstsq。
        try:
            G = Am.T @ Am
            self._K = np.linalg.inv(G) @ Am.T
        except np.linalg.LinAlgError:
            self._Am = Am

    @staticmethod
    def _build_design_matrix(xs, ys, edge_weight):
        n_eq = ys.size * (xs.size - 1) + (ys.size - 1) * xs.size
        N = ys.size * xs.size
        A = np.zeros((n_eq, N))
        w = np.ones(n_eq)
        # Interval slope = average of the two node slopes (trapezoid rule).
        # Using only the left/bottom node systematically under-steers the
        # surface and packs rays toward the mean angle (hot centre + soft edge).
        # With edge_weight set, boundary intervals get that higher weight so the
        # rectangular far-field outline is honoured even when the slope field is
        # not conservative.  edge_weight=None keeps uniform weights (border mode).
        edge_w = None if edge_weight is None else float(edge_weight)
        dx = np.diff(xs)
        dy = np.diff(ys)
        # 行序与历史实现一致：先全部 x 行（j 外层、i 内层，跳过 dx<=0），后 y 行。
        x_ok = dx > 0.0
        y_ok = dy > 0.0
        k = 0
        for j in range(ys.size):
            wrow = 1.0 if edge_w is None else (edge_w if (j == 0 or j == ys.size - 1) else 1.0)
            for i in range(xs.size - 1):
                if not x_ok[i]:
                    continue
                A[k, j * xs.size + i + 1] = 1.0 / dx[i]
                A[k, j * xs.size + i] = -1.0 / dx[i]
                if edge_w is not None:
                    w[k] = wrow * (edge_w if (i == 0 or i == xs.size - 2) else 1.0)
                k += 1
        for j in range(ys.size - 1):
            for i in range(xs.size):
                if not y_ok[j]:
                    continue
                A[k, (j + 1) * xs.size + i] = 1.0 / dy[j]
                A[k, j * xs.size + i] = -1.0 / dy[j]
                if edge_w is not None:
                    wcol = edge_w if (i == 0 or i == xs.size - 1) else 1.0
                    w[k] = wcol * (edge_w if (j == 0 or j == ys.size - 2) else 1.0)
                k += 1
        A = A[:k]
        w = w[:k]
        sw = np.sqrt(w)
        A = A * sw[:, None]
        # 行选择索引：把 (dzx, dzy) 展平后的 b 直接映射到保留的方程行。
        # True 的个数恰为 k（保留的方程行数），与 A 的行序一致。
        sel = np.concatenate((
            np.tile(x_ok, ys.size),
            np.repeat(y_ok, xs.size),
        ))
        return A, sel, sw

    @classmethod
    def for_seed(
        cls,
        x_coords: Sequence[float],
        y_coords: Sequence[float],
        z_seed: float,
        seed_i: int,
        seed_j: int,
        edge_weight: float = tuning.EDGE_WEIGHT,
    ) -> "_SlopeHeightSolver":
        """单一种子点高度固定的自由重建（默认求解路径）。"""
        xs = np.asarray(x_coords, dtype=float)
        ys = np.asarray(y_coords, dtype=float)
        fixed = np.zeros(ys.size * xs.size, dtype=bool)
        fixed[seed_j * xs.size + seed_i] = True
        vals = np.zeros_like(fixed, dtype=float)
        vals[fixed] = float(z_seed)
        return cls(xs, ys, edge_weight, fixed, vals)

    @classmethod
    def for_borders(
        cls,
        x_coords: Sequence[float],
        y_coords: Sequence[float],
        z_borders: Dict[str, Optional[np.ndarray]],
    ) -> "_SlopeHeightSolver":
        """边界行/列按给定曲线固定的重建（邻边基线路径，权重均匀）。"""
        xs = np.asarray(x_coords, dtype=float)
        ys = np.asarray(y_coords, dtype=float)
        nv, nu = ys.size, xs.size
        fixed = np.zeros(nv * nu, dtype=bool)
        vals = np.zeros(nv * nu, dtype=float)
        for side, arr in z_borders.items():
            if arr is None:
                continue
            arr = np.asarray(arr, dtype=float)
            if side in ("left", "right"):
                idx = 0 if side == "left" else nu - 1
                fixed[idx::nu] = True
                vals[idx::nu] = arr
            else:
                idx = 0 if side == "bottom" else nv - 1
                fixed[idx * nu:idx * nu + nu] = True
                vals[idx * nu:idx * nu + nu] = arr
        return cls(xs, ys, None, fixed, vals)

    def solve(self, dzx: np.ndarray, dzy: np.ndarray) -> np.ndarray:
        nv, nu, N = self.nv, self.nu, self.N
        if self._all_fixed:
            return self._fixed_vals.reshape(nv, nu)
        bx = 0.5 * (dzx[:, :-1] + dzx[:, 1:])
        by = 0.5 * (dzy[:-1, :] + dzy[1:, :])
        b_all = np.concatenate((bx.ravel(), by.ravel()))
        bm = self._sw_sel * b_all[self._sel] - self._fixed_part
        if self._K is not None:
            sol = self._K @ bm
        else:
            sol, *_ = np.linalg.lstsq(self._Am, bm, rcond=None)
        z = np.zeros(N)
        z[self._fixed] = self._fixed_vals[self._fixed]
        z[~self._fixed] = sol
        return z.reshape(nv, nu)
