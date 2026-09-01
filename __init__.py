"""
mf_reflector – Python implementation of LucidShape MacroFocal Reflector core.

Version: 0.9.6 (redesigned from official FunGeo MacroFocal 2024.09 documentation)
"""

__version__ = "0.9.6"

from .models import (
    MFReflector,
    PointSource,
    GridLayout,
    GapsConfig,
    SpreadsConfig,
    Facet,
    GridType,
    GapType,
    LightTargetType,
    EdgeRayMode,
)
from .geometry import generate_facets, facets_to_mesh, export_stl, export_obj

__all__ = [
    "MFReflector",
    "PointSource",
    "GridLayout",
    "GapsConfig",
    "SpreadsConfig",
    "Facet",
    "GridType",
    "GapType",
    "LightTargetType",
    "EdgeRayMode",
    "generate_facets",
    "facets_to_mesh",
    "export_stl",
    "export_obj",
]
