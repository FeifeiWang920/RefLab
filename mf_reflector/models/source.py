"""Light source models (LucidShape Source dialog – simplified for point source)."""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


@dataclass(frozen=True)
class PointSource:
    """
    Ideal point light source used by MacroFocal calculation.

    Full LucidShape supports cylinder (H7), filament, multi-chip LED etc.
    This class is the minimal contract required by the geometry engine.
    """
    position: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 30.0]))
    name: str = "PointSource"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "position",
            np.asarray(self.position, dtype=float).reshape(3)
        )

    @classmethod
    def default(cls) -> "PointSource":
        """Common starting point: 30 mm above origin on optical axis."""
        return cls(position=np.array([0.0, 0.0, 30.0]), name="DefaultPointSource")

    def __repr__(self) -> str:
        p = self.position
        return f"PointSource(name={self.name!r}, pos=[{p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f}])"
