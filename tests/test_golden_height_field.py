"""Golden-master regression test for the height-field solver.

The .npz baseline is captured with the pre-optimisation engine (see
golden_height_field.py).  Any refactor of the solver must reproduce the
same height fields to within 1e-8 mm; otherwise this test fails and the
optical behaviour has drifted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

try:
    import pytest
except ImportError:  # 直跑 __main__ 时允许无 pytest
    pytest = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.golden_height_field import GOLDEN_PATH, case_matrix
from geometry.engine import _build_height_field

TOL = 1e-8


def _load_golden() -> dict:
    if not GOLDEN_PATH.exists():
        raise FileNotFoundError(
            f"golden baseline missing: {GOLDEN_PATH}\n"
            "run `python tests/golden_height_field.py` with the reference engine"
        )
    with np.load(GOLDEN_PATH) as data:
        return {k: data[k] for k in data.files}


if pytest is not None:

    @pytest.fixture(scope="module")
    def golden() -> dict:
        return _load_golden()


def test_height_fields_match_baseline(golden):
    for name, refl in case_matrix().items():
        x_coords, y_coords, z, _su_g, _sv_g, blocks = _build_height_field(refl)
        assert np.max(np.abs(x_coords - golden[f"{name}__x"])) < TOL, name
        assert np.max(np.abs(y_coords - golden[f"{name}__y"])) < TOL, name
        assert np.max(np.abs(z - golden[f"{name}__z"])) < TOL, name
        # 面片块数量一致
        n_blocks = sum(1 for k in golden if k.startswith(f"{name}__b_"))
        assert len(blocks) == n_blocks, name
        for (iu, iv), blk in blocks.items():
            ref = golden[f"{name}__b_{iu}_{iv}"]
            delta = float(np.max(np.abs(blk - ref)))
            assert delta < TOL, f"{name} facet ({iu},{iv}) max|dz|={delta:.3e}"


if __name__ == "__main__":
    test_height_fields_match_baseline(_load_golden())
    print("OK – height fields match golden baseline.")
