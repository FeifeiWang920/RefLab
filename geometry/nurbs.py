# SPDX-License-Identifier: MIT
"""
Pure-NumPy B-spline surface utilities with *global interpolation*.

Using sample points directly as control points makes the surface miss the
data and often look faceted / wavy (especially for degree ≥ 3).
We therefore solve the standard interpolation system so the surface
passes through every sample point → single-facet smoothness.
"""

from __future__ import annotations

from typing import Tuple
from models.enums import PatchFitMethod
import numpy as np

try:
    from numba import njit
    _HAS_NUMBA = True
except Exception:  # pragma: no cover
    _HAS_NUMBA = False

    def njit(*_args, **_kwargs):
        def _wrap(fn):
            return fn
        if _args and callable(_args[0]) and not _kwargs:
            return _args[0]
        return _wrap


def open_uniform_knots(n_ctrl: int, degree: int) -> np.ndarray:
    """Clamped open-uniform knot vector, length = n_ctrl + degree + 1."""
    n, p = n_ctrl, degree
    m = n + p + 1
    knots = np.zeros(m)
    for i in range(p + 1):
        knots[i] = 0.0
    n_internal = n - p - 1
    if n_internal > 0:
        for i in range(1, n_internal + 1):
            knots[p + i] = i / (n_internal + 1)
    for i in range(m - p - 1, m):
        knots[i] = 1.0
    return knots


def find_span(n_ctrl: int, degree: int, u: float, knots: np.ndarray) -> int:
    p = degree
    if u >= knots[n_ctrl]:
        return n_ctrl - 1
    if u <= knots[p]:
        return p
    low, high = p, n_ctrl
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid


