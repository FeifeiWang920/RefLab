# SPDX-License-Identifier: MIT
"""
RefLab geometry engine —— 逐面片求解流水线编排（门面模块）。

求解原语分布在 geometry.mathutils / flux / reconstruction / solve / facets /
parallel；本模块只保留：全局求解顺序（F.Start / BFS）、五个求解阶段
（Pass 1 绝对求解、Pass 2 仿射校准、逆问题迭代、抛光、Pass 3 邻边缝合）
与 `_build_height_field`。`generate_facets` 的实现在 geometry.facets，
此处提供门面转发（延迟导入避免循环依赖）。
"""

from __future__ import annotations

from geometry.parallel import _parallel_map
from geometry.mathutils import _carrier_z
from geometry.flux import _energy_fracs, _incident_flux_weights, _linear_fracs, _source_emission_axis
from geometry.solve import (  # noqa: F401 – 部分为测试兼容 re-export
    _apply_affine,
    _calibrate_facets,
    _eval_facet,
    _polish_farfield_rectangle,
    _realized_angles_on_block,
    _separable_inverse_target,
    _solve_facet_optical,
    _solve_facet_with_borders,
    _spatial_intensity_inverse,
    _target_fn_from_fracs,
)

from typing import Dict, List, NamedTuple, Tuple
import logging
import numpy as np

from models.reflector import MFReflector
from models.grid import GridLayout
from models.facet import Facet
from models.enums import LightTargetType, SolveMethod
from geometry import tuning

logger = logging.getLogger(__name__)


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


class HeightField(NamedTuple):
    """`_build_height_field` 的结果：全局坐标、拼装高度场与逐面片块。"""

    x_coords: np.ndarray
    y_coords: np.ndarray
    z: np.ndarray
    su: int
    sv: int
    blocks: Dict[Tuple[int, int], np.ndarray]


class _GridCtx(NamedTuple):
    """一次流水线共享的逐面片几何数据（子网格/种子/载体高度）。"""

    su: int
    sv: int
    n_u: int
    n_v: int
    solve_order: List[Tuple[int, int]]
    parents: Dict[Tuple[int, int], Tuple[int, int]]
    facet_grids: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]]
    facet_seeds: Dict[Tuple[int, int], Tuple[int, int, float]]
    carriers: Dict[Tuple[int, int], np.ndarray]


class _EnergyCtx(NamedTuple):
    """能量映射上下文（均匀光强模式使用）。"""

    use_energy: bool
    kw: Dict[str, object]
    gamma: float


def _subgrid_coords(
    grid: GridLayout, su: int, sv: int
) -> Tuple[np.ndarray, np.ndarray]:
    """全局逐节点子网格坐标（相邻面片共享边界列）。"""
    x_edges = grid.node_x_coords()
    y_edges = grid.node_y_coords()
    x_list: List[float] = []
    for iu in range(grid.n_u):
        for k in range(su - 1):
            t = k / (su - 1)
            x_list.append((1.0 - t) * x_edges[iu] + t * x_edges[iu + 1])
    x_list.append(x_edges[-1])
    y_list: List[float] = []
    for iv in range(grid.n_v):
        for k in range(sv - 1):
            t = k / (sv - 1)
            y_list.append((1.0 - t) * y_edges[iv] + t * y_edges[iv + 1])
    y_list.append(y_edges[-1])
    return np.asarray(x_list, dtype=float), np.asarray(y_list, dtype=float)


