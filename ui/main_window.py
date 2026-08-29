"""
Tkinter UI for MF Reflector (v0.10 – tabbed workflow + LucidShape-style dialogs).

- Multi-tab parameter editing
- Advanced Gap and F.Start dialogs
- NURBS reflector generation
- STL / OBJ / STEP export
- CATIA active Part integration
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


class MFReflectorApp:
    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.root.title("MF Reflector – NURBS + CATIA (v0.10)")
        self.root.geometry("720x760")
        self.root.minsize(680, 680)
        self.reflector: Optional[MFReflector] = None
        self.catia_status: CatiaStatus = detect_catia()
        self._gap_dialog: Optional["tk.Toplevel"] = None
        self._fstart_dialog: Optional["tk.Toplevel"] = None
        self._build_ui()
        self._refresh_catia_status()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        self._build_catia_header(main)

        self.notebook = ttk.Notebook(main)
        self.notebook.pack(fill=tk.BOTH, expand=True, pady=(8, 8))

        self._build_grid_tab()
        self._build_gaps_tab()
        self._build_solver_tab()
        self._build_patch_fit_tab()
        self._build_spreads_tab()

        self._build_footer(main)

    def _build_catia_header(self, parent: "ttk.Frame") -> None:
        frame = ttk.LabelFrame(parent, text="CATIA", padding=6)
        frame.pack(fill=tk.X)
        self.catia_label = ttk.Label(frame, text="检测中…", wraplength=620)
        self.catia_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(frame, text="刷新", width=8, command=self._refresh_catia_status).pack(
            side=tk.RIGHT, padx=4
        )

    def _build_grid_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Grid & Source")

        source = ttk.LabelFrame(tab, text="Source (Point)", padding=8)
        source.pack(fill=tk.X, pady=(0, 8))
        self.src_z = self._add_entry(source, "Z position [mm]", "0.0", 0)
        self.focal = self._add_entry(source, "Carrier focal [mm]", "10.0", 1)

        # LucidShape-style size row: degree | #facets | offset | startZ
        size = ttk.LabelFrame(tab, text="Size (LucidShape)", padding=8)
        size.pack(fill=tk.X, pady=(0, 8))

        # Row 0 labels
        ttk.Label(size, text="degree U,V").grid(row=0, column=0, columnspan=2, sticky=tk.W)
        ttk.Label(size, text="# facets U,V").grid(row=0, column=2, columnspan=2, sticky=tk.W, padx=(12, 0))
        ttk.Label(size, text="offset X,Y").grid(row=0, column=4, columnspan=2, sticky=tk.W, padx=(12, 0))
        ttk.Label(size, text="start Z").grid(row=0, column=6, sticky=tk.W, padx=(12, 0))

        self.degree_u = tk.StringVar(value="5")
        self.degree_v = tk.StringVar(value="5")
        self.n_u = tk.StringVar(value="4")
        self.n_v = tk.StringVar(value="4")
        self.offset_x = tk.StringVar(value="-20")
        self.offset_y = tk.StringVar(value="-20")
        self.start_z = tk.StringVar(value="0")

        ttk.Entry(size, textvariable=self.degree_u, width=6).grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(size, textvariable=self.degree_v, width=6).grid(row=1, column=1, sticky=tk.W, pady=2, padx=(2, 0))
        ttk.Entry(size, textvariable=self.n_u, width=6).grid(row=1, column=2, sticky=tk.W, pady=2, padx=(12, 0))
        ttk.Entry(size, textvariable=self.n_v, width=6).grid(row=1, column=3, sticky=tk.W, pady=2, padx=(2, 0))
        ttk.Entry(size, textvariable=self.offset_x, width=8).grid(row=1, column=4, sticky=tk.W, pady=2, padx=(12, 0))
        ttk.Entry(size, textvariable=self.offset_y, width=8).grid(row=1, column=5, sticky=tk.W, pady=2, padx=(2, 0))
        ttk.Entry(size, textvariable=self.start_z, width=8).grid(row=1, column=6, sticky=tk.W, pady=2, padx=(12, 0))

        # width / height deltas (comma-separated, one value per facet)
        deltas = ttk.LabelFrame(tab, text="Facet size deltas [mm]", padding=8)
        deltas.pack(fill=tk.X)
        ttk.Label(deltas, text="width deltas").grid(row=0, column=0, sticky=tk.W)
        self.width_deltas = tk.StringVar(value="10,10,10,10")
        ttk.Entry(deltas, textvariable=self.width_deltas, width=48).grid(
            row=0, column=1, sticky=tk.EW, padx=6, pady=2
        )
        ttk.Label(deltas, text="height deltas").grid(row=1, column=0, sticky=tk.W)
        self.height_deltas = tk.StringVar(value="10,10,10,10")
        ttk.Entry(deltas, textvariable=self.height_deltas, width=48).grid(
            row=1, column=1, sticky=tk.EW, padx=6, pady=2
        )
        deltas.columnconfigure(1, weight=1)

        ttk.Label(
            tab,
            text="width/height deltas: comma-separated sizes for each facet column/row "
                 "(length should match # facets U / V). "
                 "offset X,Y is the lower-left corner of the aperture; start Z is the "
                 "reference height for the first facet seed.",
            wraplength=660,
        ).pack(fill=tk.X, pady=(10, 0))

    def _build_gaps_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Gaps")

        frame = ttk.LabelFrame(tab, text="Gap Parameter (LucidShape)", padding=8)
        frame.pack(fill=tk.X)

        # Mode: gap | no gap
        ttk.Label(frame, text="Mode").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.gap_type = tk.StringVar(value=GapType.GAP.value)
        mode_box = ttk.Combobox(
            frame,
            textvariable=self.gap_type,
            values=[GapType.GAP.value, GapType.NO_GAP.value],
            state="readonly",
            width=16,
        )
        mode_box.grid(row=0, column=1, sticky=tk.W, padx=4, pady=2)
        mode_box.bind("<<ComboboxSelected>>", lambda e: self._sync_gap_mode_options())

        # Sub-mode depends on gap vs no gap
        ttk.Label(frame, text="Option").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.gap_mode = tk.StringVar(value=GapSurfaceMode.SURFACE.value)
        self.gap_option_box = ttk.Combobox(
            frame,
            textvariable=self.gap_mode,
            values=[
                GapSurfaceMode.EMPTY.value,
                GapSurfaceMode.SURFACE.value,
            ],
            state="readonly",
            width=16,
        )
        self.gap_option_box.grid(row=1, column=1, sticky=tk.W, padx=4, pady=2)

        self.gap_u = self._add_entry(frame, "Size U / gap [mm]", "0.2", 2)
        self.gap_v = self._add_entry(frame, "Size V / gap [mm]", "0.2", 3)

        # kept for _collect compatibility (step-back disabled in simplified UI)
        self.gap_enable = tk.BooleanVar(value=True)
        self.gap_size_z = tk.StringVar(value="0.0")

        ttk.Label(
            tab,
            text=(
                "Mode = gap: Option = empty | surface. "
                "Deltas include gap — middle facet optical size = delta − gap, "
                "edge facet = delta − gap/2.\n"
                "Mode = no gap: Option = new border | old border | average "
                "(shared edge is forced to match; no physical gap)."
            ),
            wraplength=660,
            justify=tk.LEFT,
        ).pack(fill=tk.X, pady=(10, 0))

        self._sync_gap_mode_options()

    def _sync_gap_mode_options(self) -> None:
        """Swap Option list according to gap / no gap (LucidShape)."""
        if self.gap_type.get() == GapType.NO_GAP.value:
            opts = [
                GapSurfaceMode.NEW_BORDER.value,
                GapSurfaceMode.OLD_BORDER.value,
                GapSurfaceMode.AVERAGE.value,
            ]
            default = GapSurfaceMode.NEW_BORDER.value
        else:
            opts = [
                GapSurfaceMode.EMPTY.value,
                GapSurfaceMode.SURFACE.value,
            ]
            default = GapSurfaceMode.SURFACE.value
        self.gap_option_box["values"] = opts
        if self.gap_mode.get() not in opts:
            self.gap_mode.set(default)

    def _build_solver_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Solver")

        frame = ttk.LabelFrame(tab, text="Numerical Solver", padding=8)
        frame.pack(fill=tk.X)
        self.samples = self._add_entry(frame, "Samples per facet edge", "6", 0)
        self.solve = self._add_combobox(
            frame,
            "Solve order",
            [s.value for s in SolveMethod],
            SolveMethod.V_FIRST.value,
            1,
        )
        self.solver_iterations = self._add_entry(frame, "Max iterations", "5", 2)
        self.solver_tolerance = self._add_entry(frame, "Convergence tolerance", "1e-5", 3)

        # F.Start variables are shared by the dialog.
        self.use_start_point = tk.BooleanVar(value=True)
        self.start_x = tk.StringVar(value="0.0")
        self.start_y = tk.StringVar(value="0.0")
        self.start_auto = tk.BooleanVar(value=True)
        self.calc_start_u = tk.StringVar(value="0.0")
        self.calc_start_v = tk.StringVar(value="0.0")
        self.reference_u = tk.StringVar(value="0.0")
        self.reference_v = tk.StringVar(value="0.0")
        self.use_neighbor_curve = tk.BooleanVar(value=True)
        self.z_step_u = tk.StringVar(value="0.0")
        self.z_step_v = tk.StringVar(value="0.0")

        ttk.Button(
            tab,
            text="F.Start…",
            command=self._open_fstart_dialog,
        ).pack(anchor=tk.W, pady=(12, 0))
        ttk.Label(
            tab,
            text="F.Start controls the calculation start point, neighbor boundary "
                 "inheritance, reference position, and per-facet U/V Z steps.",
            wraplength=620,
        ).pack(fill=tk.X, pady=(8, 0))

    def _build_patch_fit_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Patch Fit")

        frame = ttk.LabelFrame(tab, text="Solve Patch Parameters", padding=8)
        frame.pack(fill=tk.X)
        self.patch_method = self._add_combobox(
            frame,
            "Patch fit method",
            [m.value for m in PatchFitMethod],
            PatchFitMethod.APPROXIMATE.value,
            0,
        )
        self.fit_patches_u = self._add_entry(frame, "# Fit patches U", "1", 1)
        self.fit_patches_v = self._add_entry(frame, "# Fit patches V", "1", 2)
        self.continuity_u = self._add_combobox(
            frame,
            "Continuity U",
            [c.value for c in PatchContinuity],
            PatchContinuity.POINT.value,
            3,
        )
        self.continuity_v = self._add_combobox(
            frame,
            "Continuity V",
            [c.value for c in PatchContinuity],
            PatchContinuity.POINT.value,
            4,
        )

        ttk.Label(
            tab,
            text="Approximation + keep size keeps the fitted optical surface inside the "
                 "base grid rectangle. Tangent continuity uses a common parameterization.",
            wraplength=620,
        ).pack(fill=tk.X, pady=(10, 0))

    def _build_spreads_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Spreads")

        frame = ttk.LabelFrame(tab, text="Far-field Spreads", padding=8)
        frame.pack(fill=tk.X)
        self.spread_h = self._add_entry(
            frame,
            "H angles [°] per facet (e.g. -20,20)",
            "-20,20",
            0,
        )
        self.spread_v = self._add_entry(
            frame,
            "V angles [°] per facet (e.g. -5,5)",
            "-10,10",
            1,
        )
        self.edge_ray = self._add_combobox(
            frame,
            "Edge-ray mode",
            [e.value for e in EdgeRayMode],
            EdgeRayMode.CENTER.value,
            2,
        )

    def _build_footer(self, parent: "ttk.Frame") -> None:
        footer = ttk.Frame(parent)
        footer.pack(fill=tk.X, side=tk.BOTTOM, pady=(10, 0))

        row1 = ttk.Frame(footer)
        row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(row1, text="Apply / Generate", command=self.on_apply).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(row1, text="Export STL…", command=self.on_export_stl).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(row1, text="Export OBJ…", command=self.on_export_obj).pack(
            side=tk.LEFT, padx=3
        )
        ttk.Button(row1, text="Export STEP…", command=self.on_export_step).pack(
            side=tk.LEFT, padx=3
        )

        row2 = ttk.Frame(footer)
        row2.pack(fill=tk.X)
        self.btn_catia = ttk.Button(
            row2, text="Send to CATIA Part", command=self.on_send_catia
        )
        self.btn_catia.pack(side=tk.LEFT, padx=3)
        self.status = ttk.Label(footer, text="Ready.", relief=tk.SUNKEN, anchor=tk.W)
        self.status.pack(fill=tk.X, pady=(8, 0))

    def _add_entry(
        self,
        parent,
        label: str,
        default: str,
        row: int,
        width: int = 18,
    ) -> "tk.StringVar":
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        var = tk.StringVar(value=default)
        ttk.Entry(parent, textvariable=var, width=width).grid(
            row=row, column=1, sticky=tk.W, padx=4, pady=2
        )
        parent.columnconfigure(0, weight=1)
        return var

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
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=24).grid(
            row=row, column=1, sticky=tk.W, padx=4, pady=2
        )
        parent.columnconfigure(0, weight=1)
        return var

    # ---------------------------------------------------------------- Dialogs
    def _open_gap_dialog(self) -> None:
        if self._gap_dialog is not None and self._gap_dialog.winfo_exists():
            self._gap_dialog.lift()
            self._gap_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self._gap_dialog = dialog
        dialog.title("Gap Settings")
        dialog.transient(self.root)
        dialog.geometry("420x280")
        dialog.resizable(False, False)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        self._add_combobox(
            frame,
            "Gap type",
            [g.value for g in GapType],
            self.gap_type.get(),
            0,
        )
        self._add_combobox(
            frame,
            "Surface mode",
            [m.value for m in GapSurfaceMode],
            self.gap_mode.get(),
            1,
        )
        self._add_entry(frame, "Step-back Z [mm]", self.gap_size_z.get(), 2, 18)

        ttk.Label(
            frame,
            text="Step-back Z is used by step back / step back + no gap types.",
            wraplength=360,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=2, sticky=tk.E, pady=(16, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    def _open_fstart_dialog(self) -> None:
        if self._fstart_dialog is not None and self._fstart_dialog.winfo_exists():
            self._fstart_dialog.lift()
            self._fstart_dialog.focus_force()
            return

        dialog = tk.Toplevel(self.root)
        self._fstart_dialog = dialog
        dialog.title("F.Start")
        dialog.transient(self.root)
        dialog.geometry("480x430")
        dialog.resizable(False, False)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        grid_group = ttk.LabelFrame(frame, text="Grid Start Point", padding=8)
        grid_group.grid(row=0, column=0, columnspan=2, sticky=tk.EW)
        ttk.Checkbutton(
            grid_group,
            text="Use global start point",
            variable=self.use_start_point,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        self._add_entry(grid_group, "Start X [mm]", self.start_x.get(), 1, 18)
        self._add_entry(grid_group, "Start Y [mm]", self.start_y.get(), 2, 18)

        calc_group = ttk.LabelFrame(frame, text="Facet Calculation Start", padding=8)
        calc_group.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
        ttk.Checkbutton(
            calc_group,
            text="Automatic (use reference position)",
            variable=self.start_auto,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        self._add_entry(calc_group, "Start U [0..1]", self.calc_start_u.get(), 1, 18)
        self._add_entry(calc_group, "Start V [0..1]", self.calc_start_v.get(), 2, 18)
        self._add_entry(calc_group, "Reference U [0..1]", self.reference_u.get(), 3, 18)
        self._add_entry(calc_group, "Reference V [0..1]", self.reference_v.get(), 4, 18)

        neighbor_group = ttk.LabelFrame(frame, text="Boundary & Z Steps", padding=8)
        neighbor_group.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0))
        ttk.Checkbutton(
            neighbor_group,
            text="Use base curve from neighbor",
            variable=self.use_neighbor_curve,
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W)
        self._add_entry(neighbor_group, "Z step U [mm]", self.z_step_u.get(), 1, 18)
        self._add_entry(neighbor_group, "Z step V [mm]", self.z_step_v.get(), 2, 18)

        buttons = ttk.Frame(frame)
        buttons.grid(row=3, column=0, columnspan=2, sticky=tk.E, pady=(14, 0))
        ttk.Button(buttons, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)

    # ------------------------------------------------------------------ CATIA
    def _refresh_catia_status(self) -> None:
        self.catia_status = detect_catia()
        st = self.catia_status
        self.catia_label.config(text=st.message)
        if st.ok:
            self.btn_catia.config(state=tk.NORMAL)
        else:
            self.btn_catia.config(state=tk.DISABLED)

    # ------------------------------------------------------------------ Data
    @staticmethod
    def _parse_deltas(text: str, n: int, fallback: float = 10.0) -> list:
        """Parse '10,10,10,10' → list of length n (pad/truncate as needed)."""
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
            None
            if self.start_auto.get()
            else float(self.calc_start_u.get())
        )
        calculation_start_v = (
            None
            if self.start_auto.get()
            else float(self.calc_start_v.get())
        )
        gap_type = GapType(self.gap_type.get())
        step_z = 0.0

        return MFReflector(
            name="UI_Reflector",
            source=PointSource(
                position=np.array([0.0, 0.0, float(self.src_z.get())])
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

    # ------------------------------------------------------------------ Actions
    def on_apply(self) -> None:
        try:
            self.reflector = self._collect()
            generate_facets(self.reflector)
            n_opt = sum(1 for f in self.reflector.facets if not f.is_gap_surface)
            n_gap = sum(1 for f in self.reflector.facets if f.is_gap_surface)
            self.status.config(
                text=f"Generated {n_opt} NURBS facets + {n_gap} gap surfaces."
            )
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            self.status.config(text="Generation failed.")

    def on_export_stl(self) -> None:
        if not self._ensure_generated():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".stl", filetypes=[("STL", "*.stl")]
        )
        if path:
            vertices, faces = facets_to_mesh(self.reflector.facets)
            export_stl(vertices, faces, path)
            self.status.config(text=f"Saved {path}")

    def on_export_obj(self) -> None:
        if not self._ensure_generated():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".obj", filetypes=[("OBJ", "*.obj")]
        )
        if path:
            vertices, faces = facets_to_mesh(self.reflector.facets)
            export_obj(vertices, faces, path)
            self.status.config(text=f"Saved {path}")

    def on_export_step(self) -> None:
        if not self._ensure_generated():
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".stp", filetypes=[("STEP", "*.stp *.step")]
        )
        if path:
            try:
                n = export_step(self.reflector.facets, path, include_gap_surfaces=True)
                self.status.config(text=f"STEP saved ({n} faces): {path}")
            except Exception as exc:
                messagebox.showerror("STEP export failed", str(exc))

    def on_send_catia(self) -> None:
        # One-click import: generate first if needed, then send directly.
        if not self.reflector or not self.reflector.is_generated():
            self.on_apply()
            if not self.reflector or not self.reflector.is_generated():
                return
        self._refresh_catia_status()
        if not self.catia_status.ok:
            messagebox.showwarning("CATIA", self.catia_status.message)
            return
        try:
            # Both the source STEP and the temporary CATPart used by the CATIA
            # bridge are removed after the import completes.
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
            messagebox.showwarning("Warning", "请先点击 Apply / Generate 生成反射面。")
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

