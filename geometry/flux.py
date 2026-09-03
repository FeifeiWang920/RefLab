# SPDX-License-Identifier: MIT
"""光源与光通量模型：发射轴、入射通量权重、能量分数映射。"""

from __future__ import annotations

from typing import Optional, Tuple
import logging

import numpy as np

from models.reflector import MFReflector
from geometry import tuning
from geometry.mathutils import _carrier_z, _height_slopes, _node_half_widths, _unit, _unit_nd


logger = logging.getLogger(__name__)



def _source_emission_axis(reflector: MFReflector) -> np.ndarray:
    """
    Source emission axis.  Explicit `source.axis` wins; otherwise the axis
    points from the source to the carrier-surface centre of the aperture.
    """
    src = reflector.source
    if src.axis is not None:
        axis = np.asarray(src.axis, dtype=float).reshape(3)
        n = float(np.linalg.norm(axis))
        if n > 1e-12:
            return axis / n
    pos = np.asarray(src.position, dtype=float).reshape(3)
    grid = reflector.grid
    cx = float(grid.offset_x + 0.5 * grid.total_width)
    cy = float(grid.offset_y + 0.5 * grid.total_height)
    cz = float(_carrier_z(cx, cy, pos, grid.focal))
    delta = np.array([cx, cy, cz]) - pos
    n = float(np.linalg.norm(delta))
    if n < 1e-12:
        return np.array([0.0, 0.0, -1.0])
    return delta / n


def _incident_flux_weights(
    xs: np.ndarray,
    ys: np.ndarray,
    z: np.ndarray,
    source: np.ndarray,
    axis: Optional[np.ndarray] = None,
    pattern: str = "lambertian",
    lambert_n: float = 1.0,
) -> np.ndarray:
    """
    Incident flux at each height-field node.

    dΦ = I(θ_s) · cosθ_i / r² · dA

      r      source → surface distance
      θ_s    emission angle from the source axis
      θ_i    incidence angle on the reflector
      I(θ_s) 1                     if pattern == "isotropic"
             max(0, cos θ_s)^n     if pattern == "lambertian"
    """
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    z = np.asarray(z, dtype=float)
    source = np.asarray(source, dtype=float).reshape(3)
    xx, yy = np.meshgrid(xs, ys)
    pts = np.stack((xx, yy, z), axis=-1)
    emit = pts - source
    dist = np.linalg.norm(emit, axis=-1, keepdims=True)
    dist = np.maximum(dist, 1e-9)
    emit_hat = emit / dist
    if axis is None:
        centre = pts.reshape(-1, 3).mean(axis=0)
        axis_vec = centre - source
        an = float(np.linalg.norm(axis_vec))
        axis_vec = axis_vec / an if an > 1e-12 else np.array([0.0, 0.0, -1.0])
    else:
        axis_vec = _unit(np.asarray(axis, dtype=float).reshape(3))
    zx, zy = _height_slopes(xs, ys, z)
    nrm = np.stack((-zx, -zy, np.ones(z.shape, dtype=float)), axis=-1)
    nrm = _unit_nd(nrm)
    cos_i = np.maximum(np.sum(nrm * (-emit_hat), axis=-1), 0.0)
    cos_s = np.maximum(np.sum(emit_hat * axis_vec.reshape(1, 1, 3), axis=-1), 0.0)
    if str(pattern).lower() == "isotropic":
        intensity = np.ones_like(cos_s)
    else:
        intensity = np.power(cos_s, max(0.0, float(lambert_n)))
    dA = (
        _node_half_widths(ys)[:, None]
        * _node_half_widths(xs)[None, :]
        * np.sqrt(1.0 + zx * zx + zy * zy)
    )
    return intensity * cos_i / np.square(dist[..., 0]) * dA


def _cdf_from_weights(weights: np.ndarray) -> np.ndarray:
    """Monotone CDF at sample nodes from interval-integrated 1-D weights."""
    w = np.maximum(np.asarray(weights, dtype=float).ravel(), 0.0)
    n = w.size
    if n <= 1:
        return np.zeros(n, dtype=float)
    mid = 0.5 * (w[:-1] + w[1:])
    total = float(np.sum(mid))
    if total <= 1e-30:
        return np.linspace(0.0, 1.0, n)
    cdf = np.concatenate(([0.0], np.cumsum(mid)))
    return cdf / cdf[-1]


def _energy_fracs(
    xs: np.ndarray,
    ys: np.ndarray,
    z: np.ndarray,
    source: np.ndarray,
    axis: Optional[np.ndarray] = None,
    pattern: str = "lambertian",
    lambert_n: float = 1.0,
    gamma: float = 1.0,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Separable 1-D energy parameters (frac_u, frac_v) ∈ [0, 1].

    gamma is applied to the *flux*, then the CDF is taken:
      w' = w^γ,  frac = CDF(w').
    γ = 1 is étendue-correct.  γ > 1 over-weights the peak so the
    integrable projection has more angle span to give back.  Powering
    the CDF itself would skew left/right and is not used.
    """
    flux = _incident_flux_weights(
        xs, ys, z, source, axis=axis, pattern=pattern, lambert_n=lambert_n
    )
    g = float(np.clip(gamma, *tuning.GAMMA_CLIP))
    if abs(g - 1.0) > 1e-6:
        flux = np.power(np.maximum(flux, 0.0), g)
    col = flux.sum(axis=0)
    row = flux.sum(axis=1)
    # Separable dΩ ~ (dH/du)(dV/dv) collapses at corners (both CDFs
    # flat).  Floor the 1-D weights so edge/corner bins keep ~10% of
    # peak angle speed and do not pile into two hot corners.
    for arr in (col, row):
        peak = float(np.max(arr))
        if peak > 0.0:
            arr[:] = np.maximum(arr, 0.1 * peak)
    return _cdf_from_weights(col), _cdf_from_weights(row)


def _linear_fracs(su: int, sv: int) -> Tuple[np.ndarray, np.ndarray]:
    return (
        np.linspace(0.0, 1.0, max(su, 1)),
        np.linspace(0.0, 1.0, max(sv, 1)),
    )


def _flux_quantile_map(
    values: np.ndarray,
    weights: np.ndarray,
    v0: float,
    v1: float,
    target_min: float = 0.1,
) -> np.ndarray:
    """
    Histogram-equalize realized angles by flux.

    Sort samples by realized angle, form a flux CDF (weights floored at
    target_min × peak so empty bins cannot steal the map), and send
    each lumen to a uniform position in [v0, v1].
    """
    v = np.asarray(values, dtype=float).ravel()
    w = np.maximum(np.asarray(weights, dtype=float).ravel(), 0.0)
    out = v.copy()
    if v.size == 0:
        return out
    peak = float(np.max(w)) if w.size else 0.0
    if peak <= 1e-30:
        return out
    w = np.maximum(w, float(target_min) * peak)
    order = np.argsort(v, kind="mergesort")
    cdf = np.cumsum(w[order])
    total = float(cdf[-1])
    if total <= 1e-30:
        return out
    cdf = cdf / total
    des = float(v0) + (float(v1) - float(v0)) * cdf
    out[order] = des
    return out