def _plan_facets(
    reflector: MFReflector,
    source: np.ndarray,
    focal: float,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    su: int,
    sv: int,
    start: Tuple[int, int, float, float],
    solve_order: List[Tuple[int, int]],
    parents: Dict[Tuple[int, int], Tuple[int, int]],
) -> _GridCtx:
    """为每个面片准备子网格、计算种子（F.Start）与载体高度。"""
    start_iu, start_iv, start_local_u, start_local_v = start
    grid = reflector.grid
    facet_grids: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]] = {}
    facet_seeds: Dict[Tuple[int, int], Tuple[int, int, float]] = {}
    carriers: Dict[Tuple[int, int], np.ndarray] = {}
    for iu, iv in solve_order:
        i0 = iu * (su - 1)
        j0 = iv * (sv - 1)
        facet_grids[(iu, iv)] = (x_coords[i0:i0 + su], y_coords[j0:j0 + sv])

        xx, yy = np.meshgrid(x_coords[i0:i0 + su], y_coords[j0:j0 + sv])
        carrier = np.asarray(_carrier_z(xx, yy, source, focal), dtype=float)
        carriers[(iu, iv)] = carrier

        # --- calculation start (F.Start / auto = reference) ---
        if (iu, iv) == (start_iu, start_iv):
            seed_u = start_local_u
            seed_v = start_local_v
        else:
            # automatic start point uses reference position (LS doc)
            seed_u = float(
                reflector.calculation_start_u
                if reflector.calculation_start_u is not None
                else reflector.reference_position_u
            )
            seed_v = float(
                reflector.calculation_start_v
                if reflector.calculation_start_v is not None
                else reflector.reference_position_v
            )
        seed_i = int(np.clip(round(seed_u * (su - 1)), 0, su - 1))
        seed_j = int(np.clip(round(seed_v * (sv - 1)), 0, sv - 1))
        # Height reference = carrier + grid.start_z at the calculation-start
        # point (base plane).
        z_ref = float(carrier[seed_j, seed_i]) + grid.start_z + grid.offset_z
        facet_seeds[(iu, iv)] = (seed_i, seed_j, z_ref)
    return _GridCtx(
        su, sv, grid.n_u, grid.n_v, solve_order, parents,
        facet_grids, facet_seeds, carriers,
    )


def _pass_absolute(
    reflector: MFReflector,
    source: np.ndarray,
    spreads,
    g: _GridCtx,
    e: _EnergyCtx,
) -> Tuple[Dict[Tuple[int, int], np.ndarray], Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray]]]:
    """Pass 1：每个面片按目标角度独立绝对求解（锚定载体）。

    返回 (绝对高度块, 能量映射)。能量映射先按载体初始化，Pass 1 后按解刷新。
    """
    # Separable H(u), V(v) only.  A 2-D nested CDF makes H depend on v
    # and V on u, which shears the far-field rectangle into a pillow.
    energy_maps = {
        key: (
            _energy_fracs(xs, ys, g.carriers[key], source, gamma=e.gamma, **e.kw)
            if e.use_energy
            else _linear_fracs(g.su, g.sv)
        )
        for key, (xs, ys) in g.facet_grids.items()
    }

    def solve_one(key):
        iu, iv = key
        xs, ys = g.facet_grids[key]
        seed_i, seed_j, z_ref = g.facet_seeds[key]
        raw_target = _target_fn_from_fracs(spreads, iu, iv, *energy_maps[key])
        return key, _solve_facet_optical(
            reflector, xs, ys, source, raw_target, g.su, g.sv,
            z_seed=z_ref, seed_i=seed_i, seed_j=seed_j, z_init=g.carriers[key],
        )

    abs_blocks = dict(_parallel_map(solve_one, g.solve_order))
    if e.use_energy:
        for key, blk in abs_blocks.items():
            xs, ys = g.facet_grids[key]
            energy_maps[key] = _energy_fracs(
                xs, ys, blk, source, gamma=e.gamma, **e.kw
            )
    return abs_blocks, energy_maps


