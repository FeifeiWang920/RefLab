# SPDX-License-Identifier: MIT
"""Golden-master capture utility for the height-field solver.

Builds reflectors for a fixed parameter matrix and dumps every solved
height block to an .npz file.  Run with the *unmodified* engine to create
the baseline; tests/test_golden_height_field.py then re-runs the same
matrix after optimisations and asserts bit-level-tight agreement
(max |dz| < 1e-8 mm) so refactors cannot silently change the optics.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import (
    EdgeRayMode,
    GapType,
    GapSurfaceMode,
    LightTargetType,
    MFReflector,
    PatchContinuity,
    PatchFitMethod,
    PointSource,
    GridLayout,
    GapsConfig,
    SolveMethod,
    SpreadsConfig,
)
from geometry.engine import _build_height_field

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_height_fields.npz"


def make_reflector(grid=None, gaps=None, spreads=None, **overrides) -> MFReflector:
    kwargs = dict(
        name="golden",
        source=PointSource(position=np.array([0.0, 0.0, 0.0])),
        grid=grid or GridLayout(
            n_u=4, n_v=4,
            width_deltas=[10.0] * 4, height_deltas=[10.0] * 4,
            offset_x=-20.0, offset_y=-20.0, start_z=0.0, focal=10.0,
            degree_u=5, degree_v=5,
            use_start_point=True, start_point=np.array([0.0, 0.0]),
        ),
        gaps=gaps or GapsConfig(enabled=True, gap_type=GapType.GAP,
                                surface_mode=GapSurfaceMode.SURFACE,
                                size_u=0.2, size_v=0.2, size_z=0.0),
        spreads=spreads or SpreadsConfig(
            light_target=LightTargetType.FAR_FIELD,
            edge_ray=EdgeRayMode.CENTER,
            h_angles="-20,20", v_angles="-10,10",
            uniform_intensity=False,
        ),
        solve=SolveMethod.V_FIRST,
        mesh_u=15, mesh_v=15,
        solver_iterations=5, solver_tolerance=1e-5,
        calculation_start_u=None, calculation_start_v=None,
        reference_position_u=0.0, reference_position_v=0.0,
        use_base_curve_from_neighbor=False, z_step_u=0.0, z_step_v=0.0,
        patch_fit_method=PatchFitMethod.APPROXIMATE,
        fit_patches_u=1, fit_patches_v=1,
        fit_patch_continuity_u=PatchContinuity.POINT,
        fit_patch_continuity_v=PatchContinuity.POINT,
    )
    kwargs.update(overrides)
    return MFReflector(**kwargs)


def case_matrix() -> dict:
    """name -> reflector.  Kept small enough for a seconds-long test run."""

    def with_grid(n: int, **overrides) -> MFReflector:
        return make_reflector(
            grid=GridLayout(
                n_u=n, n_v=n,
                width_deltas=[10.0] * n, height_deltas=[10.0] * n,
                offset_x=-20.0, offset_y=-20.0, start_z=0.0, focal=10.0,
                degree_u=5, degree_v=5,
                use_start_point=True, start_point=np.array([0.0, 0.0]),
            ),
            **overrides,
        )

    def spreads(uniform: bool, edge: EdgeRayMode = EdgeRayMode.CENTER) -> SpreadsConfig:
        return SpreadsConfig(
            light_target=LightTargetType.FAR_FIELD,
            edge_ray=edge,
            h_angles="-20,20", v_angles="-10,10",
            uniform_intensity=uniform,
        )

    def gaps(mode: GapType) -> GapsConfig:
        return GapsConfig(enabled=True, gap_type=mode,
                          surface_mode=GapSurfaceMode.SURFACE,
                          size_u=0.2, size_v=0.2, size_z=0.0)

    return {
        # 默认 4×4
        "default4": with_grid(4),
        # 均匀光强（5 轮空间迭代的最重路径），用小网格控制时长
        "uniform3": with_grid(3, spreads=spreads(True)),
        # 边缘光线两种模式
        "edgemin4": with_grid(4, spreads=spreads(False, EdgeRayMode.MIN)),
        "edgemax4": with_grid(4, spreads=spreads(False, EdgeRayMode.MAX)),
        # 无缝模式
        "nogap4": with_grid(4, gaps=gaps(GapType.NO_GAP)),
        # 邻边基线（两遍 Dirichlet 边界重解）
        "neighbor4": with_grid(4, use_base_curve_from_neighbor=True),
        # 非对称网格
        "grid6": with_grid(6),
    }


def capture(out_path: Path = GOLDEN_PATH) -> None:
    blobs: dict[str, np.ndarray] = {}
    for name, refl in case_matrix().items():
        x_coords, y_coords, z, _su_g, _sv_g, blocks = _build_height_field(refl)
        blobs[f"{name}__x"] = x_coords
        blobs[f"{name}__y"] = y_coords
        blobs[f"{name}__z"] = z
        for (iu, iv), blk in blocks.items():
            blobs[f"{name}__b_{iu}_{iv}"] = blk
    np.savez_compressed(out_path, **blobs)
    print(f"captured {len(blobs)} arrays -> {out_path}")


if __name__ == "__main__":
    capture()
