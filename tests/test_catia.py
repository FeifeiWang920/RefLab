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


def test_import_proceeds_when_active_doc_is_not_part(monkeypatch, tmp_path):
    """NOT_PART / NO_ACTIVE_DOC 不得在入口被拒——承诺的自动新建 CATPart 必须被执行。"""
    import catia.bridge as bridge

    class _FakeDoc:
        Name = "NewPart.CATPart"

        class _Part:
            pass

        Part = _Part()

    class _FakeDocuments:
        Count = 0

        def __init__(self):
            self.added = None

        def Add(self, kind):
            self.added = kind
            return _FakeDoc()

    docs = _FakeDocuments()

    class _FakeCatia:
        Documents = docs

    monkeypatch.setattr(
        bridge, "detect_catia",
        lambda: CatiaStatus(state=CatiaState.NOT_PART, message="not part"),
    )
    monkeypatch.setattr(bridge, "_get_catia", lambda allow_launch=False: _FakeCatia())

    def _stop(catia, stp_path):
        raise RuntimeError("STOP-marker")

    monkeypatch.setattr(bridge, "_convert_step_to_catpart", _stop)

    stp = tmp_path / "reflector.stp"
    stp.write_text("stub", encoding="utf-8")
    status = bridge.import_step_to_active_part(stp)

    # 未在入口被拒（否则 message 是 detect 的 "not part"）；
    # 自动建 Part 已执行，且流程推进到了 STEP 转换。
    assert docs.added == "Part"
    assert "STOP-marker" in status.message


if __name__ == "__main__":
    test_detect()