def _pass_affine(
    reflector, source, spreads, g: _GridCtx,
    abs_blocks, energy_maps,
) -> Tuple[Dict[Tuple[int, int], np.ndarray], Dict[Tuple[int, int], Tuple[float, float, float, float]]]:
    """Pass 2：边缘极值仿射校准（仅范围），补偿可积投影的整体拉伸/平移。"""
    calib = _calibrate_facets(abs_blocks, g.facet_grids, source, spreads, g.su, g.sv)
    acc_calib: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {
        k: (0.0, 1.0, 0.0, 1.0) for k in abs_blocks
    }
    acc_calib.update(calib)

    def solve_one(key):
        iu, iv = key
        xs, ys = g.facet_grids[key]
        seed_i, seed_j, z_ref = g.facet_seeds[key]
        a1, b1, a2, b2 = calib[key]
        base_fn = _target_fn_from_fracs(spreads, iu, iv, *energy_maps[key])

        def cal_target(li: int, lj: int, a1=a1, b1=b1, a2=a2, b2=b2,
                       base_fn=base_fn) -> Tuple[float, float]:
            h_deg, v_deg = base_fn(li, lj)
            return _apply_affine(h_deg, v_deg, a1, b1, a2, b2)

        return key, _solve_facet_optical(
            reflector, xs, ys, source, cal_target, g.su, g.sv,
            z_seed=z_ref, seed_i=seed_i, seed_j=seed_j,
            z_init=abs_blocks[key],
        )

    return dict(_parallel_map(solve_one, g.solve_order)), acc_calib


def _pass_inverse(
    reflector, source, spreads, g: _GridCtx, e: _EnergyCtx,
    cal_blocks, energy_maps, acc_calib,
):
    """逆问题迭代：实测反射角 vs 目标角纠偏（均匀光强多轮，否则 1 轮）。

    LucidShape FFD spatial-iterations 默认 1；矩形来自第一个曲面而非循环。
    """
    residual_targets: Dict[Tuple[int, int], object] = {}
    n_spatial = tuning.SPATIAL_PASSES_UNIFORM if e.use_energy else 1
    for k in range(n_spatial):
        gain = (
            tuning.GAIN_SCHEDULE_BASE * (tuning.GAIN_SCHEDULE_DECAY ** k)
            if e.use_energy
            else tuning.GAIN_FIXED
        )
        if e.use_energy:
            for key, blk in cal_blocks.items():
                xs, ys = g.facet_grids[key]
                energy_maps[key] = _energy_fracs(
                    xs, ys, blk, source, gamma=e.gamma, **e.kw
                )

        def solve_one(key, gain=gain):
            iu, iv = key
            xs, ys = g.facet_grids[key]
            seed_i, seed_j, z_ref = g.facet_seeds[key]
            a1, b1, a2, b2 = acc_calib[key]
            fu, fv = energy_maps[key]
            hs_r, vs_r = _realized_angles_on_block(cal_blocks[key], xs, ys, source)
            if e.use_energy:
                flux = _incident_flux_weights(
                    xs, ys, cal_blocks[key], source, **e.kw
                )
                fn = _spatial_intensity_inverse(
                    iu, iv, g.su, g.sv, spreads, hs_r, vs_r, flux,
                    gain=gain, target_min=0.1,
                )
            else:
                fn = _separable_inverse_target(
                    iu, iv, g.su, g.sv, spreads, hs_r, vs_r,
                    a1, b1, a2, b2, gain=gain, frac_u=fu, frac_v=fv,
                )
            blk = _solve_facet_optical(
                reflector, xs, ys, source, fn, g.su, g.sv,
                z_seed=z_ref, seed_i=seed_i, seed_j=seed_j,
                z_init=cal_blocks[key],
            )
            return key, blk, fn

        new_inv: Dict[Tuple[int, int], np.ndarray] = {}
        for key, blk, fn in _parallel_map(solve_one, g.solve_order):
            new_inv[key] = blk
            residual_targets[key] = fn
        cal_blocks = new_inv
    return cal_blocks, residual_targets


def _polish_energy_blocks(source, spreads, g: _GridCtx, cal_blocks):
    """均匀光强模式：远场矩形轮廓抛光。"""
    for key, blk in list(cal_blocks.items()):
        iu, iv = key
        xs, ys = g.facet_grids[key]
        h0, _ = spreads.target_angles_on_facet(iu, iv, 0.0, 0.5)
        h1, _ = spreads.target_angles_on_facet(iu, iv, 1.0, 0.5)
        _, v0 = spreads.target_angles_on_facet(iu, iv, 0.5, 0.0)
        _, v1 = spreads.target_angles_on_facet(iu, iv, 0.5, 1.0)
        cal_blocks[key] = _polish_farfield_rectangle(
            blk, xs, ys, source, h0, h1, v0, v1, passes=tuning.POLISH_PASSES,
        )
    return cal_blocks


