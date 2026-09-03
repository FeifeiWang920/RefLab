# SPDX-License-Identifier: MIT
"""F.Start 对话框：网格起点 / 面片计算起点 / 边界与 Z 步长（草稿副本，Apply 写回）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def open_fstart_dialog(app) -> None:
    """打开（或聚焦已存在的）F.Start 对话框。app 为 MFReflectorApp 实例。"""
    if app._fstart_dialog is not None and app._fstart_dialog.winfo_exists():
        app._fstart_dialog.lift()
        app._fstart_dialog.focus_force()
        return

    dialog = tk.Toplevel(app.root)
    app._fstart_dialog = dialog
    dialog.title("F.Start")
    dialog.transient(app.root)
    dialog.minsize(app._px(460), app._px(420))
    dialog.geometry(f"{app._px(520)}x{app._px(620)}")
    dialog.resizable(True, True)
    dialog.grab_set()

    d_use_start = tk.BooleanVar(value=app.use_start_point.get())
    d_start_x = tk.StringVar(value=app.start_x.get())
    d_start_y = tk.StringVar(value=app.start_y.get())
    d_start_auto = tk.BooleanVar(value=app.start_auto.get())
    d_calc_u = tk.StringVar(value=app.calc_start_u.get())
    d_calc_v = tk.StringVar(value=app.calc_start_v.get())
    d_ref_u = tk.StringVar(value=app.reference_u.get())
    d_ref_v = tk.StringVar(value=app.reference_v.get())
    d_neighbor = tk.BooleanVar(value=app.use_neighbor_curve.get())
    d_z_u = tk.StringVar(value=app.z_step_u.get())
    d_z_v = tk.StringVar(value=app.z_step_v.get())
    status = tk.StringVar(value="Not applied — click Apply to send into Generate.")

    def apply_fstart() -> bool:
        try:
            sx = float(d_start_x.get())
            sy = float(d_start_y.get())
            cu = float(d_calc_u.get())
            cv = float(d_calc_v.get())
            ru = float(d_ref_u.get())
            rv = float(d_ref_v.get())
            zu = float(d_z_u.get())
            zv = float(d_z_v.get())
        except ValueError:
            app._user_error(
                "F.Start",
                "All numeric fields must be valid numbers.",
                parent=dialog,
            )
            return False
        if d_use_start.get():
            try:
                x0, x1, y0, y1 = app._aperture_bounds()
            except Exception as exc:
                app._user_error("F.Start", f"Cannot read the grid: {exc}", parent=dialog)
                return False
            pad = 1e-9
            if not (x0 - pad <= sx <= x1 + pad and y0 - pad <= sy <= y1 + pad):
                app._user_error(
                    "F.Start",
                    f"Start ({sx:.3f}, {sy:.3f}) is outside the aperture\n"
                    f"X {x0:.1f}…{x1:.1f}, Y {y0:.1f}…{y1:.1f}.",
                    parent=dialog,
                )
                return False
        app.use_start_point.set(d_use_start.get())
        app.start_x.set(f"{sx:g}")
        app.start_y.set(f"{sy:g}")
        app.start_auto.set(d_start_auto.get())
        app.calc_start_u.set(f"{cu:g}")
        app.calc_start_v.set(f"{cv:g}")
        app.reference_u.set(f"{ru:g}")
        app.reference_v.set(f"{rv:g}")
        app.use_neighbor_curve.set(d_neighbor.get())
        app.z_step_u.set(f"{zu:g}")
        app.z_step_v.set(f"{zv:g}")
        app._refresh_fstart_summary()
        if d_use_start.get():
            status.set(f"Applied — start ({sx:g}, {sy:g}). Generate to rebuild.")
        else:
            status.set("Applied — global start off, using U/V. Generate to rebuild.")
        return True

    app._dialog_action_bar(dialog, apply_fstart, status)

    body = ttk.Frame(dialog, padding=(12, 12, 12, 0))
    body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    body.columnconfigure(0, weight=1)

    grid_group = ttk.LabelFrame(body, text="Grid Start Point", padding=8)
    grid_group.grid(row=0, column=0, sticky=tk.EW)
    ttk.Checkbutton(
        grid_group, text="使用全局起点", variable=d_use_start
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
    app._add_entry(grid_group, "Start X", d_start_x, 1, unit="mm")
    app._add_entry(grid_group, "Start Y", d_start_y, 2, unit="mm")
    try:
        x0, x1, y0, y1 = app._aperture_bounds()
        bounds = (
            f"须落在当前孔径内：X {x0:.1f}…{x1:.1f}，Y {y0:.1f}…{y1:.1f}。"
            f"中心 ({0.5 * (x0 + x1):.1f}, {0.5 * (y0 + y1):.1f})。"
        )
    except Exception:
        bounds = "须落在设计页的孔径范围内。"
    ttk.Label(grid_group, text=bounds, wraplength=app._px(450), justify=tk.LEFT).grid(
        row=3, column=0, columnspan=3, sticky=tk.W, pady=(2, 0)
    )

    calc_group = ttk.LabelFrame(body, text="Facet Calculation Start", padding=8)
    calc_group.grid(row=1, column=0, sticky=tk.EW, pady=(10, 0))
    ttk.Checkbutton(
        calc_group, text="自动（使用参考点）", variable=d_start_auto
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
    app._add_entry(calc_group, "Start U", d_calc_u, 1)
    app._add_entry(calc_group, "Start V", d_calc_v, 2)
    app._add_entry(calc_group, "Reference U", d_ref_u, 3)
    app._add_entry(calc_group, "Reference V", d_ref_v, 4)

    neighbor_group = ttk.LabelFrame(body, text="Boundary & Z Steps", padding=8)
    neighbor_group.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
    ttk.Checkbutton(
        neighbor_group, text="使用邻边基线", variable=d_neighbor
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
    app._add_entry(neighbor_group, "Z step U", d_z_u, 1, unit="mm")
    app._add_entry(neighbor_group, "Z step V", d_z_v, 2, unit="mm")
    ttk.Label(
        neighbor_group,
        text="关：只在参考点对齐，光学展开保持设定范围。开：共享边水密，接缝附近光学会弯。",
        wraplength=app._px(450),
        justify=tk.LEFT,
    ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

    dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
