# SPDX-License-Identifier: MIT
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


def _count_roots(shape) -> int:
    from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_COMPSOLID, TopAbs_SHELL, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer

    t = shape.ShapeType()
    if t in (TopAbs_SHELL, TopAbs_FACE):
        return 1
    if t not in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
        return 1
    n = 0
    for kind in (TopAbs_SHELL, TopAbs_FACE):
        exp = TopExp_Explorer(shape, kind)
        while exp.More():
            n += 1
            exp.Next()
        if n:
            return n
    return 1


def _pack_faces_as_one_shell(faces):
    """
    Put every face into a single open shell.

    Empty-gap facets do not touch, so Sewing returns a compound of many
    shells.  CATIA then opens that compound as an assembly (one Part per
    face).  One open shell is still a single root shape / single Part.
    """
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Shell

    shell = TopoDS_Shell()
    builder = BRep_Builder()
    builder.MakeShell(shell)
    for face in faces:
        builder.Add(shell, face)
    try:
        shell.Closed(False)
    except Exception:
        pass
    return shell


def _make_single_shape(faces, sew: bool, sew_tolerance: float):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing

    if len(faces) == 1:
        return faces[0]
    if sew:
        sewing = BRepBuilderAPI_Sewing(sew_tolerance)
        try:
            sewing.SetNonManifold(True)
        except Exception:
            pass
        for face in faces:
            sewing.Add(face)
        sewing.Perform()
        sewn = sewing.SewedShape()
        if _count_roots(sewn) <= 1:
            return sewn
    return _pack_faces_as_one_shell(faces)


def _configure_step_writer() -> None:
    from OCP.Interface import Interface_Static

    Interface_Static.SetCVal_s("write.step.schema", "AP203")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    try:
        Interface_Static.SetCVal_s("write.surfacecurve.mode", "0")
    except Exception:
        pass
    # Prevent OCC from emitting a PRODUCT tree (one Part per face).
    for key, val in (
        ("write.step.assembly", 0),
        ("write.step.product.name", "MF_Reflector"),
    ):
        try:
            if isinstance(val, int):
                Interface_Static.SetIVal_s(key, val)
            else:
                Interface_Static.SetCVal_s(key, val)
        except Exception:
            try:
                Interface_Static.SetCVal_s(key, str(val))
            except Exception:
                pass


def facets_to_step(
    facets: List[Facet],
    path: str,
    include_gap_surfaces: bool = True,
    sew: bool = True,
    sew_tolerance: float = 0.05,
) -> int:
    """
    Write NURBS facets to STEP as *one* root shape (one CATIA Part).

    Touching faces (gap = surface) are sewn.  Disjoint faces (gap = empty)
    are packed into a single open shell so CATIA does not create an assembly.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_ReturnStatus

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
    shape = _make_single_shape(faces, sew=sew, sew_tolerance=sew_tolerance)
    _configure_step_writer()

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
