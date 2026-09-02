"""Tests for per-facet solver, F.Start steps, gaps, and patch fitting."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from models import (
    EdgeRayMode,
    GapSurfaceMode,
    GapType,
    MFReflector,
    PatchContinuity,
    PatchFitMethod,
    PointSource,
    SolveMethod,
    SpreadsConfig,
)
from models.grid import GridLayout
from models.gaps import GapsConfig
from geometry.engine import _eval_facet, generate_facets


def _reflector(n_u=1, n_v=1, gap_type=GapType.GAP, surface_mode=GapSurfaceMode.EMPTY):
    return MFReflector(
        name="FeatureTest",
        source=PointSource(position=np.array([0.0, 0.0, 0.0])),
        grid=GridLayout(
            n_u=n_u,
            n_v=n_v,
            width_deltas=[4.0] * n_u,
            height_deltas=[4.0] * n_v,
            offset_x=-2.0 * n_u,
            offset_y=-2.0 * n_v,
            focal=25.0,
            degree_u=3,
            degree_v=3,
        ),
        gaps=GapsConfig(
            enabled=True,
            gap_type=gap_type,
            surface_mode=surface_mode,
            size_u=1.0,
            size_v=1.0,
        ),
        spreads=SpreadsConfig(
            global_h_deg=20.0,
            global_v_deg=8.0,
            edge_ray=EdgeRayMode.CENTER,
        ),
        solve=SolveMethod.V_FIRST,
        mesh_u=7,
        mesh_v=7,
        solver_iterations=2,
        patch_fit_method=PatchFitMethod.EXACT,
    )


def test_start_point_and_per_facet_solver():
    reflector = _reflector(2, 2)
    reflector.grid.start_point = np.array([0.2, -0.3])
    x, y, z, su, sv, blocks = __import__("geometry.engine", fromlist=["_build_height_field"])._build_height_field(reflector)
    assert np.isfinite(z).all()
    assert (su, sv) == (7, 7)
    assert z.shape == (13, 13)
    assert x.min() == -4.0 and x.max() == 4.0
    assert y.min() == -4.0 and y.max() == 4.0
    assert np.std(z) > 1e-6

    # Changing calculation start on the seed facet changes the integrated shape
    reflector.calculation_start_u = 0.75
    reflector.calculation_start_v = 0.25
    _, _, z2, _, _, _ = __import__(
        "geometry.engine", fromlist=["_build_height_field"]
    )._build_height_field(reflector)
    assert np.max(np.abs(z2 - z)) > 1e-6


def test_gap_surface_and_empty_modes():
    surface = generate_facets(_reflector(2, 1, GapType.GAP, GapSurfaceMode.SURFACE))
    assert len([f for f in surface if f.is_gap_surface]) == 1

    empty = generate_facets(_reflector(2, 1, GapType.GAP, GapSurfaceMode.EMPTY))
    assert len([f for f in empty if f.is_gap_surface]) == 0
    assert len(empty) == 2


def test_gap_surface_closes_corner_hole():
    facets = generate_facets(
        _reflector(2, 2, GapType.GAP, GapSurfaceMode.SURFACE)
    )
    gap_surfaces = [f for f in facets if f.is_gap_surface]
    # Four edge strips plus one central corner patch.
    assert len(gap_surfaces) == 5
    corner = next(f for f in gap_surfaces if f.ctrl.shape[:2] == (2, 2))
    assert np.allclose(corner.center[:2], [0.0, 0.0], atol=1e-8)


def test_gap_shrink_is_derived_without_hardcoded_cap():
    # deltas include gap: edge facet optical width = delta - gap/2
    # width_delta=4, gap=1 → edge optical = 4 - 0.5 = 3.5
    facets = generate_facets(_reflector(2, 1, GapType.GAP, GapSurfaceMode.EMPTY))
    widths = [float(np.ptp(f.corners[:, 0])) for f in facets]
    assert np.allclose(widths, 3.5, atol=1e-8)

    # middle facet in 3-column grid: optical = delta - gap = 4 - 1 = 3.0
    facets3 = generate_facets(_reflector(3, 1, GapType.GAP, GapSurfaceMode.EMPTY))
    widths3 = [float(np.ptp(f.corners[:, 0])) for f in facets3]
    assert abs(widths3[0] - 3.5) < 1e-8
    assert abs(widths3[1] - 3.0) < 1e-8
    assert abs(widths3[2] - 3.5) < 1e-8


def test_no_gap_new_border_makes_edges_touch():
    facets = generate_facets(_reflector(2, 1, GapType.NO_GAP, GapSurfaceMode.NEW_BORDER))
    old, new = facets
    ts = np.linspace(0.0, 1.0, old.ctrl.shape[0])
    old_edge = np.asarray([_eval_facet(old, 1.0, t) for t in ts])
    new_edge = np.asarray([_eval_facet(new, 0.0, t) for t in ts])
    assert np.max(np.abs(old_edge - new_edge)) < 1e-3


def test_no_gap_old_border_changes_old_facet():
    facets = generate_facets(_reflector(2, 1, GapType.NO_GAP, GapSurfaceMode.OLD_BORDER))
    old, new = facets
    ts = np.linspace(0.0, 1.0, old.ctrl.shape[0])
    old_edge = np.asarray([_eval_facet(old, 1.0, t) for t in ts])
    new_edge = np.asarray([_eval_facet(new, 0.0, t) for t in ts])
    assert np.max(np.abs(old_edge - new_edge)) < 1e-3


def test_step_back_no_gap_applies_z_steps():
    reflector = _reflector(3, 1, GapType.STEP_BACK_NO_GAP, GapSurfaceMode.NEW_BORDER)
    reflector.gaps.size_z = 0.3
    facets = generate_facets(reflector)
    assert [round(f.z_step, 12) for f in facets] == [0.0, 0.3, 0.6]


def test_uniform_intensity_off_matches_legacy():
    a = _reflector(2, 2)
    b = _reflector(2, 2)
    b.spreads.uniform_intensity = False
    za = __import__("geometry.engine", fromlist=["_build_height_field"])._build_height_field(a)[2]
    zb = __import__("geometry.engine", fromlist=["_build_height_field"])._build_height_field(b)[2]
    assert np.allclose(za, zb)


def test_uniform_intensity_changes_surface_when_flux_varies():
    # Close, offset source → strong 1/r² variation across a large facet.
    engine = __import__("geometry.engine", fromlist=["_build_height_field", "_energy_fracs"])
    common = dict(
        n_u=1,
        n_v=1,
    )
    off = _reflector(**common)
    on = _reflector(**common)
    off.source = PointSource(position=np.array([18.0, 12.0, 8.0]))
    on.source = PointSource(position=np.array([18.0, 12.0, 8.0]))
    off.grid.width_deltas = [40.0]
    off.grid.height_deltas = [40.0]
    off.grid.offset_x = -20.0
    off.grid.offset_y = -20.0
    on.grid.width_deltas = [40.0]
    on.grid.height_deltas = [40.0]
    on.grid.offset_x = -20.0
    on.grid.offset_y = -20.0
    on.spreads.uniform_intensity = True
    z_off = engine._build_height_field(off)[2]
    z_on = engine._build_height_field(on)[2]
    assert np.isfinite(z_on).all()
    assert np.max(np.abs(z_on - z_off)) > 1e-4

    xs = np.linspace(-20.0, 20.0, 9)
    ys = np.linspace(-20.0, 20.0, 9)
    xx, yy = np.meshgrid(xs, ys)
    carrier = np.asarray(
        engine._carrier_z(xx, yy, on.source.position, on.grid.focal),
        dtype=float,
    )
    fu, fv = engine._energy_fracs(xs, ys, carrier, on.source.position)
    assert fu[0] == 0.0 and fu[-1] == 1.0
    assert fv[0] == 0.0 and fv[-1] == 1.0
    # Offset source → CDF is not the linear parameter.
    assert np.max(np.abs(fu - np.linspace(0.0, 1.0, fu.size))) > 1e-3

    w_iso = engine._incident_flux_weights(
        xs, ys, carrier, on.source.position, pattern="isotropic"
    )
    w_lam = engine._incident_flux_weights(
        xs, ys, carrier, on.source.position, pattern="lambertian", lambert_n=1.0
    )
    assert np.isfinite(w_lam).all() and np.all(w_lam >= 0.0)
    # Lambertian cosθ_s weights the near-axis cells more than isotropic.
    assert not np.allclose(w_iso, w_lam)


def test_uniform_intensity_kills_offaxis_keystone():
    """Off-axis LED + rectangular spread must not stay an inverted trapezoid."""
    engine = __import__(
        "geometry.engine",
        fromlist=["_build_height_field", "_realized_angles_on_block"],
    )
    r = _reflector(1, 1)
    r.source = PointSource(
        position=np.array([0.0, 0.0, 0.0]),
        axis=np.array([0.0, -1.0, 0.0]),
        pattern="lambertian",
        lambert_n=1.0,
    )
    r.grid.width_deltas = [20.0]
    r.grid.height_deltas = [20.0]
    r.grid.offset_x = -10.0
    r.grid.offset_y = -20.0
    r.grid.focal = 8.0
    r.spreads.h_angles = [-20.0, 20.0]
    r.spreads.v_angles = [-10.0, 10.0]
    r.spreads.uniform_intensity = True
    r.mesh_u = 21
    r.mesh_v = 21
    r.solver_iterations = 5
    xs, ys, z, su, sv, blocks = engine._build_height_field(r)
    hs, vs = engine._realized_angles_on_block(blocks[(0, 0)], xs, ys, r.source.position)
    top = float(hs[-1, -1] - hs[-1, 0])
    bot = float(hs[0, -1] - hs[0, 0])
    mid = vs.shape[1] // 2
    smile = float(vs[0, mid] - 0.5 * (vs[0, 0] + vs[0, -1]))
    # Off-axis 20×20 / f=8 still has a few degrees of H keystone; the
    # smile (bottom V corners vs centre) is what FFD over-produced.
    assert abs(top - bot) < 5.0
    assert abs(top - 40.0) < 4.0
    assert abs(bot - 40.0) < 5.0
    assert abs(smile) < 2.5
    assert float(vs.max()) <= 12.0
    assert float(vs.min()) >= -14.0


def test_source_axis_xyz_overrides_auto():
    engine = __import__("geometry.engine", fromlist=["_source_emission_axis"])
    r = _reflector(1, 1)
    r.source = PointSource(
        position=np.array([0.0, 0.0, 0.0]),
        axis=np.array([0.3, -0.4, -0.5]),
    )
    axis = engine._source_emission_axis(r)
    expect = np.array([0.3, -0.4, -0.5])
    expect = expect / np.linalg.norm(expect)
    assert np.allclose(axis, expect)


def test_fit_patches_with_tangent_continuity():
    reflector = _reflector(1, 1)
    reflector.fit_patches_u = 2
    reflector.fit_patches_v = 2
    reflector.fit_patch_continuity_u = PatchContinuity.TANGENT
    reflector.fit_patch_continuity_v = PatchContinuity.TANGENT
    facets = generate_facets(reflector)
    assert len(facets) == 4
    assert {(f.patch_index_u, f.patch_index_v) for f in facets} == {(0, 0), (1, 0), (0, 1), (1, 1)}

    by_patch = {(f.patch_index_u, f.patch_index_v): f for f in facets}
    left, right = by_patch[(0, 0)], by_patch[(1, 0)]
    shared = left.ctrl[:, -1, :]
    assert np.max(np.abs(shared - right.ctrl[:, 0, :])) < 1e-12
    left_tangent = shared - left.ctrl[:, -2, :]
    right_tangent = right.ctrl[:, 1, :] - shared
    assert np.max(np.abs(left_tangent - right_tangent)) < 1e-12

    ts = np.linspace(0.0, 1.0, 20)
    left_edge = np.asarray([_eval_facet(left, 1.0, t) for t in ts])
    right_edge = np.asarray([_eval_facet(right, 0.0, t) for t in ts])
    assert np.max(np.abs(left_edge - right_edge)) < 1e-10


def test_approximate_keep_size_stays_inside_base_grid():
    reflector = _reflector(1, 1)
    reflector.mesh_u = 9
    reflector.mesh_v = 9
    reflector.patch_fit_method = PatchFitMethod.APPROXIMATE_KEEP_SIZE
    facets = generate_facets(reflector)
    ctrl = facets[0].ctrl
    assert ctrl[:, :, 0].min() >= -4.0 - 1e-12
    assert ctrl[:, :, 0].max() <= 4.0 + 1e-12
    assert ctrl[:, :, 1].min() >= -4.0 - 1e-12
    assert ctrl[:, :, 1].max() <= 4.0 + 1e-12


def test_no_gap_borders_close_in_both_u_and_v():
    facets = generate_facets(
        _reflector(2, 2, GapType.NO_GAP, GapSurfaceMode.NEW_BORDER)
    )
    by_index = {(f.index_u, f.index_v): f for f in facets}
    ts = np.linspace(0.0, 1.0, 20)
    for j in range(2):
        old = by_index[(0, j)]
        new = by_index[(1, j)]
        old_edge = np.asarray([_eval_facet(old, 1.0, t) for t in ts])
        new_edge = np.asarray([_eval_facet(new, 0.0, t) for t in ts])
        assert np.max(np.abs(old_edge - new_edge)) < 1e-3
    for i in range(2):
        old = by_index[(i, 0)]
        new = by_index[(i, 1)]
        old_edge = np.asarray([_eval_facet(old, t, 1.0) for t in ts])
        new_edge = np.asarray([_eval_facet(new, t, 0.0) for t in ts])
        assert np.max(np.abs(old_edge - new_edge)) < 1e-3
if __name__ == "__main__":
    test_start_point_and_per_facet_solver()
    test_gap_surface_and_empty_modes()
    test_gap_surface_closes_corner_hole()
    test_gap_shrink_is_derived_without_hardcoded_cap()
    test_no_gap_new_border_makes_edges_touch()
    test_no_gap_old_border_changes_old_facet()
    test_step_back_no_gap_applies_z_steps()
    test_fit_patches_with_tangent_continuity()
    test_approximate_keep_size_stays_inside_base_grid()
    test_no_gap_borders_close_in_both_u_and_v()
    print("OK – engine feature tests passed.")






