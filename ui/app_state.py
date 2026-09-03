# SPDX-License-Identifier: MIT
"""UI 表单状态 → MFReflector 的收集逻辑（独立于 Tk 布局，可直接单测）。"""

from __future__ import annotations

import numpy as np

from models import (
    EdgeRayMode,
    GapSurfaceMode,
    GapType,
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


def parse_deltas(text: str, n: int, fallback: float = 10.0) -> list:
    """逗号分隔的尺寸列表 → 长度为 n 的列表（不足重复末值）。"""
    parts = [p.strip() for p in str(text).replace(";", ",").split(",") if p.strip()]
    vals = [float(p) for p in parts] if parts else []
    if not vals:
        vals = [fallback]
    if len(vals) < n:
        vals = vals + [vals[-1]] * (n - len(vals))
    return vals[:n]


def collect(app) -> MFReflector:
    """从 app 的 tk 变量收集当前设计参数，构建 MFReflector。"""
    n_u = max(1, int(app.n_u.get()))
    n_v = max(1, int(app.n_v.get()))
    degree_u = max(1, int(app.degree_u.get()))
    degree_v = max(1, int(app.degree_v.get()))
    width_deltas = parse_deltas(app.width_deltas.get(), n_u)
    height_deltas = parse_deltas(app.height_deltas.get(), n_v)
    offset_x = float(app.offset_x.get())
    offset_y = float(app.offset_y.get())
    start_z = float(app.start_z.get())

    calculation_start_u = (
        None if app.start_auto.get() else float(app.calc_start_u.get())
    )
    calculation_start_v = (
        None if app.start_auto.get() else float(app.calc_start_v.get())
    )
    gap_type = GapType(app.gap_type.get())
    step_z = 0.0  # UI 未暴露缝隙 Z 向台阶（gaps.size_z）；如需暴露加输入项

    return MFReflector(
        name="UI_Reflector",
        source=PointSource(
            position=np.array([
                float(app.src_x.get()),
                float(app.src_y.get()),
                float(app.src_z.get()),
            ]),
            pattern=str(app.src_pattern.get()),
            lambert_n=float(app.src_lambert_n.get()),
            axis=None if app.src_axis_auto.get() else np.array([
                float(app.src_axis_x.get()),
                float(app.src_axis_y.get()),
                float(app.src_axis_z.get()),
            ]),
        ),
        grid=GridLayout(
            n_u=n_u,
            n_v=n_v,
            width_deltas=width_deltas,
            height_deltas=height_deltas,
            offset_x=offset_x,
            offset_y=offset_y,
            start_z=start_z,
            focal=float(app.focal.get()),
            degree_u=degree_u,
            degree_v=degree_v,
            use_start_point=app.use_start_point.get(),
            start_point=np.array([float(app.start_x.get()), float(app.start_y.get())]),
        ),
        gaps=GapsConfig(
            enabled=True,
            gap_type=gap_type,
            surface_mode=GapSurfaceMode(app.gap_mode.get()),
            size_u=float(app.gap_u.get()),
            size_v=float(app.gap_v.get()),
            size_z=step_z,
        ),
        spreads=SpreadsConfig(
            light_target=LightTargetType.FAR_FIELD,
            edge_ray=EdgeRayMode(app.edge_ray.get()),
            h_angles=app.spread_h.get(),
            v_angles=app.spread_v.get(),
            uniform_intensity=bool(app.uniform_intensity.get()),
        ),
        solve=SolveMethod(app.solve.get()),
        mesh_u=max(2, int(app.samples.get())),
        mesh_v=max(2, int(app.samples.get())),
        solver_iterations=max(1, int(app.solver_iterations.get())),
        solver_tolerance=float(app.solver_tolerance.get()),
        calculation_start_u=calculation_start_u,
        calculation_start_v=calculation_start_v,
        reference_position_u=float(app.reference_u.get()),
        reference_position_v=float(app.reference_v.get()),
        use_base_curve_from_neighbor=app.use_neighbor_curve.get(),
        z_step_u=float(app.z_step_u.get()),
        z_step_v=float(app.z_step_v.get()),
        patch_fit_method=PatchFitMethod(app.patch_method.get()),
        fit_patches_u=max(1, int(app.fit_patches_u.get())),
        fit_patches_v=max(1, int(app.fit_patches_v.get())),
        fit_patch_continuity_u=PatchContinuity(app.continuity_u.get()),
        fit_patch_continuity_v=PatchContinuity(app.continuity_v.get()),
    )