def basis_funs(u: float, span: int, degree: int, knots: np.ndarray) -> np.ndarray:
    p = degree
    N = np.zeros(p + 1)
    left = np.zeros(p + 1)
    right = np.zeros(p + 1)
    N[0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            denom = right[r + 1] + left[j - r]
            temp = 0.0 if abs(denom) < 1e-14 else N[r] / denom
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N


def eval_surface(
    ctrl: np.ndarray,
    degree_u: int,
    degree_v: int,
    knots_u: np.ndarray,
    knots_v: np.ndarray,
    u: float,
    v: float,
) -> np.ndarray:
    ctrl = np.asarray(ctrl, dtype=float)
    knots_u = np.asarray(knots_u, dtype=float)
    knots_v = np.asarray(knots_v, dtype=float)
    if _HAS_NUMBA:
        return _eval_surface_nb(
            ctrl, int(degree_u), int(degree_v), knots_u, knots_v,
            float(u), float(v),
        )
    nv, nu, _ = ctrl.shape
    u = float(np.clip(u, 0.0, 1.0))
    v = float(np.clip(v, 0.0, 1.0))
    span_u = find_span(nu, degree_u, u, knots_u)
    span_v = find_span(nv, degree_v, v, knots_v)
    Nu = basis_funs(u, span_u, degree_u, knots_u)
    Nv = basis_funs(v, span_v, degree_v, knots_v)
    pt = np.zeros(3)
    for j in range(degree_v + 1):
        row = np.zeros(3)
        for i in range(degree_u + 1):
            row += Nu[i] * ctrl[span_v - degree_v + j, span_u - degree_u + i]
        pt += Nv[j] * row
    return pt


@njit(cache=True)
def _find_span_nb(n_ctrl: int, degree: int, u: float, knots: np.ndarray) -> int:
    p = degree
    if u >= knots[n_ctrl]:
        return n_ctrl - 1
    if u <= knots[p]:
        return p
    low = p
    high = n_ctrl
    mid = (low + high) // 2
    while u < knots[mid] or u >= knots[mid + 1]:
        if u < knots[mid]:
            high = mid
        else:
            low = mid
        mid = (low + high) // 2
    return mid


@njit(cache=True)
def _basis_funs_nb(u: float, span: int, degree: int, knots: np.ndarray) -> np.ndarray:
    p = degree
    N = np.zeros(p + 1)
    left = np.zeros(p + 1)
    right = np.zeros(p + 1)
    N[0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - knots[span + 1 - j]
        right[j] = knots[span + j] - u
        saved = 0.0
        for r in range(j):
            denom = right[r + 1] + left[j - r]
            temp = 0.0 if abs(denom) < 1e-14 else N[r] / denom
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N


@njit(cache=True)
def _eval_surface_nb(
    ctrl: np.ndarray,
    degree_u: int,
    degree_v: int,
    knots_u: np.ndarray,
    knots_v: np.ndarray,
    u: float,
    v: float,
) -> np.ndarray:
    nv, nu, _ = ctrl.shape
    if u < 0.0:
        u = 0.0
    elif u > 1.0:
        u = 1.0
    if v < 0.0:
        v = 0.0
    elif v > 1.0:
        v = 1.0
    span_u = _find_span_nb(nu, degree_u, u, knots_u)
    span_v = _find_span_nb(nv, degree_v, v, knots_v)
    Nu = _basis_funs_nb(u, span_u, degree_u, knots_u)
    Nv = _basis_funs_nb(v, span_v, degree_v, knots_v)
    pt = np.zeros(3)
    for j in range(degree_v + 1):
        row0 = 0.0
        row1 = 0.0
        row2 = 0.0
        for i in range(degree_u + 1):
            pole = ctrl[span_v - degree_v + j, span_u - degree_u + i]
            w = Nu[i]
            row0 += w * pole[0]
            row1 += w * pole[1]
            row2 += w * pole[2]
        pt[0] += Nv[j] * row0
        pt[1] += Nv[j] * row1
        pt[2] += Nv[j] * row2
    return pt


@njit(cache=True)
def _sample_surface_nb(
    ctrl: np.ndarray,
    degree_u: int,
    degree_v: int,
    knots_u: np.ndarray,
    knots_v: np.ndarray,
    nu_samples: int,
    nv_samples: int,
) -> np.ndarray:
    pts = np.empty((nv_samples * nu_samples, 3))
    k = 0
    for j in range(nv_samples):
        v = j / (nv_samples - 1) if nv_samples > 1 else 0.0
        for i in range(nu_samples):
            u = i / (nu_samples - 1) if nu_samples > 1 else 0.0
            pts[k] = _eval_surface_nb(ctrl, degree_u, degree_v, knots_u, knots_v, u, v)
            k += 1
    return pts


def sample_surface(
    ctrl: np.ndarray,
    degree_u: int,
    degree_v: int,
    knots_u: np.ndarray,
    knots_v: np.ndarray,
    nu_samples: int,
    nv_samples: int,
) -> np.ndarray:
    ctrl = np.asarray(ctrl, dtype=float)
    knots_u = np.asarray(knots_u, dtype=float)
    knots_v = np.asarray(knots_v, dtype=float)
    if _HAS_NUMBA:
        return _sample_surface_nb(
            ctrl, int(degree_u), int(degree_v), knots_u, knots_v,
            int(nu_samples), int(nv_samples),
        )
    pts = []
    for j in range(nv_samples):
        v = j / (nv_samples - 1) if nv_samples > 1 else 0.0
        for i in range(nu_samples):
            u = i / (nu_samples - 1) if nu_samples > 1 else 0.0
            pts.append(eval_surface(ctrl, degree_u, degree_v, knots_u, knots_v, u, v))
    return np.asarray(pts, dtype=float)


# ---------------------------------------------------------------------------
# Global interpolation (The NURBS Book, Piegl & Tiller)
# ---------------------------------------------------------------------------

def _chord_params(points_1d: np.ndarray) -> np.ndarray:
    """Chord-length parameters for a 1D sequence of points (n, 3)."""
    n = len(points_1d)
    if n == 1:
        return np.array([0.0])
    d = np.zeros(n)
    for i in range(1, n):
        d[i] = d[i - 1] + np.linalg.norm(points_1d[i] - points_1d[i - 1])
    if d[-1] < 1e-14:
        return np.linspace(0.0, 1.0, n)
    return d / d[-1]


def _avg_params_grid(points: np.ndarray, direction: str) -> np.ndarray:
    """
    Average chord-length parameters across rows (direction='u') or columns ('v').
    points: (nv, nu, 3)
    """
    nv, nu, _ = points.shape
    if direction == "u":
        acc = np.zeros(nu)
        for j in range(nv):
            acc += _chord_params(points[j, :, :])
        return acc / nv
    else:
        acc = np.zeros(nv)
        for i in range(nu):
            acc += _chord_params(points[:, i, :])
        return acc / nu


def _interpolating_knots(params: np.ndarray, degree: int) -> np.ndarray:
    """Averaging technique for interpolating knot vector (Piegl)."""
    n = len(params)  # number of points = number of controls
    p = degree
    m = n + p + 1
    knots = np.zeros(m)
    for i in range(p + 1):
        knots[i] = 0.0
        knots[m - 1 - i] = 1.0
    if n == p + 1:
        return knots
    for j in range(1, n - p):
        s = 0.0
        for i in range(j, j + p):
            s += params[i]
        knots[j + p] = s / p
    return knots


def _basis_matrix(params: np.ndarray, degree: int, knots: np.ndarray) -> np.ndarray:
    """Collocation matrix A[i,j] = N_j,p(params[i])."""
    n_ctrl = len(knots) - degree - 1
    A = np.zeros((len(params), n_ctrl))
    for i, raw_u in enumerate(params):
        u = float(np.clip(raw_u, 0.0, 1.0))
        if i == 0:
            u = 0.0
        elif i == len(params) - 1:
            u = 1.0
        span = find_span(n_ctrl, degree, u, knots)
        values = basis_funs(u, span, degree, knots)
        for k, value in enumerate(values):
            col = span - degree + k
            if 0 <= col < n_ctrl:
                A[i, col] = value
    return A


def _interpolate_curve(points_1d: np.ndarray, degree: int, params: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """Interpolate a 1D chain of points → control points (n, 3)."""
    A = _basis_matrix(params, degree, knots)
    # Solve A * ctrl = points for each xyz
    try:
        ctrl = np.linalg.solve(A, points_1d)
    except np.linalg.LinAlgError:
        ctrl = np.linalg.lstsq(A, points_1d, rcond=None)[0]
    return ctrl


def _approximate_nurbs_from_grid(
    points: np.ndarray,
    degree_u: int,
    degree_v: int,
    keep_size: bool,
) -> Tuple[np.ndarray, int, int, np.ndarray, np.ndarray]:
    """Least-squares B-spline approximation of a regular point grid."""
    nv, nu, _ = points.shape
    du = max(1, min(int(degree_u), nu - 1))
    dv = max(1, min(int(degree_v), nv - 1))

    def target_count(n: int, degree: int) -> int:
        """Fewer controls than samples → smoother curvature (LS approximation)."""
        if n <= degree + 1:
            return n
        # Aim for roughly degree+2 .. n/2 controls
        return max(degree + 1, min(n - 1, max(degree + 2, (n + 2) // 3)))

    ncu, ncv = target_count(nu, du), target_count(nv, dv)
    if ncu >= nu and ncv >= nv:
        return make_nurbs_from_grid(points, du, dv)

    ku = open_uniform_knots(ncu, du)
    kv = open_uniform_knots(ncv, dv)
    pu = np.linspace(0.0, 1.0, nu)
    pv = np.linspace(0.0, 1.0, nv)
    Au = _basis_matrix(pu, du, ku)
    Av = _basis_matrix(pv, dv, kv)

    # Approximate rows in U, then columns in V.
    intermediate = np.asarray(
        [np.linalg.lstsq(Au, points[j], rcond=None)[0] for j in range(nv)]
    )
    ctrl = np.asarray(
        [np.linalg.lstsq(Av, intermediate[:, i], rcond=None)[0] for i in range(ncu)]
    ).transpose(1, 0, 2)

    if keep_size:
        # The optical surface is a height graph over the base grid. Keeping all
        # control points inside its XY bounding rectangle also keeps the B-spline
        # patch inside that rectangle (convex hull property).
        low = points[:, :, :2].min(axis=(0, 1))
        high = points[:, :, :2].max(axis=(0, 1))
        ctrl[:, :, :2] = np.clip(ctrl[:, :, :2], low, high)

    return ctrl, du, dv, ku, kv


def make_nurbs_from_grid(
    points: np.ndarray,
    degree_u: int,
    degree_v: int,
    fit_method: PatchFitMethod = PatchFitMethod.EXACT,
    uniform_parameters: bool = False,
) -> Tuple[np.ndarray, int, int, np.ndarray, np.ndarray]:
    """
    Global interpolation or approximation of a regular point grid.

    points : (nv, nu, 3) sample points
    Returns (ctrl, deg_u, deg_v, knots_u, knots_v)
    """
    nv, nu, _ = points.shape
    du = max(1, min(int(degree_u), nu - 1))
    dv = max(1, min(int(degree_v), nv - 1))

    # Degenerate small grids: fall back to using points as controls
    if nu < du + 1 or nv < dv + 1 or nu < 2 or nv < 2:
        du = max(1, min(du, nu - 1))
        dv = max(1, min(dv, nv - 1))
        ku = open_uniform_knots(nu, du)
        kv = open_uniform_knots(nv, dv)
        return points.copy(), du, dv, ku, kv

    if fit_method in (
        PatchFitMethod.APPROXIMATE,
        PatchFitMethod.APPROXIMATE_KEEP_SIZE,
    ):
        return _approximate_nurbs_from_grid(
            points,
            du,
            dv,
            keep_size=fit_method == PatchFitMethod.APPROXIMATE_KEEP_SIZE,
        )

    if uniform_parameters:
        params_u = np.linspace(0.0, 1.0, nu)
        params_v = np.linspace(0.0, 1.0, nv)
    else:
        # Parameterisation (chord-length averaged)
        params_u = _avg_params_grid(points, "u")
        params_v = _avg_params_grid(points, "v")
        params_u[0], params_u[-1] = 0.0, 1.0
        params_v[0], params_v[-1] = 0.0, 1.0

    knots_u = _interpolating_knots(params_u, du)
    knots_v = _interpolating_knots(params_v, dv)

    # --- Surface interpolation: interpolate rows in U, then columns in V ---
    # Step 1: for each fixed v-row, interpolate in U → intermediate R (nv, nu, 3)
    R = np.zeros((nv, nu, 3))
    for j in range(nv):
        R[j] = _interpolate_curve(points[j], du, params_u, knots_u)

    # Step 2: for each fixed u-column of R, interpolate in V → controls
    ctrl = np.zeros((nv, nu, 3))
    for i in range(nu):
        ctrl[:, i, :] = _interpolate_curve(R[:, i, :], dv, params_v, knots_v)

    return ctrl, du, dv, knots_u, knots_v



