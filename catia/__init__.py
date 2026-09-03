# SPDX-License-Identifier: MIT
"""CATIA V5 integration – detect running session and import STEP into active Part."""

from .bridge import (
    CatiaStatus,
    detect_catia,
    import_step_to_active_part,
    is_available,
)

__all__ = [
    "CatiaStatus",
    "detect_catia",
    "import_step_to_active_part",
    "is_available",
]
