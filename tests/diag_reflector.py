"""Final verification: fitted-NURBS reflection-angle accuracy + C0 borders + edge cases."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np

from models import (MFReflector, PointSource, GridLayout, GapsConfig, SpreadsConfig,
                    GapType, GapSurfaceMode, EdgeRayMode, SolveMethod, PatchFitMethod)
from geometry import generate_facets
from geometry.nurbs import eval_surface
import geometry.engine as eng


def build(n_u=4, n_v=4, gap=0.2, **kw):
    return MFReflector(
        name="Verify",
        source=PointSource(position=np.array([0.0, 0.0, 0.0])),
        grid=GridLayout(
            n_u=n_u, n_v=n_v,
            width_deltas=[10.0] * n_u, height_deltas=[10.0] * n_v,
            offset_x=-5.0 * n_u, offset_y=-5.0 * n_v,
            focal=10.0, degree_u=5, degree_v=5,
            use_start_point=True, start_point=np.array([0.0, 0.0]),
        ),
        gaps=GapsConfig(enabled=True, gap_type=GapType.GAP,
                        surface_mode=GapSurfaceMode.SURFACE, size_u=gap, size_v=gap),
        spreads=SpreadsConfig(h_angles="-20,20", v_angles="-10,10",
                              edge_ray=EdgeRayMode.CENTER),
        solve=SolveMethod.V_FIRST,
        mesh_u=6, mesh_v=6,
        solver_iterations=5, solver_tolerance=1e-5,
        patch_fit_method=PatchFitMethod.APPROXIMATE,
        **kw,
    )


def surf_normal(facet, u, v):
    e = 1e-5
    du = -e if u >= 1.0 else e
    dv = -e if v >= 1.0 else e
    p00 = eval_surface(facet.ctrl, facet.degree_u, facet.degree_v, facet.knots_u, facet.knots_v, u, v)
    p10 = eval_surface(facet.ctrl, facet.degree_u, facet.degree_v, facet.knots_u, facet.knots_v, u + du, v)
    p01 = eval_surface(facet.ctrl, facet.degree_u, facet.degree_v, facet.knots_u, facet.knots_v, u, v + dv)
    n = np.cross(p10 - p00, p01 - p00)
    nrm = np.linalg.norm(n)
    if nrm < 1e-14:
        return None
    n /= nrm
    if np.dot(n, facet.normal) < 0:
        n = -n
    return n


def verify(r, label):
    facets = generate_facets(r)
    optical = [f for f in facets if not f.is_gap_surface]
    source = r.source.position
    errs = []
    for f in optical:
        for j in range(5):
            for i in range(5):
                if i == 0 and f.index_u == 0 or i == 4 and f.index_u == r.grid.n_u - 1:
                    pass
                u = i / 4.0
                v = j / 4.0
                n = surf_normal(f, u, v)
                if n is None:
                    continue
                p = eval_surface(f.ctrl, f.degree_u, f.degree_v, f.knots_u, f.knots_v, u, v)
                I = p - source
                I /= np.linalg.norm(I)
                R = I - 2.0 * np.dot(I, n) * n
                R /= np.linalg.norm(R)
                ha = np.rad2deg(np.arctan2(R[0], R[2]))
                va = np.rad2deg(np.arcsin(np.clip(R[1], -1, 1)))
                ht, vt = r.spreads.target_angles_on_facet(f.index_u, f.index_v, u, v)
                errs.append((abs(ha - ht), abs(va - vt)))
    errs = np.array(errs)
    x, y, z, su, sv, blocks = eng._build_height_field(r)
    n_u, n_v = r.grid.n_u, r.grid.n_v
    wu = max([np.max(np.abs(blocks[(iu, iv)][:, -1] - blocks[(iu + 1, iv)][:, 0]))
              for iv in range(n_v) for iu in range(n_u - 1)] + [0.0])
    wv = max([np.max(np.abs(blocks[(iu, iv)][-1, :] - blocks[(iu, iv + 1)][0, :]))
              for iu in range(n_u) for iv in range(n_v - 1)] + [0.0])
    print(f"{label:26s} NURBS angle err: H mean={errs[:,0].mean():5.2f} max={errs[:,0].max():5.2f} "
          f"| V mean={errs[:,1].mean():5.2f} max={errs[:,1].max():5.2f} "
          f"| borders U={wu:.4f} V={wv:.4f}")


if __name__ == "__main__":
    verify(build(), "4x4 default")
    verify(build(1, 1), "1x1 facet")
    verify(build(1, 3), "1x3 facets")
    verify(build(3, 1), "3x1 facets")
    r = build()
    r.gaps.size_u = r.gaps.size_v = 0.0
    r.gaps.surface_mode = GapSurfaceMode.EMPTY
    verify(r, "4x4 no-gap 0.0")
    print("OK")
