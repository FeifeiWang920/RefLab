# SPDX-License-Identifier: MIT
"""Domain models for MacroFocal Reflector."""

from .enums import (
    GridType,
    GridShapeMode,
    EdgeShape,
    GapType,
    GapSurfaceMode,
    DraftDirection,
    LightTargetType,
    EdgeRayMode,
    PatchFitMethod,
    PatchContinuity,
    SolveMethod,
)
from .source import PointSource
from .grid import GridLayout
from .gaps import GapsConfig, SingleGapSetting
from .spreads import SpreadsConfig
from .facet import Facet
from .reflector import MFReflector

__all__ = [
    "GridType",
    "GridShapeMode",
    "EdgeShape",
    "GapType",
    "GapSurfaceMode",
    "DraftDirection",
    "LightTargetType",
    "EdgeRayMode",
    "PatchFitMethod",
    "PatchContinuity",
    "SolveMethod",
    "PointSource",
    "GridLayout",
    "GapsConfig",
    "SingleGapSetting",
    "SpreadsConfig",
    "Facet",
    "MFReflector",
]

