"""
Precise STEP export of NURBS facets via OpenCascade (OCP / cadquery-ocp).

All optical faces + gap surfaces are sewn into a *single* shell so that
CATIA receives one coherent body instead of many separate faces.
"""

from __future__ import annotations

from typing import List
import numpy as np

from models.facet import Facet


def _knots_to_occt(knots: np.ndarray):
    k = np.round(np.asarray(knots, dtype=float), decimals=10)
    unique, reg = [], []
    for val in k:
        if not unique or abs(val - unique[-1]) > 1e-12:
            unique.append(float(val))
            reg.append(1)
        else:
            reg[-1] += 1
    return unique, reg


def facet_to_bspline_surface(facet: Facet):
    if not facet.is_nurbs or facet.ctrl is None:
        return None

    from OCP.Geom import Geom_BSplineSurface
    from OCP.TColgp import TColgp_Array2OfPnt
    from OCP.TColStd import (
        TColStd_Array1OfReal,
        TColStd_Array1OfInteger,
        TColStd_Array2OfReal,
    )
    from OCP.gp import gp_Pnt

    ctrl = np.asarray(facet.ctrl, dtype=float)
    nv, nu, _ = ctrl.shape
    du, dv = int(facet.degree_u), int(facet.degree_v)
    if nu < du + 1 or nv < dv + 1:
        return None

    poles = TColgp_Array2OfPnt(1, nu, 1, nv)
    for j in range(nv):
        for i in range(nu):
            x, y, z = ctrl[j, i]
            poles.SetValue(i + 1, j + 1, gp_Pnt(float(x), float(y), float(z)))

    u_unique, u_mults = _knots_to_occt(facet.knots_u)
    v_unique, v_mults = _knots_to_occt(facet.knots_v)

    u_knots = TColStd_Array1OfReal(1, len(u_unique))
    u_mult = TColStd_Array1OfInteger(1, len(u_unique))
    for i, (val, m) in enumerate(zip(u_unique, u_mults)):
        u_knots.SetValue(i + 1, val)
        u_mult.SetValue(i + 1, int(m))

    v_knots = TColStd_Array1OfReal(1, len(v_unique))
    v_mult = TColStd_Array1OfInteger(1, len(v_unique))
    for i, (val, m) in enumerate(zip(v_unique, v_mults)):
        v_knots.SetValue(i + 1, val)
        v_mult.SetValue(i + 1, int(m))

    weights = TColStd_Array2OfReal(1, nu, 1, nv)
    for j in range(1, nv + 1):
        for i in range(1, nu + 1):
            weights.SetValue(i, j, 1.0)

    try:
        return Geom_BSplineSurface(
            poles, weights, u_knots, v_knots, u_mult, v_mult, du, dv, False, False
        )
    except Exception:
        try:
            return Geom_BSplineSurface(
                poles, u_knots, v_knots, u_mult, v_mult, du, dv
            )
        except Exception as exc:
            print(f"[step_export] BSpline failed ({facet.index_u},{facet.index_v}): {exc}")
            return None


def facets_to_step(
    facets: List[Facet],
    path: str,
    include_gap_surfaces: bool = True,
    sew: bool = True,
    sew_tolerance: float = 0.05,
) -> int:
    """
    Write NURBS facets to STEP as a *single sewn shell* (one body).

    sew=True  → BRepBuilderAPI_Sewing so CATIA sees one shape
    sew=False → compound of individual faces
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_Sewing
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
    from OCP.BRep import BRep_Builder
    from OCP.Interface import Interface_Static

    faces = []
    for f in facets:
        if f.is_gap_surface and not include_gap_surfaces:
            continue
        surf = facet_to_bspline_surface(f)
        if surf is None:
            continue
        try:
            mk = BRepBuilderAPI_MakeFace(surf, 1e-6)
            if mk.IsDone():
                faces.append(mk.Face())
        except Exception as exc:
            print(f"[step_export] MakeFace failed: {exc}")

    if not faces:
        raise RuntimeError("No valid NURBS faces to export")

    n_faces = len(faces)

    # ---- Sew into one shell (preferred for CATIA) ----
    shape: TopoDS_Shape
    if sew and n_faces > 1:
        sewing = BRepBuilderAPI_Sewing(sew_tolerance)
        for face in faces:
            sewing.Add(face)
        sewing.Perform()
        shape = sewing.SewedShape()
    else:
        builder = BRep_Builder()
        compound = TopoDS_Compound()
        builder.MakeCompound(compound)
        for face in faces:
            builder.Add(compound, face)
        shape = compound

    Interface_Static.SetCVal_s("write.step.schema", "AP203")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    # Write as one solid/shell representation when possible
    try:
        Interface_Static.SetCVal_s("write.surfacecurve.mode", "0")
    except Exception:
        pass

    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    status = writer.Write(path)
    if status != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed with status {status}")

    return n_faces


def export_step(
    facets: List[Facet],
    path: str,
    include_gap_surfaces: bool = True,
    sew: bool = True,
) -> int:
    """Public API – always sew by default so CATIA gets one body."""
    return facets_to_step(
        facets, path,
        include_gap_surfaces=include_gap_surfaces,
        sew=sew,
    )
