# SPDX-License-Identifier: MIT
"""Headless smoke tests for the tabbed Tk UI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tk = pytest.importorskip("tkinter", reason="tkinter is unavailable; UI smoke tests skipped")

from models import GapType, PatchContinuity, PatchFitMethod, SolveMethod
from ui.main_window import MFReflectorApp

# 主题与字体断言依赖 Windows 系统主题栈（Vista/sv-ttk + Microsoft YaHei UI）
win_only = pytest.mark.skipif(
    sys.platform != "win32",
    reason="sun-valley theme / YaHei font assertions are Windows-specific",
)


def test_tabbed_ui_and_dialogs():
    root = tk.Tk()
    root.withdraw()
    app = MFReflectorApp(root)
    root.update_idletasks()

    tabs = [app.notebook.tab(tab_id, "text") for tab_id in app.notebook.tabs()]
    assert tabs == ["设计", "光学", "构造"]

    app._open_fstart_dialog()
    assert app._fstart_dialog is not None and app._fstart_dialog.winfo_exists()
    app._fstart_dialog.destroy()
    root.update_idletasks()

    reflector = app._collect()
    assert reflector.gaps.gap_type == GapType.GAP
    assert reflector.solve == SolveMethod.V_FIRST
    assert reflector.patch_fit_method == PatchFitMethod.APPROXIMATE
    assert reflector.fit_patch_continuity_u == PatchContinuity.POINT
    assert reflector.calculation_start_u is None
    assert reflector.calculation_start_v is None
    assert reflector.use_base_curve_from_neighbor is False
    assert reflector.z_step_u == 0.0
    assert reflector.z_step_v == 0.0
    assert reflector.spreads.uniform_intensity is False
    assert reflector.source.axis is None
    app.src_axis_auto.set(False)
    app.src_axis_x.set("1")
    app.src_axis_y.set("0")
    app.src_axis_z.set("0")
    reflector = app._collect()
    assert reflector.source.axis is not None
    assert abs(float(reflector.source.axis[0]) - 1.0) < 1e-12
    assert abs(float(reflector.source.axis[1])) < 1e-12
    assert abs(float(reflector.source.axis[2])) < 1e-12

    root.destroy()


@win_only
def test_visual_theme_and_primary_button():
    root = tk.Tk()
    root.withdraw()
    app = MFReflectorApp(root)
    root.update_idletasks()

    theme = root.tk.call("ttk::style", "theme", "use")
    assert "sun-valley" in str(theme), f"expected sun-valley theme, got {theme}"
    assert str(app.btn_generate.cget("style")) == "Accent.TButton"
    status_relief = str(app.status.cget("relief"))
    assert status_relief in ("", "flat"), f"status bar should be flat, got {status_relief!r}"

    import tkinter.font as tkfont
    from ui.main_window import UI_FONT_SIZE, SV_TTK_FONTS
    for name in ("TkDefaultFont", "TkTextFont"):
        f = tkfont.nametofont(name)
        assert f.cget("size") >= UI_FONT_SIZE, (
            f"{name} should be >= {UI_FONT_SIZE}pt, got {f.cget('size')}"
        )
        assert "yahei" in str(f.cget("family")).lower(), (
            f"{name} family should be Microsoft YaHei, got {f.cget('family')}"
        )
    # ttk 控件实际使用的字体（sv-ttk 用自己的 SunValleyBodyFont，必须一并覆盖）
    style_font = root.tk.call("ttk::style", "lookup", "TLabel", "-font")
    sf = tkfont.Font(root=root, name=str(style_font), exists=True)
    assert str(style_font) in SV_TTK_FONTS, f"unexpected ttk font: {style_font}"
    assert sf.cget("size") == SV_TTK_FONTS[str(style_font)], (
        f"ttk font size drifted: expected {SV_TTK_FONTS[str(style_font)]}, got {sf.cget('size')}"
    )
    assert "yahei" in str(sf.cget("family")).lower(), (
        f"ttk TLabel font family should be Microsoft YaHei, got {sf.cget('family')}"
    )

    root.destroy()


def test_parse_deltas_and_aperture_bounds():
    """UI 纯函数：尺寸列表解析与孔径范围。"""
    from ui.app_state import parse_deltas

    assert parse_deltas("10,20,30", 4) == [10.0, 20.0, 30.0, 30.0]  # 不足重复末值
    assert parse_deltas("10; 20", 2) == [10.0, 20.0]  # 分号等价逗号
    assert parse_deltas("", 2) == [10.0, 10.0]  # 空 → fallback
    assert parse_deltas("1,2,3,4,5", 2) == [1.0, 2.0]  # 超出截断

    root = tk.Tk()
    root.withdraw()
    app = MFReflectorApp(root)
    root.update_idletasks()
    # 默认网格：offset ±20、4×10 mm → 孔径 [-20, 20]²
    assert app._aperture_bounds() == (-20.0, 20.0, -20.0, 20.0)
    root.destroy()


def wait_generation(app, timeout: float = 120.0) -> None:
    """泵事件循环直到后台生成结束（测试辅助，从生产类移出）。"""
    import time as _time

    deadline = _time.time() + timeout
    while app._gen_thread is not None and app._gen_thread.is_alive():
        if _time.time() >= deadline:
            raise TimeoutError("generation did not finish in time")
        try:
            app.root.update()
        except tk.TclError:
            break
        _time.sleep(0.01)
    # 再泵几轮让 after 回调把结果与按钮状态落地
    for _ in range(20):
        try:
            app.root.update()
        except tk.TclError:
            break
        if app._gen_thread is None:
            break
        _time.sleep(0.01)


def test_generate_runs_in_background():
    root = tk.Tk()
    root.withdraw()
    app = MFReflectorApp(root)
    root.update_idletasks()

    app.on_apply()
    # on_apply 应立即返回（未阻塞），且生成期间按钮禁用
    assert app._gen_thread is not None and app._gen_thread.is_alive()
    assert str(app.btn_generate.cget("state")) == "disabled"
    assert str(app.btn_catia.cget("state")) == "disabled"

    wait_generation(app)
    assert app.reflector is not None and app.reflector.is_generated()
    assert app._gen_thread is None
    assert str(app.btn_generate.cget("state")) in ("normal", "")
    assert str(app.btn_catia.cget("state")) in ("normal", "")
    assert "生成" in str(app.status.cget("text"))

    root.destroy()


def test_send_catia_runs_in_background(monkeypatch):
    """发送到 CATIA 必须在工作线程执行，期间按钮禁用，完成后恢复。"""
    import time as _time
    from types import SimpleNamespace
    from catia.bridge import CatiaState, CatiaStatus
    import ui.main_window as ui_main

    root = tk.Tk()
    root.withdraw()
    app = MFReflectorApp(root)
    root.update_idletasks()
    app.on_apply()
    wait_generation(app)

    calls = []
    monkeypatch.setattr(
        ui_main, "detect_catia",
        lambda: CatiaStatus(state=CatiaState.PART_READY, message="mock ready"),
    )

    def fake_export(*a, **k):
        _time.sleep(0.15)
        calls.append("export")
        return 16

    def fake_import(*a, **k):
        calls.append("import")
        return SimpleNamespace(ok=True, message="mock ok")

    monkeypatch.setattr(ui_main, "export_step", fake_export)
    monkeypatch.setattr(ui_main, "import_step_to_active_part", fake_import)

    app.on_send_catia()
    assert app._catia_thread is not None and app._catia_thread.is_alive()
    assert str(app.btn_catia.cget("state")) == "disabled"

    deadline = _time.time() + 30
    while app._catia_thread is not None and _time.time() < deadline:
        root.update()
        _time.sleep(0.01)
    for _ in range(20):
        root.update()
        _time.sleep(0.01)

    assert calls == ["export", "import"]
    assert "mock ok" in str(app.status.cget("text"))
    assert str(app.btn_catia.cget("state")) in ("normal", "")
    root.destroy()


if __name__ == "__main__":
    test_tabbed_ui_and_dialogs()
    test_generate_runs_in_background()
    print("OK – tabbed UI smoke test passed.")
