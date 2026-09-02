"""
Tkinter UI for MF Reflector (v0.11 – L1 three-tab layout).

Visual/IA upgrade only. Same parameters, same _collect() semantics.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    HAS_TK = True
except ImportError:
    HAS_TK = False

try:
    import sv_ttk
    HAS_SV_TTK = True
except ImportError:
    HAS_SV_TTK = False

import numpy as np
from models import (
    MFReflector,
    PointSource,
    GridLayout,
    GapsConfig,
    SpreadsConfig,
    GapType,
    GapSurfaceMode,
    EdgeRayMode,
    LightTargetType,
    PatchContinuity,
    PatchFitMethod,
    SolveMethod,
)
from geometry import generate_facets, facets_to_mesh, export_stl, export_obj, export_step
from catia import detect_catia, import_step_to_active_part, CatiaStatus


def _system_dpi() -> float:
    """Logical DPI of the primary display. 96 = 100%."""
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        import ctypes

        return float(ctypes.windll.user32.GetDpiForSystem())  # type: ignore[attr-defined]
    except Exception:
        return 96.0


class MFReflectorApp:
    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("MF Reflector")
        self._dpi = _system_dpi()
        self._scale = max(1.0, self._dpi / 96.0)
        try:
            self.root.tk.call("tk", "scaling", self._dpi / 72.0)
        except tk.TclError:
            pass
        w = int(round(760 * self._scale))
        h = int(round(520 * self._scale))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(int(round(560 * self._scale)), int(round(430 * self._scale)))
        self.reflector: Optional[MFReflector] = None
        self.catia_status: CatiaStatus = detect_catia()
        self._fstart_dialog: Optional["tk.Toplevel"] = None
        self._hint_labels: list = []
        self._design_columns: Optional[tuple] = None
        self._apply_visual_theme()
        self._build_ui()
        self._refresh_catia_status()
        self._refresh_fstart_summary()
        self._sync_axis_state()
        self.root.bind("<Configure>", self._on_root_configure)

    def _px(self, logical: int) -> int:
        return int(round(logical * self._scale))

    # ------------------------------------------------------------------ theme
    def _muted_color(self) -> str:
        """Muted foreground matching the active theme (fallback: fixed grey)."""
        try:
            return self.root.tk.call(
                "ttk::style", "lookup", "TLabel", "-foreground"
            ) or "#5B616B"
        except tk.TclError:
            return "#5B616B"

    def _apply_visual_theme(self) -> None:
        if HAS_SV_TTK:
            sv_ttk.set_theme("light")
        # 全局字体：微软雅黑 12pt（用户指定）。
        # 注意：sv-ttk 给 ttk 控件定义了专用 SunValley*Font（11pt Segoe UI），
        # 只改 TkDefaultFont 等命名字体对 ttk 控件无效，必须一并覆盖。
        import tkinter.font as tkfont

        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            tkfont.nametofont(name).configure(family="Microsoft YaHei UI", size=12)
        sv_fonts = {
            "SunValleyBodyFont": 11,        # 正文：所有标签、输入框、下拉框
            "SunValleyBodyStrongFont": 12,  # 加粗正文：按钮文字
            "SunValleyBodyLargeFont": 12,   # 大号正文
            "SunValleyCaptionFont": 10,     # 小字说明（灰色提示、单位 mm/°）
            "SunValleySubtitleFont": 12,    # 副标题
            "SunValleyTitleFont": 14,       # 标题
            "SunValleyTitleLargeFont": 16,  # 大标题
            "SunValleyDisplayFont": 18,     # 展示级大字
        }
        for name, size in sv_fonts.items():
            try:
                tkfont.Font(root=self.root, name=name, exists=True).configure(
                    family="Microsoft YaHei UI", size=size
                )
            except tk.TclError:
                pass  # 主题未加载（无 sv_ttk）时该字体不存在
        style = ttk.Style(self.root)
        # 紧凑控件密度：分组框留白尽量小，行距收窄，保持可用
        style.configure("TLabelframe", padding=self._px(4))
        style.configure("TLabelframe.Label", padding=(0, 0, 0, self._px(1)))
        style.configure("TButton", padding=(self._px(10), self._px(3)))
        style.configure("Accent.TButton", padding=(self._px(14), self._px(3)))
        self._hint_fg = self._muted_color()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self._build_menubar()

        main = ttk.Frame(self.root, padding=(8, 6, 8, 6))
        main.pack(fill=tk.BOTH, expand=True)
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)

        self._build_catia_bar(main)
        self._build_footer(main)

        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=2, column=0, sticky=tk.NSEW, pady=(6, 6))

        self._build_design_tab()
        self._build_optics_tab()
        self._build_construct_tab()

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self.root)
        export_menu = tk.Menu(menubar, tearoff=0)
        export_menu.add_command(label="STL…", command=self.on_export_stl)
        export_menu.add_command(label="OBJ…", command=self.on_export_obj)
        export_menu.add_command(label="STEP…", command=self.on_export_step)
        menubar.add_cascade(label="导出", menu=export_menu)
        self.root.config(menu=menubar)

    def _build_catia_bar(self, parent: "ttk.Frame") -> None:
        bar = ttk.Frame(parent)
        bar.grid(row=0, column=0, sticky=tk.EW)
        bar.columnconfigure(0, weight=1)
        self.catia_label = ttk.Label(bar, text="检测中…")
        self.catia_label.grid(row=0, column=0, sticky=tk.W)
        ttk.Button(bar, text="刷新", width=8, command=self._refresh_catia_status).grid(
            row=0, column=1, sticky=tk.E, padx=(8, 0)
        )

    def _build_design_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="设计")
        self._design_tab = tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        source = ttk.LabelFrame(tab, text="Source", padding=6)
        source.grid(row=0, column=0, sticky="new", padx=(0, 8), pady=(0, 8))
        self.src_x = self._add_entry(source, "X position", "0.0", 0, unit="mm")
        self.src_y = self._add_entry(source, "Y position", "0.0", 1, unit="mm")
        self.src_z = self._add_entry(source, "Z position", "0.0", 2, unit="mm")
        self.src_pattern = self._add_combobox(
            source, "Angular pattern", ["lambertian", "isotropic"], "lambertian", 3
        )
        self.focal = self._add_entry(source, "Carrier focal", "10.0", 4, unit="mm")

        size = ttk.LabelFrame(tab, text="Size", padding=6)
        size.grid(row=0, column=1, sticky="new", padx=(0, 0), pady=(0, 8))

        self.n_u = tk.StringVar(value="4")
        self.n_v = tk.StringVar(value="4")
        self.degree_u = tk.StringVar(value="5")
        self.degree_v = tk.StringVar(value="5")
        self.offset_x = tk.StringVar(value="-20")
        self.offset_y = tk.StringVar(value="-20")
        self.start_z = tk.StringVar(value="0")
        self.width_deltas = tk.StringVar(value="10,10,10,10")
        self.height_deltas = tk.StringVar(value="10,10,10,10")

        self._add_pair(size, "# facets U, V", self.n_u, self.n_v, 0)
        self._add_pair(size, "degree U, V", self.degree_u, self.degree_v, 1)
        self._add_pair(size, "offset X, Y", self.offset_x, self.offset_y, 2, unit="mm")
        self._add_labeled_entry(size, "start Z", self.start_z, 3, unit="mm")
        self._add_labeled_entry(size, "width deltas", self.width_deltas, 4, wide=True)
        self._add_labeled_entry(size, "height deltas", self.height_deltas, 5, wide=True)
        self._hint(
            size,
            "逗号分隔，个数对应面片数 U / V，不足则重复末值。",
            6,
        )

        adv_wrap = ttk.LabelFrame(tab, text="Advanced", padding=6)
        adv_wrap.grid(row=1, column=0, columnspan=2, sticky="new")
        self.src_axis_auto = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            adv_wrap,
            text="Auto axis（光源 → 反射面中心）",
            variable=self.src_axis_auto,
            command=self._sync_axis_state,
        ).grid(row=0, column=0, columnspan=4, sticky=tk.W)
        self.src_axis_x = tk.StringVar(value="0.0")
        self.src_axis_y = tk.StringVar(value="0.0")
        self.src_axis_z = tk.StringVar(value="-1.0")
        self.src_lambert_n = tk.StringVar(value="1.0")
        axis_row = ttk.Frame(adv_wrap)
        axis_row.grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))
        ttk.Label(axis_row, text="Axis X,Y,Z").pack(side=tk.LEFT)
        self._ax_widgets = []
        for var in (self.src_axis_x, self.src_axis_y, self.src_axis_z):
            e = ttk.Entry(axis_row, textvariable=var, width=8, justify=tk.RIGHT)
            e.pack(side=tk.LEFT, padx=(6, 0))
            self._ax_widgets.append(e)
        n_row = ttk.Frame(adv_wrap)
        n_row.grid(row=2, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))
        ttk.Label(n_row, text="Lambertian n").pack(side=tk.LEFT)
        ttk.Entry(n_row, textvariable=self.src_lambert_n, width=8, justify=tk.RIGHT).pack(
            side=tk.LEFT, padx=(6, 0)
        )

        self._design_columns = (source, size)
        self._design_advanced = adv_wrap
        tab.bind("<Configure>", self._on_design_configure)

    def _build_optics_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="光学")

        frame = ttk.LabelFrame(tab, text="Spreads", padding=6)
        frame.pack(fill=tk.X)
        self.spread_h = self._add_entry(frame, "H angles", "-20,20", 0, unit="°", width=16)
        self.spread_v = self._add_entry(frame, "V angles", "-10,10", 1, unit="°", width=16)
        self.edge_ray = self._add_combobox(
            frame,
            "Edge-ray",
            [e.value for e in EdgeRayMode],
            EdgeRayMode.CENTER.value,
            2,
        )
        self.uniform_intensity = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Uniform intensity",
            variable=self.uniform_intensity,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(6, 2))
        self._hint(
            frame,
            "按入射通量做可分离映射，四边钉在设定的 H/V 端点。格式：min,max。",
            4,
            cols=3,
        )

    def _build_construct_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(tab, text="构造")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        gaps = ttk.LabelFrame(tab, text="Gaps", padding=6)
        gaps.grid(row=0, column=0, sticky="new", padx=(0, 8), pady=(0, 8))
        ttk.Label(gaps, text="Mode").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.gap_type = tk.StringVar(value=GapType.GAP.value)
        mode_box = ttk.Combobox(
            gaps,
            textvariable=self.gap_type,
            values=[GapType.GAP.value, GapType.NO_GAP.value],
            state="readonly",
            width=16,
        )
        mode_box.grid(row=0, column=1, sticky=tk.W, padx=3, pady=2)
        mode_box.bind("<<ComboboxSelected>>", lambda e: self._sync_gap_mode_options())

        ttk.Label(gaps, text="Option").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.gap_mode = tk.StringVar(value=GapSurfaceMode.SURFACE.value)
        self.gap_option_box = ttk.Combobox(
            gaps,
            textvariable=self.gap_mode,
            values=[GapSurfaceMode.EMPTY.value, GapSurfaceMode.SURFACE.value],
            state="readonly",
            width=16,
        )
        self.gap_option_box.grid(row=1, column=1, sticky=tk.W, padx=3, pady=2)
        self.gap_u = self._add_entry(gaps, "Size U", "0.2", 2, unit="mm")
        self.gap_v = self._add_entry(gaps, "Size V", "0.2", 3, unit="mm")

        start = ttk.LabelFrame(tab, text="F.Start", padding=6)
        start.grid(row=0, column=1, sticky="new", padx=(0, 0), pady=(0, 8))
        self.fstart_summary = ttk.Label(start, text="")
        self.fstart_summary.pack(anchor=tk.W, pady=(0, 8))
        ttk.Button(start, text="F.Start…", command=self._open_fstart_dialog).pack(anchor=tk.W)

        self.use_start_point = tk.BooleanVar(value=True)
        self.start_x = tk.StringVar(value="0.0")
        self.start_y = tk.StringVar(value="0.0")
        self.start_auto = tk.BooleanVar(value=True)
        self.calc_start_u = tk.StringVar(value="0.0")
        self.calc_start_v = tk.StringVar(value="0.0")
        self.reference_u = tk.StringVar(value="0.0")
        self.reference_v = tk.StringVar(value="0.0")
        self.use_neighbor_curve = tk.BooleanVar(value=False)
        self.z_step_u = tk.StringVar(value="0.0")
        self.z_step_v = tk.StringVar(value="0.0")

        patch = ttk.LabelFrame(tab, text="Patch Fit", padding=6)
        patch.grid(row=1, column=0, columnspan=2, sticky="new", pady=(0, 8))
        self.patch_method = self._add_combobox(
            patch,
            "Patch fit method",
            [m.value for m in PatchFitMethod],
            PatchFitMethod.APPROXIMATE.value,
            0,
        )

        self._adv_visible = tk.BooleanVar(value=False)
        adv_head = ttk.Frame(tab)
        adv_head.grid(row=2, column=0, columnspan=2, sticky=tk.EW)
        self._adv_toggle = ttk.Checkbutton(
            adv_head,
            text="Advanced",
            variable=self._adv_visible,
            command=self._toggle_advanced,
        )
        self._adv_toggle.pack(anchor=tk.W)

        self._adv_body = ttk.LabelFrame(tab, text="Solver", padding=6)
        self.samples = self._add_entry(self._adv_body, "Samples per edge", "15", 0)
        self.solve = self._add_combobox(
            self._adv_body,
            "Solve order",
            [s.value for s in SolveMethod],
            SolveMethod.V_FIRST.value,
            1,
        )
        self.solver_iterations = self._add_entry(self._adv_body, "Max iterations", "5", 2)
        self.solver_tolerance = self._add_entry(self._adv_body, "Tolerance", "1e-5", 3)
        self.fit_patches_u = self._add_entry(self._adv_body, "# Fit patches U", "1", 4)
        self.fit_patches_v = self._add_entry(self._adv_body, "# Fit patches V", "1", 5)
        self.continuity_u = self._add_combobox(
            self._adv_body,
            "Continuity U",
            [c.value for c in PatchContinuity],
            PatchContinuity.POINT.value,
            6,
        )
        self.continuity_v = self._add_combobox(
            self._adv_body,
            "Continuity V",
            [c.value for c in PatchContinuity],
            PatchContinuity.POINT.value,
            7,
        )

        self._sync_gap_mode_options()

    def _toggle_advanced(self) -> None:
        if self._adv_visible.get():
            self._adv_body.grid(row=3, column=0, columnspan=2, sticky="new", pady=(2, 0))
        else:
            self._adv_body.grid_remove()

    def _build_footer(self, parent: "ttk.Frame") -> None:
        footer = ttk.Frame(parent)
        footer.grid(row=3, column=0, sticky=tk.EW)
        ttk.Separator(footer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 8))
        btns = ttk.Frame(footer)
        btns.pack(fill=tk.X)
        self.status = ttk.Label(footer, text="就绪。", anchor=tk.W)
        self.status.pack(fill=tk.X, pady=(0, 8))
        self.btn_generate = ttk.Button(
            btns, text="生成", style="Accent.TButton", command=self.on_apply
        )
        self.btn_generate.pack(side=tk.RIGHT)
        self.btn_catia = ttk.Button(btns, text="发送到 CATIA", command=self.on_send_catia)
        self.btn_catia.pack(side=tk.RIGHT, padx=(0, 8))

    # ------------------------------------------------------------------ helpers
    def _hint(self, parent, text: str, row: int, cols: int = 3) -> None:
        lbl = ttk.Label(parent, text=text, foreground=self._hint_fg)
        lbl.grid(row=row, column=0, columnspan=cols, sticky=tk.W, pady=(2, 0))
        self._hint_labels.append(lbl)

    def _add_entry(
        self,
        parent,
        label: str,
        default,
        row: int,
        width: int = 14,
        unit: str = "",
    ) -> "tk.StringVar":
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        if isinstance(default, tk.StringVar):
            var = default
        else:
            var = tk.StringVar(value=str(default))
        ttk.Entry(parent, textvariable=var, width=width, justify=tk.RIGHT).grid(
            row=row, column=1, sticky=tk.W, padx=3, pady=2
        )
        if unit:
            ttk.Label(parent, text=unit, foreground=self._hint_fg).grid(
                row=row, column=2, sticky=tk.W
            )
        return var

    def _add_labeled_entry(
        self,
        parent,
        label: str,
        var: "tk.StringVar",
        row: int,
        unit: str = "",
        wide: bool = False,
    ) -> "ttk.Entry":
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        entry = ttk.Entry(
            parent,
            textvariable=var,
            width=22 if wide else 9,
            justify=tk.RIGHT if not wide else tk.LEFT,
        )
        entry.grid(row=row, column=1, columnspan=2 if wide else 1, sticky=tk.W, padx=3, pady=2)
        if unit and not wide:
            ttk.Label(parent, text=unit, foreground=self._hint_fg).grid(
                row=row, column=2, sticky=tk.W
            )
        return entry

    def _add_pair(
        self,
        parent,
        label: str,
        var_a: "tk.StringVar",
        var_b: "tk.StringVar",
        row: int,
        unit: str = "",
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        pair = ttk.Frame(parent)
        pair.grid(row=row, column=1, sticky=tk.W, padx=3, pady=2)
        ttk.Entry(pair, textvariable=var_a, width=7, justify=tk.RIGHT).pack(side=tk.LEFT)
        ttk.Entry(pair, textvariable=var_b, width=8, justify=tk.RIGHT).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        if unit:
            ttk.Label(parent, text=unit, foreground=self._hint_fg).grid(
                row=row, column=2, sticky=tk.W
            )

    def _add_combobox(
        self,
        parent,
        label: str,
        values: list[str],
        default: str,
        row: int,
    ) -> "tk.StringVar":
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        var = tk.StringVar(value=default)
        ttk.Combobox(
            parent, textvariable=var, values=values, state="readonly", width=16
        ).grid(row=row, column=1, sticky=tk.W, padx=3, pady=2)
        return var

    def _sync_axis_state(self) -> None:
        state = tk.DISABLED if self.src_axis_auto.get() else tk.NORMAL
        for w in getattr(self, "_ax_widgets", []):
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

    def _on_design_configure(self, event=None) -> None:
        if not self._design_columns:
            return
        tab = self._design_tab
        left, right = self._design_columns
        width = tab.winfo_width()
        threshold = self._px(740)
        adv = getattr(self, "_design_advanced", None)
        if width < threshold and width > 2:
            left.grid(row=0, column=0, columnspan=2, sticky="new", padx=0, pady=(0, 8))
            right.grid(row=1, column=0, columnspan=2, sticky="new", padx=0, pady=(0, 8))
            if adv is not None:
                adv.grid(row=2, column=0, columnspan=2, sticky="new")
        else:
            left.grid(row=0, column=0, columnspan=1, sticky="new", padx=(0, 8), pady=(0, 8))
            right.grid(row=0, column=1, columnspan=1, sticky="new", padx=0, pady=(0, 8))
            if adv is not None:
                adv.grid(row=1, column=0, columnspan=2, sticky="new")

    def _on_root_configure(self, event=None) -> None:
        if event and event.widget is not self.root:
            return
        wrap = max(240, self.root.winfo_width() - self._px(80))
        for lbl in self._hint_labels:
            try:
                lbl.configure(wraplength=wrap)
            except tk.TclError:
                pass
        try:
            self.catia_label.configure(wraplength=max(200, wrap - self._px(120)))
        except tk.TclError:
            pass

    def _sync_gap_mode_options(self) -> None:
        if self.gap_type.get() == GapType.NO_GAP.value:
            opts = [
                GapSurfaceMode.NEW_BORDER.value,
                GapSurfaceMode.OLD_BORDER.value,
                GapSurfaceMode.AVERAGE.value,
            ]
            default = GapSurfaceMode.NEW_BORDER.value
        else:
            opts = [GapSurfaceMode.EMPTY.value, GapSurfaceMode.SURFACE.value]
            default = GapSurfaceMode.SURFACE.value
        self.gap_option_box["values"] = opts
        if self.gap_mode.get() not in opts:
            self.gap_mode.set(default)

    def _refresh_fstart_summary(self) -> None:
        if self.use_start_point.get():
            loc = f"全局起点 ({self.start_x.get()}, {self.start_y.get()})"
        else:
            loc = "全局起点关闭"
        auto = "自动参考点" if self.start_auto.get() else "手动 U/V"
        self.fstart_summary.config(text=f"{loc} · {auto}")

    def _aperture_bounds(self) -> tuple[float, float, float, float]:
        n_u = max(1, int(float(self.n_u.get())))
        n_v = max(1, int(float(self.n_v.get())))
        widths = self._parse_deltas(self.width_deltas.get(), n_u)
        heights = self._parse_deltas(self.height_deltas.get(), n_v)
        x0 = float(self.offset_x.get())
        y0 = float(self.offset_y.get())
        return x0, x0 + float(sum(widths)), y0, y0 + float(sum(heights))

    def _dialog_action_bar(
        self,
        dialog: "tk.Toplevel",
        on_apply,
        status_var: "tk.StringVar",
    ) -> None:
        footer = ttk.Frame(dialog, padding=(12, 8, 12, 12))
        footer.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Separator(footer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 8))
        ttk.Label(footer, textvariable=status_var, foreground="#1a5f2a").pack(
            anchor=tk.W, pady=(0, 8)
        )
        buttons = ttk.Frame(footer)
        buttons.pack(fill=tk.X)

        def apply_and_close() -> None:
            if on_apply():
                dialog.destroy()

        ttk.Button(buttons, text="Apply", command=on_apply, width=10).pack(side=tk.LEFT)
        ttk.Button(buttons, text="OK", command=apply_and_close, width=10).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(buttons, text="Close", command=dialog.destroy, width=10).pack(
            side=tk.RIGHT
        )

    # ---------------------------------------------------------------- Dialogs
    def _open_fstart_dialog(self) -> None:
        if self._fstart_dialog is not None and self._fstart_dialog.winfo_exists():
            self._fstart_dialog.lift()
            self._fstart_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self._fstart_dialog = dialog
        dialog.title("F.Start")
        dialog.transient(self.root)
        dialog.minsize(self._px(460), self._px(420))
        dialog.geometry(f"{self._px(520)}x{self._px(620)}")
        dialog.resizable(True, True)
        dialog.grab_set()

        d_use_start = tk.BooleanVar(value=self.use_start_point.get())
        d_start_x = tk.StringVar(value=self.start_x.get())
        d_start_y = tk.StringVar(value=self.start_y.get())
        d_start_auto = tk.BooleanVar(value=self.start_auto.get())
        d_calc_u = tk.StringVar(value=self.calc_start_u.get())
        d_calc_v = tk.StringVar(value=self.calc_start_v.get())
        d_ref_u = tk.StringVar(value=self.reference_u.get())
        d_ref_v = tk.StringVar(value=self.reference_v.get())
        d_neighbor = tk.BooleanVar(value=self.use_neighbor_curve.get())
        d_z_u = tk.StringVar(value=self.z_step_u.get())
        d_z_v = tk.StringVar(value=self.z_step_v.get())
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
                messagebox.showerror(
                    "F.Start",
                    "All numeric fields must be valid numbers.",
                    parent=dialog,
                )
                return False
            if d_use_start.get():
                try:
                    x0, x1, y0, y1 = self._aperture_bounds()
                except Exception as exc:
                    messagebox.showerror("F.Start", f"Cannot read the grid: {exc}", parent=dialog)
                    return False
                pad = 1e-9
                if not (x0 - pad <= sx <= x1 + pad and y0 - pad <= sy <= y1 + pad):
                    messagebox.showerror(
                        "F.Start",
                        f"Start ({sx:.3f}, {sy:.3f}) is outside the aperture\n"
                        f"X {x0:.1f}…{x1:.1f}, Y {y0:.1f}…{y1:.1f}.",
                        parent=dialog,
                    )
                    return False
            self.use_start_point.set(d_use_start.get())
            self.start_x.set(f"{sx:g}")
            self.start_y.set(f"{sy:g}")
            self.start_auto.set(d_start_auto.get())
            self.calc_start_u.set(f"{cu:g}")
            self.calc_start_v.set(f"{cv:g}")
            self.reference_u.set(f"{ru:g}")
            self.reference_v.set(f"{rv:g}")
            self.use_neighbor_curve.set(d_neighbor.get())
            self.z_step_u.set(f"{zu:g}")
            self.z_step_v.set(f"{zv:g}")
            self._refresh_fstart_summary()
            if d_use_start.get():
                status.set(f"Applied — start ({sx:g}, {sy:g}). Generate to rebuild.")
            else:
                status.set("Applied — global start off, using U/V. Generate to rebuild.")
            return True

        self._dialog_action_bar(dialog, apply_fstart, status)

        body = ttk.Frame(dialog, padding=(12, 12, 12, 0))
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=1)

        grid_group = ttk.LabelFrame(body, text="Grid Start Point", padding=8)
        grid_group.grid(row=0, column=0, sticky=tk.EW)
        ttk.Checkbutton(
            grid_group, text="使用全局起点", variable=d_use_start
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        self._add_entry(grid_group, "Start X", d_start_x, 1, unit="mm")
        self._add_entry(grid_group, "Start Y", d_start_y, 2, unit="mm")
        try:
            x0, x1, y0, y1 = self._aperture_bounds()
            bounds = (
                f"须落在当前孔径内：X {x0:.1f}…{x1:.1f}，Y {y0:.1f}…{y1:.1f}。"
                f"中心 ({0.5 * (x0 + x1):.1f}, {0.5 * (y0 + y1):.1f})。"
            )
        except Exception:
            bounds = "须落在设计页的孔径范围内。"
        ttk.Label(grid_group, text=bounds, wraplength=self._px(450), justify=tk.LEFT).grid(
            row=3, column=0, columnspan=3, sticky=tk.W, pady=(2, 0)
        )

        calc_group = ttk.LabelFrame(body, text="Facet Calculation Start", padding=8)
        calc_group.grid(row=1, column=0, sticky=tk.EW, pady=(10, 0))
        ttk.Checkbutton(
            calc_group, text="自动（使用参考点）", variable=d_start_auto
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        self._add_entry(calc_group, "Start U", d_calc_u, 1)
        self._add_entry(calc_group, "Start V", d_calc_v, 2)
        self._add_entry(calc_group, "Reference U", d_ref_u, 3)
        self._add_entry(calc_group, "Reference V", d_ref_v, 4)

        neighbor_group = ttk.LabelFrame(body, text="Boundary & Z Steps", padding=8)
        neighbor_group.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
        ttk.Checkbutton(
            neighbor_group, text="使用邻边基线", variable=d_neighbor
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        self._add_entry(neighbor_group, "Z step U", d_z_u, 1, unit="mm")
        self._add_entry(neighbor_group, "Z step V", d_z_v, 2, unit="mm")
        ttk.Label(
            neighbor_group,
            text="关：只在参考点对齐，光学展开保持设定范围。开：共享边水密，接缝附近光学会弯。",
            wraplength=self._px(450),
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    # ------------------------------------------------------------------ CATIA
    def _refresh_catia_status(self) -> None:
        self.catia_status = detect_catia()
        st = self.catia_status
        self.catia_label.config(text=st.message)
        if st.can_send:
            self.btn_catia.config(state=tk.NORMAL)
        else:
            self.btn_catia.config(state=tk.DISABLED)

    # ------------------------------------------------------------------ Data
    @staticmethod
    def _parse_deltas(text: str, n: int, fallback: float = 10.0) -> list:
        parts = [p.strip() for p in str(text).replace(";", ",").split(",") if p.strip()]
        vals = [float(p) for p in parts] if parts else []
        if not vals:
            vals = [fallback]
        if len(vals) < n:
            vals = vals + [vals[-1]] * (n - len(vals))
        return vals[:n]

    def _collect(self) -> MFReflector:
        n_u = max(1, int(self.n_u.get()))
        n_v = max(1, int(self.n_v.get()))
        degree_u = max(1, int(self.degree_u.get()))
        degree_v = max(1, int(self.degree_v.get()))
        width_deltas = self._parse_deltas(self.width_deltas.get(), n_u)
        height_deltas = self._parse_deltas(self.height_deltas.get(), n_v)
        offset_x = float(self.offset_x.get())
        offset_y = float(self.offset_y.get())
        start_z = float(self.start_z.get())

        calculation_start_u = (
            None if self.start_auto.get() else float(self.calc_start_u.get())
        )
        calculation_start_v = (
            None if self.start_auto.get() else float(self.calc_start_v.get())
        )
        gap_type = GapType(self.gap_type.get())
        step_z = 0.0

        return MFReflector(
            name="UI_Reflector",
            source=PointSource(
                position=np.array([
                    float(self.src_x.get()),
                    float(self.src_y.get()),
                    float(self.src_z.get()),
                ]),
                pattern=str(self.src_pattern.get()),
                lambert_n=float(self.src_lambert_n.get()),
                axis=None if self.src_axis_auto.get() else np.array([
                    float(self.src_axis_x.get()),
                    float(self.src_axis_y.get()),
                    float(self.src_axis_z.get()),
                ]),
            ),
            grid=GridLayout(
                n_u=n_u,
                n_v=n_v,
                width_deltas=width_deltas,
                height_deltas=height_deltas,
                offset_x=offset_x,
                offset_y=offset_y,
                start_z=start_z,
                focal=float(self.focal.get()),
                degree_u=degree_u,
                degree_v=degree_v,
                use_start_point=self.use_start_point.get(),
                start_point=np.array([float(self.start_x.get()), float(self.start_y.get())]),
            ),
            gaps=GapsConfig(
                enabled=True,
                gap_type=gap_type,
                surface_mode=GapSurfaceMode(self.gap_mode.get()),
                size_u=float(self.gap_u.get()),
                size_v=float(self.gap_v.get()),
                size_z=step_z,
            ),
            spreads=SpreadsConfig(
                light_target=LightTargetType.FAR_FIELD,
                edge_ray=EdgeRayMode(self.edge_ray.get()),
                h_angles=self.spread_h.get(),
                v_angles=self.spread_v.get(),
                uniform_intensity=bool(self.uniform_intensity.get()),
            ),
            solve=SolveMethod(self.solve.get()),
            mesh_u=max(2, int(self.samples.get())),
            mesh_v=max(2, int(self.samples.get())),
            solver_iterations=max(1, int(self.solver_iterations.get())),
            solver_tolerance=float(self.solver_tolerance.get()),
            calculation_start_u=calculation_start_u,
            calculation_start_v=calculation_start_v,
            reference_position_u=float(self.reference_u.get()),
            reference_position_v=float(self.reference_v.get()),
            use_base_curve_from_neighbor=self.use_neighbor_curve.get(),
            z_step_u=float(self.z_step_u.get()),
            z_step_v=float(self.z_step_v.get()),
            patch_fit_method=PatchFitMethod(self.patch_method.get()),
            fit_patches_u=max(1, int(self.fit_patches_u.get())),
            fit_patches_v=max(1, int(self.fit_patches_v.get())),
            fit_patch_continuity_u=PatchContinuity(self.continuity_u.get()),
            fit_patch_continuity_v=PatchContinuity(self.continuity_v.get()),
        )

    def on_apply(self) -> None:
        try:
            self.reflector = self._collect()
            generate_facets(self.reflector)
            n_opt = sum(1 for f in self.reflector.facets if not f.is_gap_surface)
            n_gap = sum(1 for f in self.reflector.facets if f.is_gap_surface)
            self.status.config(text=f"已生成 {n_opt} 个 NURBS 光学面 + {n_gap} 个缝面。")
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))
            self.status.config(text="生成失败。")

    def on_export_stl(self) -> None:
        if not self._ensure_generated():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".stl", filetypes=[("STL", "*.stl")]
        )
        if path:
            vertices, faces = facets_to_mesh(self.reflector.facets)
            export_stl(vertices, faces, path)
            self.status.config(text=f"已保存 {path}")

    def on_export_obj(self) -> None:
        if not self._ensure_generated():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".obj", filetypes=[("OBJ", "*.obj")]
        )
        if path:
            vertices, faces = facets_to_mesh(self.reflector.facets)
            export_obj(vertices, faces, path)
            self.status.config(text=f"已保存 {path}")

    def on_export_step(self) -> None:
        if not self._ensure_generated():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".stp", filetypes=[("STEP", "*.stp *.step")]
        )
        if path:
            try:
                n = export_step(self.reflector.facets, path, include_gap_surfaces=True)
                self.status.config(text=f"STEP 已保存（{n} 面）：{path}")
            except Exception as exc:
                messagebox.showerror("STEP 导出失败", str(exc))

    def on_send_catia(self) -> None:
        if not self.reflector or not self.reflector.is_generated():
            self.on_apply()
            if not self.reflector or not self.reflector.is_generated():
                return
        self._refresh_catia_status()
        if not self.catia_status.can_send:
            messagebox.showwarning("CATIA", self.catia_status.message)
            return
        try:
            with tempfile.TemporaryDirectory(prefix="mf_reflector_") as temp_dir:
                tmp = Path(temp_dir) / "reflector.stp"
                export_step(self.reflector.facets, str(tmp), include_gap_surfaces=True)
                result = import_step_to_active_part(tmp, body_name="MF_Reflector")
            self.status.config(text=result.message)
            if result.ok:
                messagebox.showinfo("CATIA", result.message)
            else:
                messagebox.showerror("CATIA", result.message)
        except Exception as exc:
            messagebox.showerror("CATIA", str(exc))

    def _ensure_generated(self) -> bool:
        if not self.reflector or not self.reflector.is_generated():
            messagebox.showwarning("提示", "请先生成反射面。")
            return False
        return True


def run() -> None:
    if not HAS_TK:
        print("tkinter is not available in this environment.")
        status = detect_catia()
        print(f"CATIA status: {status.state.value} – {status.message}")
        return
    root = tk.Tk()
    MFReflectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()
