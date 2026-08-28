"""
Gaps configuration
Aligned with LucidShape Gaps dialog (p.54–59).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from .enums import GapType, GapSurfaceMode, DraftDirection


@dataclass
class SingleGapSetting:
    """Settings for one directed gap (e.g. H-1-2 or V-2-3)."""
    gap_type: GapType = GapType.GAP
    surface_mode: GapSurfaceMode = GapSurfaceMode.EMPTY
    size_xy: float = 0.5            # gap size in X/Y [mm]
    size_z: float = 0.0             # extra Z step (used by step-back)
    draft_enabled: bool = False
    draft_direction: DraftDirection = DraftDirection.CENTER
    draft_angle: float = 5.0        # degrees
    draft_height: float = 0.0
    radius_groove: float = 0.0
    radius_tip: float = 0.0
    tangent_length: float = 0.1     # for S-shape


@dataclass
class GapsConfig:
    """
    Gaps configuration for a block.

    v1 supports the common case "all gaps same".
    Per-gap overrides are stored in the optional dicts for future UI.
    """
    enabled: bool = True
    all_gaps_same: bool = True

    # Uniform settings (used when all_gaps_same == True)
    gap_type: GapType = GapType.GAP
    surface_mode: GapSurfaceMode = GapSurfaceMode.EMPTY
    size_u: float = 0.5             # horizontal gap [mm]
    size_v: float = 0.5             # vertical gap [mm]
    size_z: float = 0.0             # Z step-back [mm]
    draft_enabled: bool = False
    draft_direction: DraftDirection = DraftDirection.CENTER
    draft_angle: float = 5.0

    # Future: per-gap overrides keyed by "H-1-2", "V-2-3" ...
    horizontal_gaps: Dict[str, SingleGapSetting] = field(default_factory=dict)
    vertical_gaps: Dict[str, SingleGapSetting] = field(default_factory=dict)

    def _gap_size(self, size: float) -> float:
        if not self.enabled or self.gap_type in (
            GapType.NO_GAP,
            GapType.STEP_BACK_NO_GAP,
        ):
            return 0.0
        return size

    def effective_gap_u(self) -> float:
        return self._gap_size(self.size_u)

    def effective_gap_v(self) -> float:
        return self._gap_size(self.size_v)

    def effective_step_z(self) -> float:
        """Z offset applied between consecutive rows/columns for step-back types."""
        if not self.enabled:
            return 0.0
        if self.gap_type in (GapType.STEP_BACK, GapType.STEP_BACK_NO_GAP):
            return self.size_z
        return 0.0

