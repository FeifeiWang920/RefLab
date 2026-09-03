# SPDX-License-Identifier: MIT
"""CATIA bridge smoke test (safe on machines without CATIA)."""

from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catia import detect_catia, is_available, CatiaStatus
from catia.bridge import CatiaState


def test_detect():
    print(f"COM available : {is_available()}")
    st = detect_catia()
    print(f"State         : {st.state.value}")
    print(f"Message       : {st.message}")
    print(f"Document      : {st.document_name or '(none)'}")
    print(f"Version       : {st.catia_version or '(unknown)'}")
    assert isinstance(st, CatiaStatus)
    assert st.state in list(CatiaState)
    # On Linux CI we expect UNAVAILABLE
    if not is_available():
        assert st.state == CatiaState.UNAVAILABLE
    print("OK – CATIA detect() completed without error.")


if __name__ == "__main__":
    test_detect()
