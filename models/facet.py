# SPDX-License-Identifier: MIT
"""Single MacroFocal facet – supports planar corners and NURBS patch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class Facet:
    """
    One optical facet of a RefLab reflector.

    Geometry can be represented as:
      - corners (4 points) for quick preview
      - denser points grid
      - full NURBS (ctrl net + degrees + knots) when available
    """
    index_u: int
    index_v: int
    center: np.ndarray
    normal: np.ndarray
    size_u: float
    size_v: float
    corners: np.ndarray                 # (4, 3)

    h_min: float = 0.0
    h_max: float = 0.0
    v_min: float = 0.0
    v_max: float = 0.0
    z_step: float = 0.0
    patch_index_u: int = 0
    patch_index_v: int = 0

    # Dense sampling (fallback mesh)
    points: Optional[np.ndarray] = field(default=None, repr=False)
    samples_u: int = 2
    samples_v: int = 2

    # NURBS representation
    is_nurbs: bool = False
    ctrl: Optional[np.ndarray] = field(default=None, repr=False)   # (nv, nu, 3)
    degree_u: int = 1
    degree_v: int = 1
    knots_u: Optional[np.ndarray] = field(default=None, repr=False)
    knots_v: Optional[np.ndarray] = field(default=None, repr=False)

    # Gap connector flag (True for gap-surface patches)
    is_gap_surface: bool = False

    def __post_init__(self) -> None:
        self.center = np.asarray(self.center, dtype=float).reshape(3)
        self.normal = np.asarray(self.normal, dtype=float).reshape(3)
        self.corners = np.asarray(self.corners, dtype=float).reshape(4, 3)
        nrm = np.linalg.norm(self.normal)
        if nrm > 1e-12:
            self.normal = self.normal / nrm
        if self.points is not None:
            self.points = np.asarray(self.points, dtype=float)
        if self.ctrl is not None:
            self.ctrl = np.asarray(self.ctrl, dtype=float)

    @property
    def area(self) -> float:
        return self.size_u * self.size_v

    def mesh_points(self) -> np.ndarray:
        """Return points used for triangle mesh export."""
        if self.is_nurbs and self.ctrl is not None:
            from geometry.nurbs import sample_surface
            return sample_surface(
                self.ctrl, self.degree_u, self.degree_v,
                self.knots_u, self.knots_v,
                self.samples_u, self.samples_v,
            )
        if self.points is not None and len(self.points) > 0:
            return self.points
        return self.corners