def _pass_stitch(
    reflector, source, spreads, g: _GridCtx, e: _EnergyCtx,
    cal_blocks, energy_maps, residual_targets, acc_calib,
    z_step_u: float, z_step_v: float,
) -> Tuple[Dict[Tuple[int, int], np.ndarray], np.ndarray]:
    """Pass 3：邻边基线（Dirichlet 重解）或参考点刚性偏移 + Z 台阶，并拼装全局高度场。"""
    nu = g.n_u * (g.su - 1) + 1
    nv = g.n_v * (g.sv - 1) + 1
    z = np.zeros((nv, nu), dtype=float)
    blocks: Dict[Tuple[int, int], np.ndarray] = {}
    if reflector.use_base_curve_from_neighbor:
        # Optional full shared-edge curve matching: average the facing edge
        # curves of adjacent facets, then re-solve each facet with those
        # curves as Dirichlet boundary conditions -> C0 borders.  NOTE: this
        # bends the facet optics near every shared border (the two designs
        # demand opposite edge slopes), so the far-field range is only
        # approximate; the reference-point mode below is the optical default.
        border_curves = _shared_border_curves(cal_blocks, g.su, g.sv)

        def solve_one(key):
            iu, iv = key
            xs, ys = g.facet_grids[key]
            zb = {
                "left": border_curves[("u", iu, iv)] if iu > 0 else None,
                "right": border_curves[("u", iu + 1, iv)] if iu < g.n_u - 1 else None,
                "bottom": border_curves[("v", iu, iv)] if iv > 0 else None,
                "top": border_curves[("v", iu, iv + 1)] if iv < g.n_v - 1 else None,
            }
            ah, bh, av, bv = acc_calib[key]
            fn = residual_targets.get(key)
            if fn is None:
                fu, fv = energy_maps[key]
                base_fn = _target_fn_from_fracs(spreads, iu, iv, fu, fv)

                def fn(li: int, lj: int, ah=ah, bh=bh, av=av, bv=bv,
                       base_fn=base_fn) -> Tuple[float, float]:
                    return _apply_affine(*base_fn(li, lj), ah, bh, av, bv)
            blk = _solve_facet_with_borders(
                reflector, cal_blocks[key], spread_target=fn,
                xs=xs, ys=ys, source=source, zb=zb,
                su=g.su, sv=g.sv, z_step=float(iu * z_step_u + iv * z_step_v),
            )
            return key, blk

        for (iu, iv), blk in _parallel_map(solve_one, g.solve_order):
            blocks[(iu, iv)] = blk
            i0 = iu * (g.su - 1)
            j0 = iv * (g.sv - 1)
            z[j0:j0 + g.sv, i0:i0 + g.su] = blk
    else:
        # Reference-position rigid offset against the BFS parent (the parent
        # is always already solved, so the old "snap to carrier" patchwork is
        # gone).  A Z step is added per facet index afterwards.
        for iu, iv in g.solve_order:
            i0 = iu * (g.su - 1)
            j0 = iv * (g.sv - 1)
            z_loc = cal_blocks[(iu, iv)].copy()
            parent = g.parents.get((iu, iv))
            if parent is not None:
                piu, piv = parent
                neigh = blocks[(piu, piv)]
                if piu == iu - 1:
                    ref = float(np.clip(reflector.reference_position_v, 0.0, 1.0))
                    idx = int(round(ref * (g.sv - 1)))
                    z_loc += float(neigh[idx, -1] - z_loc[idx, 0])
                elif piu == iu + 1:
                    ref = float(np.clip(reflector.reference_position_v, 0.0, 1.0))
                    idx = int(round(ref * (g.sv - 1)))
                    z_loc += float(neigh[idx, 0] - z_loc[idx, -1])
                elif piv == iv - 1:
                    ref = float(np.clip(reflector.reference_position_u, 0.0, 1.0))
                    idx = int(round(ref * (g.su - 1)))
                    z_loc += float(neigh[-1, idx] - z_loc[0, idx])
                elif piv == iv + 1:
                    ref = float(np.clip(reflector.reference_position_u, 0.0, 1.0))
                    idx = int(round(ref * (g.su - 1)))
                    z_loc += float(neigh[0, idx] - z_loc[-1, idx])
            z_loc = z_loc + (iu * z_step_u + iv * z_step_v)
            blocks[(iu, iv)] = z_loc
            z[j0:j0 + g.sv, i0:i0 + g.su] = z_loc
    return blocks, z


