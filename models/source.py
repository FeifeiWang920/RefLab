# SPDX-License-Identifier: MIT
"""Light source models (LucidShape Source dialog – simplified for point source)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass(frozen=True)
class PointSource:
    """
    Point light source used by MacroFocal calculation.

    pattern:
      - "lambertian": I(θ) = I0 · cos^n(θ), θ from the emission axis
      - "isotropic":  I(θ) = I0
    axis:
      Emission direction. None = automatic (source → reflector centre).
    lambert_n:
      Lambertian order. 1 = ideal LED / Lambertian emitter.
    """
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 30.0]))
    name: str = "PointSource"
    pattern: str = "lambertian"
    axis: Optional[np.ndarray] = None
    lambert_n: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "position",
            np.asarray(self.position, dtype=float).reshape(3),
        )
        if self.axis is not None:
            axis = np.asarray(self.axis, dtype=float).reshape(3)
            n = float(np.linalg.norm(axis))
            object.__setattr__(self, "axis", axis / n if n > 1e-12 else None)
        object.__setattr__(self, "pattern", str(self.pattern).strip().lower() or "lambertian")
        object.__setattr__(self, "lambert_n", float(max(0.0, self.lambert_n)))

    @classmethod
    def default(cls) -> "PointSource":
        """Common starting point: 30 mm above origin on optical axis."""
        return cls(position=np.array([0.0, 0.0, 30.0]), name="DefaultPointSource")

    def __repr__(self) -> str:
        p = self.position
        if self.axis is None:
            axis_s = "auto"
        else:
            a = self.axis
            axis_s = f"[{a[0]:.3f}, {a[1]:.3f}, {a[2]:.3f}]"
        return (
            f"PointSource(name={self.name!r}, pos=[{p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}], "
            f"axis={axis_s}, pattern={self.pattern!r}, n={self.lambert_n:.2f})"
        )
