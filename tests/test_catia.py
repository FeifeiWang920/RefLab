# SPDX-License-Identifier: MIT
"""CATIA bridge smoke test (safe on machines without CATIA)."""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

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


needs_pywin32 = pytest.mark.skipif(
    not is_available(), reason="pywin32 unavailable (non-Windows or not installed)"
)


@needs_pywin32
def test_detect_catia_never_launches(monkeypatch):
    """探测（detect_catia）只允许 GetActiveObject；Dispatch 拉起 CATIA 只能发生在显式发送。"""
    calls = []

    def fake_get_active_object(_name):
        calls.append("GetActiveObject")
        raise RuntimeError("no running CATIA (test stub)")

    def fake_dispatch(_name):
        calls.append("Dispatch")
        return object()

    monkeypatch.setattr("win32com.client.GetActiveObject", fake_get_active_object)
    monkeypatch.setattr("win32com.client.Dispatch", fake_dispatch)

    status = detect_catia()

    assert status.state == CatiaState.NOT_RUNNING
    assert calls == ["GetActiveObject"], f"探测路径不得调用 Dispatch，实际: {calls}"


if __name__ == "__main__":
    test_detect()
