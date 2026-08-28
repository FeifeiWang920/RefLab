"""
Spreads configuration – LucidShape MF facet spread semantics.

Key rule (per user / LucidShape):
  - An angle list such as H = (-20, 20) or H = (0, 5, 10, 15, 20)
    describes the far-field horizontal spread of *one facet*.
  - Inside that facet the target angle is distributed evenly
    (by normalised parameter / projected area) across the list.
  - Simple two-value form (-20, 20) → linear from -20° to 20°.
  - Multi-value form (-20, -10, 20) → piecewise-linear interpolation
    so equal parameter steps map to equal segments of the angle list.

The same list is applied to every facet unless a per_facet table is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Sequence
import numpy as np

from .enums import LightTargetType, EdgeRayMode


def _parse_angle_list(text_or_list) -> List[float]:
    if text_or_list is None:
        return []
    if isinstance(text_or_list, (list, tuple, np.ndarray)):
        vals = [float(x) for x in text_or_list]
    else:
        parts = [
            p.strip()
            for p in str(text_or_list).replace(";", ",").split(",")
            if p.strip()
        ]
        vals = [float(p) for p in parts] if parts else []
    return vals


def _interp_angle_list(angles: Sequence[float], frac: float) -> float:
    """
    Map frac ∈ [0, 1] evenly onto the angle list (piecewise linear).
    frac is the normalised position across the facet (projected-area proxy).
    """
    if not angles:
        return 0.0
    if len(angles) == 1:
        return float(angles[0])
    frac = float(np.clip(frac, 0.0, 1.0))
    # Equal parameter spacing between list entries
    x = np.linspace(0.0, 1.0, len(angles))
    return float(np.interp(frac, x, np.asarray(angles, dtype=float)))


@dataclass
class SpreadsConfig:
    """
    Far-field spread of each facet (LucidShape style).

    h_angles / v_angles : ordered list of target angles (deg) for ONE facet.
      - (-20, 20)           → linear -20° … 20° across the facet
      - (0, 5, 10, 15, 20) → piecewise, even parameter steps
      - (-20, -10, 20)     → piecewise interpolation

    When lists are empty, fall back to symmetric global_h_deg / global_v_deg.
    """
    light_target: LightTargetType = LightTargetType.FAR_FIELD
    edge_ray: EdgeRayMode = EdgeRayMode.CENTER

    # Per-facet angle lists (applied to every facet by default)
    h_angles: List[float] = field(default_factory=list)
    v_angles: List[float] = field(default_factory=list)

    # Fallback when lists are empty: symmetric total span
    global_h_deg: float = 40.0
    global_v_deg: float = 20.0

    # Optional overrides: [n_v][n_u] of (h_list, v_list) or (hmin,hmax,vmin,vmax)
    per_facet: Optional[List[List[Tuple]]] = None

    # Modifiers
    global_shift_h: float = 0.0
    global_shift_v: float = 0.0
    global_scale_h: float = 1.0
    global_scale_v: float = 1.0

    center_offset: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def __post_init__(self) -> None:
        self.center_offset = np.asarray(self.center_offset, dtype=float).reshape(3)
        self.h_angles = _parse_angle_list(self.h_angles)
        self.v_angles = _parse_angle_list(self.v_angles)
        if len(self.h_angles) < 2:
            half = abs(self.global_h_deg) / 2.0
            self.h_angles = [-half, half]
        if len(self.v_angles) < 2:
            half = abs(self.global_v_deg) / 2.0
            self.v_angles = [-half, half]

    # ------------------------------------------------------------------
    def _lists_for_facet(
        self, i_u: int, i_v: int
    ) -> Tuple[List[float], List[float]]:
        """Return (h_list, v_list) for facet (i_u, i_v)."""
        if self.per_facet is not None:
            entry = self.per_facet[i_v][i_u]
            # Support both (h_list, v_list) and (hmin,hmax,vmin,vmax)
            if len(entry) == 2 and isinstance(entry[0], (list, tuple)):
                return list(entry[0]), list(entry[1])
            if len(entry) == 4 and all(isinstance(x, (int, float)) for x in entry):
                return [float(entry[0]), float(entry[1])], [
                    float(entry[2]),
                    float(entry[3]),
                ]
        return self.h_angles, self.v_angles

    def target_angles_on_facet(
        self,
        i_u: int,
        i_v: int,
        local_u: float,
        local_v: float,
    ) -> Tuple[float, float]:
        """
        Target (h, v) degrees at a point inside facet (i_u, i_v).

        local_u, local_v ∈ [0, 1] are the normalised coordinates
        across the facet (0 = one edge, 1 = opposite edge).
        Mapping is even in parameter (= approximate projected-area
        uniform distribution for a roughly flat facet).
        """
        h_list, v_list = self._lists_for_facet(i_u, i_v)
        h = _interp_angle_list(h_list, local_u)
        v = _interp_angle_list(v_list, local_v)
        h = h * self.global_scale_h + self.global_shift_h
        v = v * self.global_scale_v + self.global_shift_v
        return h, v

    def get_facet_spread(
        self, i_u: int, i_v: int, n_u: int = 1, n_v: int = 1
    ) -> Tuple[float, float, float, float]:
        """
        Overall (h_min, h_max, v_min, v_max) for the facet
        (min/max of its angle lists). Used for Edge-Ray and bookkeeping.
        """
        h_list, v_list = self._lists_for_facet(i_u, i_v)
        h_min, h_max = min(h_list), max(h_list)
        v_min, v_max = min(v_list), max(v_list)
        h_min = h_min * self.global_scale_h + self.global_shift_h
        h_max = h_max * self.global_scale_h + self.global_shift_h
        v_min = v_min * self.global_scale_v + self.global_shift_v
        v_max = v_max * self.global_scale_v + self.global_shift_v
        return h_min, h_max, v_min, v_max
