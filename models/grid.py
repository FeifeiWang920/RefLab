# SPDX-License-Identifier: MIT
"""
Base Grid / Grid Layout
Supports both uniform size and variable width_deltas / height_deltas (params.py style).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence
import numpy as np

from .enums import GridType, GridShapeMode, EdgeShape


def _pad_deltas(vals: Sequence[float], n: int, default: float) -> List[float]:
    v = list(vals) if vals else []
    if not v:
        return [default] * n
    if len(v) >= n:
        return list(v[:n])
    return v + [v[-1]] * (n - len(v))


@dataclass
class GridLayout:
    """
    Classic grid layout.

    Two ways to define facet sizes:
      1. Uniform: size_u / size_v  (legacy)
      2. Variable: width_deltas / height_deltas  (preferred, matches params.py)

    When width_deltas is non-empty it takes priority over size_u.
    """
    grid_type: GridType = GridType.CLASSIC

    n_u: int = 4
    n_v: int = 4

    # Uniform fallback
    size_u: float = 40.0
    size_v: float = 40.0

    # Variable facet sizes (mm); length == n_u / n_v
    width_deltas: List[float] = field(default_factory=list)
    height_deltas: List[float] = field(default_factory=list)

    degree_u: int = 5
    degree_v: int = 5

    # Positioning
    offset_x: float = 0.0          # lower-left X of the aperture
    offset_y: float = 0.0          # lower-left Y
    start_z: float = 0.0           # nominal Z of the base / carrier reference
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))

    # Carrier paraboloid focal length (mm)
    focal: float = 25.0

    # Legacy compatibility
    offset_z: float = 0.0
    offset_xy: np.ndarray = field(default_factory=lambda: np.zeros(2))
    start_point: np.ndarray = field(default_factory=lambda: np.zeros(2))
    use_start_point: bool = True

    # Shape (future)
    shape_mode: GridShapeMode = GridShapeMode.RECTANGLE
    up_edge: EdgeShape = EdgeShape.STRAIGHT
    low_edge: EdgeShape = EdgeShape.STRAIGHT
    left_edge: EdgeShape = EdgeShape.STRAIGHT
    right_edge: EdgeShape = EdgeShape.STRAIGHT
    upper_radii: np.ndarray = field(default_factory=lambda: np.array([70.0, 70.0]))
    lower_angle: float = 0.0
    straight_inner_lines: bool = True
    mirror_u: bool = False
    mirror_v: bool = False

    def __post_init__(self) -> None:
        self.center = np.asarray(self.center, dtype=float).reshape(3)
        self.start_point = np.asarray(self.start_point, dtype=float).reshape(2)
        self.offset_xy = np.asarray(self.offset_xy, dtype=float).reshape(2)
        self.upper_radii = np.asarray(self.upper_radii, dtype=float).reshape(2)

        self.n_u = max(1, int(self.n_u))
        self.n_v = max(1, int(self.n_v))
        self.degree_u = max(1, int(self.degree_u))
        self.degree_v = max(1, int(self.degree_v))
        if self.focal <= 0:
            raise ValueError("focal must be > 0")

        # Normalise deltas
        if self.width_deltas:
            self.width_deltas = _pad_deltas(self.width_deltas, self.n_u, 10.0)
            self.size_u = float(sum(self.width_deltas))
        else:
            self.width_deltas = [self.size_u / self.n_u] * self.n_u

        if self.height_deltas:
            self.height_deltas = _pad_deltas(self.height_deltas, self.n_v, 10.0)
            self.size_v = float(sum(self.height_deltas))
        else:
            self.height_deltas = [self.size_v / self.n_v] * self.n_v

    @property
    def total_facets(self) -> int:
        return self.n_u * self.n_v

    @property
    def total_width(self) -> float:
        return float(sum(self.width_deltas))

    @property
    def total_height(self) -> float:
        return float(sum(self.height_deltas))

    def node_x_coords(self) -> np.ndarray:
        """X coordinates of the (n_u+1) vertical grid lines (aperture plane)."""
        xs = [self.offset_x]
        for w in self.width_deltas:
            xs.append(xs[-1] + w)
        return np.asarray(xs, dtype=float)

    def node_y_coords(self) -> np.ndarray:
        """Y coordinates of the (n_v+1) horizontal grid lines."""
        ys = [self.offset_y]
        for h in self.height_deltas:
            ys.append(ys[-1] + h)
        return np.asarray(ys, dtype=float)

    def facet_pitch_u(self, gap_u: float = 0.0) -> float:
        """Average usable width (legacy helper)."""
        total_gap = gap_u * max(self.n_u - 1, 0)
        usable = self.size_u - total_gap
        return usable / self.n_u if self.n_u > 0 else 0.0

    def facet_pitch_v(self, gap_v: float = 0.0) -> float:
        total_gap = gap_v * max(self.n_v - 1, 0)
        usable = self.size_v - total_gap
        return usable / self.n_v if self.n_v > 0 else 0.0