def generate_facets(
    reflector: MFReflector,
    samples_u: int | None = None,
    samples_v: int | None = None,
) -> List[Facet]:
    """门面：实际实现在 geometry.facets（延迟导入避免循环依赖）。"""
    from geometry.facets import generate_facets as _impl

    return _impl(reflector, samples_u, samples_v)


def _build_height_field(reflector: MFReflector) -> HeightField:
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
        neighbour along the *full* shared-edge curve via Dirichlet re-solve.
        This makes the whole facet family watertight (C0) at every shared
        border — no banks, wrinkles or twisted step surfaces between facets.
      - Z steps: added per facet index after the border match.

    Facets are intentionally *not* one C1 surface — gaps separate them.
    """
    grid = reflector.grid
    spreads = reflector.spreads
    if spreads.light_target is not LightTargetType.FAR_FIELD:
        raise NotImplementedError(
            f"light_target={spreads.light_target.value!r} 尚未实现——"
            "引擎当前仅支持 far field（如需其余目标模式请提 issue 或扩展 "
            "_build_height_field 的目标方向解析）"
        )
    source = reflector.source.position.copy()
    su = max(2, reflector.mesh_u)
    sv = max(2, reflector.mesh_v)

    x_coords, y_coords = _subgrid_coords(grid, su, sv)
    start = _start_facet(reflector)
    solve_order, parents = _solve_order(
        grid.n_u, grid.n_v, (start[0], start[1]), reflector.solve
    )
    g = _plan_facets(
        reflector, source, grid.focal, x_coords, y_coords, su, sv,
        start, solve_order, parents,
    )
    use_energy = bool(spreads.uniform_intensity)
    e = _EnergyCtx(
        use_energy=use_energy,
        kw=dict(
            axis=_source_emission_axis(reflector),
            pattern=getattr(reflector.source, "pattern", "lambertian"),
            lambert_n=float(getattr(reflector.source, "lambert_n", 1.0)),
        ),
        gamma=float(getattr(spreads, "energy_gamma", 1.0)) if use_energy else 1.0,
    )

    abs_blocks, energy_maps = _pass_absolute(reflector, source, spreads, g, e)
    cal_blocks, acc_calib = _pass_affine(
        reflector, source, spreads, g, abs_blocks, energy_maps
    )
    cal_blocks, residual_targets = _pass_inverse(
        reflector, source, spreads, g, e, cal_blocks, energy_maps, acc_calib
    )
    if e.use_energy:
        cal_blocks = _polish_energy_blocks(source, spreads, g, cal_blocks)

    z_step_u = reflector.z_step_u + reflector.gaps.effective_step_z()
    z_step_v = reflector.z_step_v + reflector.gaps.effective_step_z()
    blocks, z = _pass_stitch(
        reflector, source, spreads, g, e,
        cal_blocks, energy_maps, residual_targets, acc_calib, z_step_u, z_step_v,
    )
    return HeightField(x_coords, y_coords, z, su, sv, blocks)


# ---------------------------------------------------------------------------
# Per-facet optical solve + spread calibration
# ---------------------------------------------------------------------------


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


