# SPDX-License-Identifier: MIT
"""
Enumerations aligned with LucidShape FunGeo MacroFocal 2024.09 terminology.
"""

from __future__ import annotations

from enum import Enum


class GridType(Enum):
    CLASSIC = "Classic"
    RECTANGLE = "Rectangle"
    ZONAL = "Zonal"
    POLAR = "Polar"
    GLOBE = "Globe"
    FOUR_BORDER_CURVE = "4 Border Curve"
    GRID_OF_CURVES = "Grid of Curves"
    SELECT_NURBS = "Select NURBS"


class GridShapeMode(Enum):
    RECTANGLE = "rectangle"
    UP_DOWN_SHAPED = "up/down shaped"
    LEFT_RIGHT_SHAPED = "left/right shaped"


class EdgeShape(Enum):
    STRAIGHT = "straight"
    ROUND = "round"
    SLANT = "slant"


class GapType(Enum):
    """缝隙模式。UI 暴露 GAP / NO_GAP；STEP_BACK* 仅可通过 API 使用。"""
    GAP = "gap"
    NO_GAP = "no gap"
    STEP_BACK = "step back"
    STEP_BACK_NO_GAP = "step back + no gap"


class GapSurfaceMode(Enum):
    """缝隙面选项。UI 暴露 SURFACE/EMPTY（gap 模式）与 NEW_BORDER/OLD_BORDER/AVERAGE（no_gap）；S_SHAPE/INTERSECTION 仅 API。"""
    SURFACE = "surface"
    EMPTY = "empty"
    S_SHAPE = "S shape surface"
    AVERAGE = "average"
    NEW_BORDER = "new border"
    OLD_BORDER = "old border"
    INTERSECTION = "intersection"


class DraftDirection(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class LightTargetType(Enum):
    """远场目标类型。引擎仅实现 FAR_FIELD，其余取值在求解入口显式报错；UI 亦只暴露 FAR_FIELD。"""
    FAR_FIELD = "far field"
    NEAR_Z_PLANE = "near Z-plane"
    NEAR_FREE_PLANE = "near free plane"
    VIRTUAL_Z_PLANE = "virtual Z-plane"
    VIRTUAL_FREE_PLANE = "virt. free plane"
    SPHERE = "sphere"
    TORUS_UV = "torus UV"
    CYLINDER_U = "cylinder U"
    CYLINDER_V = "cylinder V"
    FLAT = "Flat"
    SIMPLE_SPREAD = "simple spread"


class EdgeRayMode(Enum):
    CENTER = "center"
    MAX = "max edge ray"
    MIN = "min edge ray"


class PatchFitMethod(Enum):
    EXACT = "exact"
    APPROXIMATE = "approximation"
    APPROXIMATE_KEEP_SIZE = "approximation + keep size"


class SolveMethod(Enum):
    """Integration order for normal-field integration."""
    V_FIRST = "v-first"
    U_FIRST = "u-first"


class PatchContinuity(Enum):
    POINT = "point"
    TANGENT = "tangent"
    CURVATURE = "curvature"
