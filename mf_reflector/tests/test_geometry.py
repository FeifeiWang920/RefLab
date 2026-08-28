"""Test NURBS facets + Gap Surface mode."""

from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from models import *
from geometry import generate_facets, facets_to_mesh, export_stl, export_obj


def test_nurbs_and_gap_surface():
    reflector = MFReflector(
        name="Test_NURBS_Gap",
        source=PointSource(position=np.array([0.0, 0.0, 0.0])),
        grid=GridLayout(
            n_u=3, n_v=3,
            width_deltas=[12.0, 12.0, 12.0],
            height_deltas=[12.0, 12.0, 12.0],
            offset_x=-18.0,
            offset_y=-18.0,
            focal=25.0,
            degree_u=3,
            degree_v=3,
        ),
        gaps=GapsConfig(
            enabled=True,
            gap_type=GapType.GAP,
            surface_mode=GapSurfaceMode.SURFACE,   # <-- Gap Surface
            size_u=1.0,
            size_v=1.0,
        ),
        spreads=SpreadsConfig(
            global_h_deg=30.0,
            global_v_deg=10.0,
            edge_ray=EdgeRayMode.CENTER,
        ),
        solve=SolveMethod.V_FIRST,
        mesh_u=6,
        mesh_v=6,
    )

    facets = generate_facets(reflector)
    optical = [f for f in facets if not f.is_gap_surface]
    gap_surfs = [f for f in facets if f.is_gap_surface]

    print(f"Optical facets : {len(optical)}")
    print(f"Gap surfaces   : {len(gap_surfs)}")
    print(f"Total          : {len(facets)}")

    assert len(optical) == 9
    # 3x3 grid → 2 vertical lines of gaps × 3 + 2 horizontal × 3 = 12
    assert len(gap_surfs) == 16, f"expected 16 gap surfaces (edge strips + corner patches), got {len(gap_surfs)}"

    for f in optical:
        assert f.is_nurbs, "optical facet should be NURBS"
        assert f.ctrl is not None
        assert f.degree_u >= 1 and f.degree_v >= 1
        assert f.knots_u is not None and f.knots_v is not None

    all_pts = np.vstack([f.mesh_points() for f in facets])
    print(f"Total mesh pts : {all_pts.shape[0]}")
    print(f"Z range        : [{all_pts[:,2].min():.3f}, {all_pts[:,2].max():.3f}]")
    print(reflector.summary())

    verts, faces = facets_to_mesh(facets)
    out = ROOT / "tests" / "output"
    out.mkdir(exist_ok=True)
    export_stl(verts, faces, str(out / "test_nurbs_gap.stl"))
    export_obj(verts, faces, str(out / "test_nurbs_gap.obj"))
    print(f"Vertices: {verts.shape[0]}, Triangles: {faces.shape[0]}")
    print("OK – NURBS facets + Gap Surface succeeded.")


if __name__ == "__main__":
    test_nurbs_and_gap_surface()



