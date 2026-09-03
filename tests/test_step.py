# SPDX-License-Identifier: MIT
"""Test precise STEP export of NURBS reflector."""

from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pytest

pytest.importorskip("OCP", reason="cadquery/OCP not installed – STEP export tests skipped")
from models import *
from geometry import generate_facets, export_step


def test_step_export():
    reflector = MFReflector(
        name="STEP_Test",
        source=PointSource(position=np.array([0.0, 0.0, 0.0])),
        grid=GridLayout(
            n_u=3, n_v=2,
            width_deltas=[15.0, 15.0, 15.0],
            height_deltas=[15.0, 15.0],
            offset_x=-22.5,
            offset_y=-15.0,
            focal=25.0,
            degree_u=3,
            degree_v=3,
        ),
        gaps=GapsConfig(
            enabled=True,
            gap_type=GapType.GAP,
            surface_mode=GapSurfaceMode.SURFACE,
            size_u=0.8,
            size_v=0.8,
        ),
        spreads=SpreadsConfig(
            global_h_deg=30.0,
            global_v_deg=12.0,
            edge_ray=EdgeRayMode.CENTER,
        ),
        solve=SolveMethod.V_FIRST,
        mesh_u=7,
        mesh_v=7,
    )

    facets = generate_facets(reflector)
    optical = [f for f in facets if not f.is_gap_surface]
    print(f"Optical NURBS facets: {len(optical)}")
    print(f"Gap surfaces        : {len(facets) - len(optical)}")

    out = ROOT / "tests" / "output"
    out.mkdir(exist_ok=True)
    stp_path = str(out / "mf_reflector.stp")

    n = export_step(facets, stp_path, include_gap_surfaces=True)
    print(f"Faces written to STEP: {n}")
    print(f"File: {stp_path}")
    print(f"Size: {Path(stp_path).stat().st_size} bytes")

    assert Path(stp_path).exists()
    assert Path(stp_path).stat().st_size > 1000
    assert n >= len(optical)
    print("OK – precise STEP export succeeded.")


if __name__ == "__main__":
    test_step_export()
