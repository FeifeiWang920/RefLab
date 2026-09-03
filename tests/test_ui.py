"""Headless smoke tests for the tabbed Tk UI."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import tkinter as tk
except ImportError:
    raise SystemExit("tkinter is unavailable; UI smoke test skipped")

from models import GapType, PatchContinuity, PatchFitMethod, SolveMethod
from ui.main_window import MFReflectorApp


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
    from ui.main_window import UI_FONT_FAMILY, UI_FONT_SIZE, SV_TTK_FONTS
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

    app._wait_for_generation(timeout=120)
    assert app.reflector is not None and app.reflector.is_generated()
    assert app._gen_thread is None
    assert str(app.btn_generate.cget("state")) in ("normal", "")
    assert str(app.btn_catia.cget("state")) in ("normal", "")
    assert "生成" in str(app.status.cget("text"))

    root.destroy()


if __name__ == "__main__":
    test_tabbed_ui_and_dialogs()
    test_generate_runs_in_background()
    print("OK – tabbed UI smoke test passed.")
