"""
MacroFocal geometry engine (v0.8 – per-facet solver + Gap Surface).

1. Carrier paraboloid + relative slope integration, solved facet by facet.
2. Each facet is fitted with a real B-spline (NURBS) surface.
3. GapSurfaceMode.SURFACE generates ruled patches between adjacent facets.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np

from models.reflector import MFReflector
from models.facet import Facet
from models.enums import (
    EdgeRayMode,
    GapSurfaceMode,
    GapType,
    PatchContinuity,
    PatchFitMethod,
    SolveMethod,
)
from geometry.nurbs import make_nurbs_from_grid


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


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


def _target_direction_from_angles(h_deg: float, v_deg: float) -> np.ndarray:
    h = np.deg2rad(h_deg)
    v = np.deg2rad(v_deg)
    d = np.array([np.sin(h) * np.cos(v), np.sin(v), np.cos(h) * np.cos(v)])
    return _unit(d)


def _required_normal(source, point, target) -> np.ndarray:
    I = _unit(point - source)
    R = _unit(target)
    N = R - I
    nrm = np.linalg.norm(N)
    N = -I if nrm < 1e-9 else N / nrm
    if np.dot(N, source - point) < 0:
        N = -N
    return N


def _slopes_from_normal(N: np.ndarray) -> Tuple[float, float]:
    if abs(N[2]) < 1e-9:
        return 0.0, 0.0
    return -float(N[0] / N[2]), -float(N[1] / N[2])


def _carrier_z(x, y, source, focal) -> float:
    sx, sy, sz = source
    rho2 = (x - sx) ** 2 + (y - sy) ** 2
    return (sz - focal) + rho2 / (4.0 * focal)


def _carrier_normal(x, y, source, focal) -> np.ndarray:
    sx, sy, _ = source
    zx = (x - sx) / (2.0 * focal)
    zy = (y - sy) / (2.0 * focal)
    return _unit(np.array([-zx, -zy, 1.0]))


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

def _solve_order(n_u: int, n_v: int, start: Tuple[int, int], order: SolveMethod) -> Tuple[
    List[Tuple[int, int]], Dict[Tuple[int, int], Tuple[int, int]]
]:
    """
    BFS solve order plus the BFS parent of every facet.

    The parent is guaranteed to be solved before its child (BFS property), so
    each facet can always be matched against an already-computed neighbour.
    This removes the old behaviour where facets whose candidate neighbours had
    not been solved yet silently snapped back to the carrier, which produced an
    independent "anchor patchwork" with mismatched facet borders.
    """
    neighbors = (
        [(0, -1), (0, 1), (-1, 0), (1, 0)]
        if order == SolveMethod.V_FIRST
        else [(-1, 0), (1, 0), (0, -1), (0, 1)]
    )
    result: List[Tuple[int, int]] = []
    parents: Dict[Tuple[int, int], Tuple[int, int]] = {}
    visited = {start}
    queue = [start]
    while queue:
        iu, iv = queue.pop(0)
        result.append((iu, iv))
        for du, dv in neighbors:
            nxt = (iu + du, iv + dv)
            if 0 <= nxt[0] < n_u and 0 <= nxt[1] < n_v and nxt not in visited:
                visited.add(nxt)
                parents[nxt] = (iu, iv)
                queue.append(nxt)
    return result, parents


def _start_facet(reflector: MFReflector) -> Tuple[int, int, float, float]:
    grid = reflector.grid
    x_edges = grid.node_x_coords()
    y_edges = grid.node_y_coords()
    iu, iv = 0, 0
    local_u = reflector.calculation_start_u
    local_v = reflector.calculation_start_v
    if local_u is None:
        local_u = reflector.reference_position_u
    if local_v is None:
        local_v = reflector.reference_position_v

    if grid.use_start_point:
        x, y = grid.start_point
        if not (
            x_edges[0] - 1e-9 <= x <= x_edges[-1] + 1e-9
            and y_edges[0] - 1e-9 <= y <= y_edges[-1] + 1e-9
        ):
            raise ValueError("grid.start_point must be inside the grid")
        iu = int(np.searchsorted(x_edges, x, side="right") - 1)
        iv = int(np.searchsorted(y_edges, y, side="right") - 1)
        iu = min(max(iu, 0), grid.n_u - 1)
        iv = min(max(iv, 0), grid.n_v - 1)
        local_u = (x - x_edges[iu]) / max(grid.width_deltas[iu], 1e-12)
        local_v = (y - y_edges[iv]) / max(grid.height_deltas[iv], 1e-12)
    return iu, iv, float(np.clip(local_u, 0.0, 1.0)), float(np.clip(local_v, 0.0, 1.0))


def _inherit_edge(
    raw: np.ndarray,
    neighbor: np.ndarray,
    axis: str,
    ref: float,
    use_curve: bool,
) -> np.ndarray:
    if axis == "v":
        delta = neighbor[-1, :] - raw[0, :]
        if not use_curve:
            index = int(round(np.clip(ref, 0.0, 1.0) * (delta.shape[0] - 1)))
            delta[:] = delta[index]
        weights = np.linspace(0.0, 1.0, raw.shape[0])[:, None]
        return raw + delta[None, :] * weights
    delta = neighbor[:, -1] - raw[:, 0]
    if not use_curve:
        index = int(round(np.clip(ref, 0.0, 1.0) * (delta.shape[0] - 1)))
        delta[:] = delta[index]
    weights = np.linspace(0.0, 1.0, raw.shape[1])[None, :]
    return raw + delta[:, None] * weights



def _fair_height_block(z: np.ndarray, iterations: int = 12, strength: float = 0.4) -> np.ndarray:
    """Laplacian fairing; boundaries fixed."""
    if z.shape[0] < 3 or z.shape[1] < 3 or iterations <= 0:
        return z
    out = z.astype(float, copy=True)
    for _ in range(iterations):
        lap = (
            out[:-2, 1:-1] + out[2:, 1:-1] + out[1:-1, :-2] + out[1:-1, 2:]
            - 4.0 * out[1:-1, 1:-1]
        )
        out[1:-1, 1:-1] += strength * 0.25 * lap
    return out


def _reconstruct_height_from_slopes(
    dzx: np.ndarray,
    dzy: np.ndarray,
    x_coords: Sequence[float],
    y_coords: Sequence[float],
    z_seed: float,
    seed_i: int,
    seed_j: int,
    iterations: int = 40,
) -> np.ndarray:
    """
    Build the *optimal* height field whose gradient matches (dzx, dzy) in LS sense.

    Discrete slope fields from the reflection law are not exactly conservative
    (path-dependent), so we solve the least-squares gradient-matching problem
    directly (dense normal equations; per-facet grids are tiny):
        min_z  sum_j,i ( (z[j,i+1]-z[j,i])/dx - dzx[j,i] )^2
             + sum_j,i ( (z[j+1,i]-z[j,i])/dy - dzy[j,i] )^2
    subject to z[seed] = z_seed.  This yields the smoothest surface that best
    honours the desired slopes and replaces the old ad-hoc Southwell sweeps.
    """
    nv, nu = dzx.shape
    N = nv * nu
    xs = np.asarray(x_coords, dtype=float)
    ys = np.asarray(y_coords, dtype=float)

    n_eq = nv * (nu - 1) + (nv - 1) * nu
    A = np.zeros((n_eq, N))
    b = np.zeros(n_eq)
    k = 0
    for j in range(nv):
        for i in range(nu - 1):
            dx = xs[i + 1] - xs[i]
            if dx <= 0.0:
                continue
            A[k, j * nu + i + 1] = 1.0 / dx
            A[k, j * nu + i] = -1.0 / dx
            b[k] = dzx[j, i]
            k += 1
    for j in range(nv - 1):
        for i in range(nu):
            dy = ys[j + 1] - ys[j]
            if dy <= 0.0:
                continue
            A[k, (j + 1) * nu + i] = 1.0 / dy
            A[k, j * nu + i] = -1.0 / dy
            b[k] = dzy[j, i]
            k += 1
    A = A[:k]
    b = b[:k]

    # Fix the seed height (Dirichlet constraint): solve for the other nodes.
    mask = np.ones(N, dtype=bool)
    mask[seed_j * nu + seed_i] = False
    Am = A[:, mask]
    bm = b - (A[:, ~mask] * z_seed).ravel()
    sol, *_ = np.linalg.lstsq(Am, bm, rcond=None)
    z = np.zeros(N)
    z[~mask] = z_seed
    z[mask] = sol
    return z.reshape(nv, nu)


def _build_height_field(reflector: MFReflector):
    """
    LucidShape-style per-facet solve with globally consistent borders.

    From FunGeo / MF dialog (Set F.Start, Other Settings):
      - patch calculation sequence: vertical-first or horizontal-first
        (our SolveMethod) defines the order facets are computed.
      - Each facet is integrated independently for its own spreads.
      - calculation start (U,V): seed of the relative integration inside
        the facet; default (0,0) or automatic = reference position.
      - reference position (U,V) along the shared edge: when
        use_base_curve_from_neighbor is off, only the point at the reference
        position of the already-computed parent facet is matched (rigid Z
        offset, preserving the optical shape of the new facet).
      - use_base_curve_from_neighbor (default): the new facet connects to its
        neighbour along the *full* shared-edge curve.  We implement this as a
        two-pass scheme:
          1. every facet is solved absolutely (carrier-anchored);
          2. the shared borders are averaged between the adjacent facets and
             each facet is re-solved with those border curves as Dirichlet
             boundary conditions.
        This makes the whole facet family watertight (C0) at every shared
        border — no banks, wrinkles or twisted step surfaces between facets.
      - Z steps: added per facet index after the border match.

    Facets are intentionally *not* one C1 surface — gaps separate them.
    """
    grid = reflector.grid
    spreads = reflector.spreads
    source = reflector.source.position.copy()
    focal = grid.focal
    order = reflector.solve
    n_u, n_v = grid.n_u, grid.n_v
    su = max(2, reflector.mesh_u)
    sv = max(2, reflector.mesh_v)
    nu = n_u * (su - 1) + 1
    nv = n_v * (sv - 1) + 1

    x_edges = grid.node_x_coords()
    y_edges = grid.node_y_coords()
    x_list: List[float] = []
    for iu in range(n_u):
        for k in range(su - 1):
            t = k / (su - 1)
            x_list.append((1.0 - t) * x_edges[iu] + t * x_edges[iu + 1])
    x_list.append(x_edges[-1])
    x_coords = np.asarray(x_list, dtype=float)

    y_list: List[float] = []
    for iv in range(n_v):
        for k in range(sv - 1):
            t = k / (sv - 1)
            y_list.append((1.0 - t) * y_edges[iv] + t * y_edges[iv + 1])
    y_list.append(y_edges[-1])
    y_coords = np.asarray(y_list, dtype=float)

    z = np.zeros((nv, nu), dtype=float)

    z_step_u = reflector.z_step_u + reflector.gaps.effective_step_z()
    z_step_v = reflector.z_step_v + reflector.gaps.effective_step_z()

    start_iu, start_iv, start_local_u, start_local_v = _start_facet(reflector)
    solve_order, parents = _solve_order(n_u, n_v, (start_iu, start_iv), order)

    # ------------------------------------------------------------------
    # Pass 1: independent optical solve of every facet (absolute heights,
    # anchored to the carrier at the facet's calculation-start point).
    # ------------------------------------------------------------------
    abs_blocks: Dict[Tuple[int, int], np.ndarray] = {}
    facet_seeds: Dict[Tuple[int, int], Tuple[int, int, float]] = {}
    facet_grids: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]] = {}
    for iu, iv in solve_order:
        i0 = iu * (su - 1)
        j0 = iv * (sv - 1)
        xs = x_coords[i0:i0 + su]
        ys = y_coords[j0:j0 + sv]
        facet_grids[(iu, iv)] = (xs, ys)

        carrier = np.asarray(
            [[_carrier_z(xs[i], ys[j], source, focal) for i in range(su)]
             for j in range(sv)],
            dtype=float,
        )

        # --- calculation start (F.Start / auto = reference) ---
        is_seed_facet = (iu, iv) == (start_iu, start_iv)
        if is_seed_facet:
            seed_u = start_local_u
            seed_v = start_local_v
        else:
            # automatic start point uses reference position (LS doc)
            if reflector.calculation_start_u is not None:
                seed_u = float(reflector.calculation_start_u)
            else:
                seed_u = float(reflector.reference_position_u)
            if reflector.calculation_start_v is not None:
                seed_v = float(reflector.calculation_start_v)
            else:
                seed_v = float(reflector.reference_position_v)
        seed_i = int(np.clip(round(seed_u * (su - 1)), 0, su - 1))
        seed_j = int(np.clip(round(seed_v * (sv - 1)), 0, sv - 1))
        # Height reference = carrier + grid.start_z at the calculation-start
        # point (base plane).
        z_ref = float(carrier[seed_j, seed_i]) + grid.start_z + grid.offset_z
        facet_seeds[(iu, iv)] = (seed_i, seed_j, z_ref)

        # Desired *absolute* slopes from the reflection law, then reconstruct a
        # height field by least-squares gradient matching so the facet's
        # reflection angles follow the spread.
        def raw_target(li: int, lj: int, iu=iu, iv=iv) -> Tuple[float, float]:
            lu = li / max(su - 1, 1)
            lv = lj / max(sv - 1, 1)
            return spreads.target_angles_on_facet(iu, iv, lu, lv)

        abs_blocks[(iu, iv)] = _solve_facet_optical(
            reflector, xs, ys, source, raw_target, su, sv,
            z_seed=z_ref, seed_i=seed_i, seed_j=seed_j, z_init=carrier,
        )

    # ------------------------------------------------------------------
    # Pass 2: spread calibration (one affine round).
    # The least-squares surface reproduces the requested spread only to the
    # discretisation accuracy (~1-3° at facet borders).  Measure the affine
    # deviation  realised ≈ a + b·target  on each facet and re-solve with the
    # corrected target mapping, so the realised far-field extent of every facet
    # matches the requested angle range (rectangular spot).
    # ------------------------------------------------------------------
    calib = _calibrate_facets(abs_blocks, facet_grids, source, spreads, su, sv)
    cal_blocks: Dict[Tuple[int, int], np.ndarray] = {}
    for iu, iv in solve_order:
        xs, ys = facet_grids[(iu, iv)]
        seed_i, seed_j, z_ref = facet_seeds[(iu, iv)]
        ah, bh, av, bv = calib[(iu, iv)]

        def cal_target(li: int, lj: int, ah=ah, bh=bh, av=av, bv=bv,
                       iu=iu, iv=iv) -> Tuple[float, float]:
            h_deg, v_deg = spreads.target_angles_on_facet(
                iu, iv, li / max(su - 1, 1), lj / max(sv - 1, 1)
            )
            return (h_deg - ah) / bh, (v_deg - av) / bv

        cal_blocks[(iu, iv)] = _solve_facet_optical(
            reflector, xs, ys, source, cal_target, su, sv,
            z_seed=z_ref, seed_i=seed_i, seed_j=seed_j,
            z_init=abs_blocks[(iu, iv)],
        )

    # ------------------------------------------------------------------
    # Pass 3: neighbour influence.
    # ------------------------------------------------------------------
    blocks: Dict[Tuple[int, int], np.ndarray] = {}
    if reflector.use_base_curve_from_neighbor:
        # Optional full shared-edge curve matching: average the facing edge
        # curves of adjacent facets, then re-solve each facet with those
        # curves as Dirichlet boundary conditions -> C0 borders.  NOTE: this
        # bends the facet optics near every shared border (the two designs
        # demand opposite edge slopes), so the far-field range is only
        # approximate; the reference-point mode below is the optical default.
        border_curves = _shared_border_curves(cal_blocks, su, sv)
        for iu, iv in solve_order:
            i0 = iu * (su - 1)
            j0 = iv * (sv - 1)
            xs = x_coords[i0:i0 + su]
            ys = y_coords[j0:j0 + sv]
            zb = {
                "left": border_curves[("u", iu, iv)] if iu > 0 else None,
                "right": border_curves[("u", iu + 1, iv)] if iu < n_u - 1 else None,
                "bottom": border_curves[("v", iu, iv)] if iv > 0 else None,
                "top": border_curves[("v", iu, iv + 1)] if iv < n_v - 1 else None,
            }
            ah, bh, av, bv = calib[(iu, iv)]

            def cal_target2(li: int, lj: int, ah=ah, bh=bh, av=av, bv=bv,
                            iu=iu, iv=iv) -> Tuple[float, float]:
                h_deg, v_deg = spreads.target_angles_on_facet(
                    iu, iv, li / max(su - 1, 1), lj / max(sv - 1, 1)
                )
                return (h_deg - ah) / bh, (v_deg - av) / bv

            blk = _solve_facet_with_borders(
                reflector, cal_blocks[(iu, iv)], spread_target=cal_target2,
                xs=xs, ys=ys, source=source, zb=zb,
                su=su, sv=sv, z_step=float(iu * z_step_u + iv * z_step_v),
            )
            blocks[(iu, iv)] = blk
            z[j0:j0 + sv, i0:i0 + su] = blk
    else:
        # Reference-position rigid offset against the BFS parent (the parent
        # is always already solved, so the old "snap to carrier" patchwork is
        # gone).  A Z step is added per facet index afterwards.
        solved: Dict[Tuple[int, int], np.ndarray] = {}
        for iu, iv in solve_order:
            i0 = iu * (su - 1)
            j0 = iv * (sv - 1)
            xs = x_coords[i0:i0 + su]
            ys = y_coords[j0:j0 + sv]
            z_loc = cal_blocks[(iu, iv)].copy()
            parent = parents.get((iu, iv))
            if parent is not None:
                piu, piv = parent
                neigh = solved[(piu, piv)]
                if piu == iu - 1:
                    ref = float(np.clip(reflector.reference_position_v, 0.0, 1.0))
                    idx = int(round(ref * (sv - 1)))
                    z_loc += float(neigh[idx, -1] - z_loc[idx, 0])
                elif piu == iu + 1:
                    ref = float(np.clip(reflector.reference_position_v, 0.0, 1.0))
                    idx = int(round(ref * (sv - 1)))
                    z_loc += float(neigh[idx, 0] - z_loc[idx, -1])
                elif piv == iv - 1:
                    ref = float(np.clip(reflector.reference_position_u, 0.0, 1.0))
                    idx = int(round(ref * (su - 1)))
                    z_loc += float(neigh[-1, idx] - z_loc[0, idx])
                elif piv == iv + 1:
                    ref = float(np.clip(reflector.reference_position_u, 0.0, 1.0))
                    idx = int(round(ref * (su - 1)))
                    z_loc += float(neigh[0, idx] - z_loc[-1, idx])
            z_loc = z_loc + (iu * z_step_u + iv * z_step_v)
            solved[(iu, iv)] = z_loc.copy()
            blocks[(iu, iv)] = z_loc.copy()
            z[j0:j0 + sv, i0:i0 + su] = z_loc

    return x_coords, y_coords, z, su, sv, blocks


# ---------------------------------------------------------------------------
# Per-facet optical solve + spread calibration
# ---------------------------------------------------------------------------


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
    Fixed-point solve of one facet: at every node take the reflection-law
    normal for the spread target, integrate the slope field by least-squares
    gradient matching, and iterate until the surface stops moving.
    """
    max_iter = max(1, int(reflector.solver_iterations))
    tol = max(0.0, float(reflector.solver_tolerance))
    z_loc = np.asarray(z_init, dtype=float).copy()
    for _ in range(max_iter):
        dzx = np.zeros((sv, su))
        dzy = np.zeros((sv, su))
        for lj in range(sv):
            for li in range(su):
                pt = np.array([xs[li], ys[lj], z_loc[lj, li]])
                h_deg, v_deg = target_fn(li, lj)
                n_req = _required_normal(
                    source, pt, _target_direction_from_angles(h_deg, v_deg)
                )
                sx, sy = _slopes_from_normal(n_req)
                dzx[lj, li] = sx
                dzy[lj, li] = sy
        z_new = _reconstruct_height_from_slopes(
            dzx, dzy, xs, ys,
            z_seed=z_seed,
            seed_i=seed_i, seed_j=seed_j,
            iterations=30,
        )
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
    hs = np.zeros((sv, su))
    vs = np.zeros((sv, su))
    for j in range(sv):
        for i in range(su):
            if 0 < i < su - 1:
                zx = (blk[j, i + 1] - blk[j, i - 1]) / (xs[i + 1] - xs[i - 1])
            elif i == 0:
                zx = (blk[j, 1] - blk[j, 0]) / (xs[1] - xs[0])
            else:
                zx = (blk[j, -1] - blk[j, -2]) / (xs[-1] - xs[-2])
            if 0 < j < sv - 1:
                zy = (blk[j + 1, i] - blk[j - 1, i]) / (ys[j + 1] - ys[j - 1])
            elif j == 0:
                zy = (blk[1, i] - blk[0, i]) / (ys[1] - ys[0])
            else:
                zy = (blk[-1, i] - blk[-2, i]) / (ys[-1] - ys[-2])
            n = np.array([-zx, -zy, 1.0])
            ln = np.linalg.norm(n)
            if ln < 1e-14:
                continue
            n /= ln
            p = np.array([xs[i], ys[j], blk[j, i]])
            I = p - source
            I /= np.linalg.norm(I)
            R = I - 2.0 * np.dot(I, n) * n
            R /= np.linalg.norm(R)
            hs[j, i] = np.rad2deg(np.arctan2(R[0], R[2]))
            vs[j, i] = np.rad2deg(np.arcsin(np.clip(R[1], -1.0, 1.0)))
    return hs, vs


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

    realized_h ≈ ah + bh·target_h   and   realized_v ≈ av + bv·target_v
    are fitted at the nodes of the pass-1 solution.  The corrected target map
    (h-ah)/bh, (v-av)/bv makes the realised far-field extent of the facet equal
    the requested angle range (rectangular spot).
    """
    calib: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
    for key, blk in blocks.items():
        xs, ys = grids[key]
        th, tv = [], []
        rh, rv = [], []
        for j in range(1, sv - 1):
            for i in range(1, su - 1):
                h_, v_ = spreads.target_angles_on_facet(
                    key[0], key[1], i / max(su - 1, 1), j / max(sv - 1, 1)
                )
                th.append(h_)
                tv.append(v_)
        hs, vs = _realized_angles_on_block(blk, xs, ys, source)
        for j in range(1, sv - 1):
            for i in range(1, su - 1):
                rh.append(hs[j, i])
                rv.append(vs[j, i])
        th, tv, rh, rv = map(np.asarray, (th, tv, rh, rv))

        def fit(target, realized):
            if float(np.ptp(target)) < 1e-6:
                return 0.0, 1.0
            slope, intercept = np.polyfit(target, realized, 1)
            slope = float(np.clip(slope, 0.5, 1.5))
            return float(intercept), slope

        ah, bh = fit(th, rh)
        av, bv = fit(tv, rv)
        calib[key] = (ah, bh, av, bv)
    return calib


def _shared_border_curves(
    blocks: Dict[Tuple[int, int], np.ndarray], su: int, sv: int
) -> Dict[Tuple[str, int, int], np.ndarray]:
    """
    Build one consistent curve per internal border by averaging the facing
    edges of the adjacent facets, with grid corners averaged over all facets
    sharing them.  Keys: ("u", iu_border, iv) for a vertical border at
    x_edges[iu_border] (0 < iu_border < n_u), and ("v", iu, iv_border) for a
    horizontal border at y_edges[iv_border] (0 < iv_border < n_v).
    """
    n_u = max(b[0] for b in blocks) + 1
    n_v = max(b[1] for b in blocks) + 1
    corners: Dict[Tuple[int, int], List[np.ndarray]] = {}
    for (iu, iv), blk in blocks.items():
        for ci, (di, dj) in enumerate(((0, 0), (su - 1, 0), (su - 1, sv - 1), (0, sv - 1))):
            key = (iu + (1 if di == su - 1 else 0), iv + (1 if dj == sv - 1 else 0))
            corners.setdefault(key, []).append(blk[dj, di])
    corner_val = {k: np.mean(np.asarray(v), axis=0) for k, v in corners.items()}

    curves: Dict[Tuple[str, int, int], np.ndarray] = {}
    for iu in range(1, n_u):
        for iv in range(n_v):
            a = blocks[(iu - 1, iv)]
            b = blocks[(iu, iv)]
            curve = 0.5 * (a[:, -1] + b[:, 0])
            curve[0] = corner_val[(iu, iv)]
            curve[-1] = corner_val[(iu, iv + 1)]
            curves[("u", iu, iv)] = curve
    for iv in range(1, n_v):
        for iu in range(n_u):
            a = blocks[(iu, iv - 1)]
            b = blocks[(iu, iv)]
            curve = 0.5 * (a[-1, :] + b[0, :])
            curve[0] = corner_val[(iu, iv)]
            curve[-1] = corner_val[(iu + 1, iv)]
            curves[("v", iu, iv)] = curve
    return curves


def _ls_reconstruct_with_borders(
    dzx: np.ndarray,
    dzy: np.ndarray,
    x_coords: Sequence[float],
    y_coords: Sequence[float],
    z_borders: Dict[str, Optional[np.ndarray]],
) -> np.ndarray:
    """Least-squares gradient matching with Dirichlet border rows/columns."""
    nv, nu = dzx.shape
    N = nv * nu
    xs = np.asarray(x_coords, dtype=float)
    ys = np.asarray(y_coords, dtype=float)

    n_eq = nv * (nu - 1) + (nv - 1) * nu
    A = np.zeros((n_eq, N))
    b = np.zeros(n_eq)
    k = 0
    for j in range(nv):
        for i in range(nu - 1):
            dx = xs[i + 1] - xs[i]
            if dx <= 0.0:
                continue
            A[k, j * nu + i + 1] = 1.0 / dx
            A[k, j * nu + i] = -1.0 / dx
            b[k] = dzx[j, i]
            k += 1
    for j in range(nv - 1):
        for i in range(nu):
            dy = ys[j + 1] - ys[j]
            if dy <= 0.0:
                continue
            A[k, (j + 1) * nu + i] = 1.0 / dy
            A[k, j * nu + i] = -1.0 / dy
            b[k] = dzy[j, i]
            k += 1
    A = A[:k]
    b = b[:k]

    z_fixed = np.zeros(N)
    fixed = np.zeros(N, dtype=bool)
    for side, arr in z_borders.items():
        if arr is None:
            continue
        arr = np.asarray(arr, dtype=float)
        if side in ("left", "right"):
            idx = 0 if side == "left" else nu - 1
            for j in range(nv):
                z_fixed[j * nu + idx] = arr[j]
                fixed[j * nu + idx] = True
        else:
            idx = 0 if side == "bottom" else nv - 1
            for i in range(nu):
                z_fixed[idx * nu + i] = arr[i]
                fixed[idx * nu + i] = True

    free = ~fixed
    if not free.any():
        return z_fixed.reshape(nv, nu)

    Am = A[:, free]
    bm = b - (A[:, fixed] @ z_fixed[fixed])
    sol, *_ = np.linalg.lstsq(Am, bm, rcond=None)
    z = np.zeros(N)
    z[fixed] = z_fixed[fixed]
    z[free] = sol
    return z.reshape(nv, nu)


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
    for _ in range(max_iter):
        dzx = np.zeros((sv, su))
        dzy = np.zeros((sv, su))
        for lj in range(sv):
            for li in range(su):
                pt = np.array([xs[li], ys[lj], z_loc[lj, li]])
                h_deg, v_deg = spread_target(li, lj)
                n_req = _required_normal(source, pt, _target_direction_from_angles(h_deg, v_deg))
                sx, sy = _slopes_from_normal(n_req)
                dzx[lj, li] = sx
                dzy[lj, li] = sy
        z_new = _ls_reconstruct_with_borders(dzx, dzy, xs, ys, zb)
        delta = float(np.max(np.abs(z_new - z_loc)))
        z_loc = z_new
        if delta <= tol:
            break
    return z_loc + z_step


def _bilinear_sample(grid_pts: np.ndarray, u: float, v: float) -> np.ndarray:
    sv, su, _ = grid_pts.shape
    ii = float(np.clip(u * (su - 1), 0, su - 1))
    jj = float(np.clip(v * (sv - 1), 0, sv - 1))
    i0, j0 = int(ii), int(jj)
    i1, j1 = min(i0 + 1, su - 1), min(j0 + 1, sv - 1)
    du, dv = ii - i0, jj - j0
    return (
        (1.0 - du) * (1.0 - dv) * grid_pts[j0, i0]
        + du * (1.0 - dv) * grid_pts[j0, i1]
        + (1.0 - du) * dv * grid_pts[j1, i0]
        + du * dv * grid_pts[j1, i1]
    )


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
        return grid_pts
    sv, su, _ = grid_pts.shape
    u0 = float(shrink_left)
    u1 = 1.0 - float(shrink_right)
    v0 = float(shrink_bottom)
    v1 = 1.0 - float(shrink_top)
    if u1 <= u0 or v1 <= v0:
        raise ValueError("gap shrink would consume the entire facet")
    result = np.zeros_like(grid_pts)
    for j in range(sv):
        v = v0 + (v1 - v0) * (j / max(sv - 1, 1))
        for i in range(su):
            u = u0 + (u1 - u0) * (i / max(su - 1, 1))
            result[j, i] = _bilinear_sample(grid_pts, u, v)
    return result


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
    return [
        (starts[i], starts[i + 1] + (1 if i + 1 < n_patches else 0))
        for i in range(n_patches)
    ]


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

def _apply_edge_delta(ctrl: np.ndarray, edge: str, delta: np.ndarray) -> np.ndarray:
    if edge == "right":
        weights = (1.0 - np.linspace(0.0, 1.0, ctrl.shape[1]))[None, :, None]
    elif edge == "left":
        weights = np.linspace(0.0, 1.0, ctrl.shape[1])[None, :, None]
    elif edge == "top":
        weights = (1.0 - np.linspace(0.0, 1.0, ctrl.shape[0]))[:, None, None]
    else:
        weights = np.linspace(0.0, 1.0, ctrl.shape[0])[:, None, None]
    if edge in ("right", "left"):
        return ctrl + delta[:, None, :] * weights
    return ctrl + delta[None, :, :] * weights


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
    degree: int = 1,
) -> Facet:
    """Ruled NURBS strip between two facing edges (arc-length matched)."""
    n = max(2, max(len(edge_a), len(edge_b)))
    # Match parameterisation by arc length to avoid twisted rulings
    ea = _reparam_arc_length(edge_a, n)
    eb = _reparam_arc_length(edge_b, n)
    ctrl = np.stack([ea, eb], axis=0)  # (2, n, 3)
    deg_v = 1
    deg_u = min(max(1, degree), n - 1)
    from geometry.nurbs import open_uniform_knots
    knots_v = open_uniform_knots(2, deg_v)
    knots_u = open_uniform_knots(n, deg_u)
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
        # Few samples across the narrow gap → avoid ladder-looking mesh
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

    su = max(2, samples_u if samples_u is not None else reflector.mesh_u)
    sv = max(2, samples_v if samples_v is not None else reflector.mesh_v)
    # Equal sample counts per sub-patch keep shared knot vectors identical,
    # which is required for geometric (not merely control-net) continuity.
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

    edge_cache: Dict[Tuple[int, int, int, int], Dict[str, np.ndarray]] = {}
    if use_surface:
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

    if use_surface:
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
                            degree=1,
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
                            degree=1,
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

    reflector.facets = facets
    return facets














