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
    assert tabs == [
        "Grid & Source",
        "Gaps",
        "Solver",
        "Patch Fit",
        "Spreads",
    ]

    app._open_gap_dialog()
    assert app._gap_dialog is not None and app._gap_dialog.winfo_exists()
    app._gap_dialog.destroy()
    root.update_idletasks()

    app._open_fstart_dialog()
    assert app._fstart_dialog is not None and app._fstart_dialog.winfo_exists()
    app._fstart_dialog.destroy()
    root.update_idletasks()

    reflector = app._collect()
    assert reflector.gaps.gap_type == GapType.GAP
    assert reflector.solve == SolveMethod.V_FIRST
    assert reflector.patch_fit_method == PatchFitMethod.EXACT
    assert reflector.fit_patch_continuity_u == PatchContinuity.POINT
    assert reflector.calculation_start_u is None
    assert reflector.calculation_start_v is None
    assert reflector.use_base_curve_from_neighbor is True
    assert reflector.z_step_u == 0.0
    assert reflector.z_step_v == 0.0

    root.destroy()


if __name__ == "__main__":
    test_tabbed_ui_and_dialogs()
    print("OK – tabbed UI smoke test passed.")
