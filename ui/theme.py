# SPDX-License-Identifier: MIT
"""sv-ttk 主题应用与全局字体设置。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

try:
    import sv_ttk
    HAS_SV_TTK = True
except ImportError:
    HAS_SV_TTK = False

# sv-ttk 主题字体 → 字号（pt）。sv-ttk 自带的 SunValley*Font 是 11pt Segoe UI，
# 必须整体覆盖为微软雅黑；改字号只需改这张表。
SV_TTK_FONTS = {
    "SunValleyBodyFont": 11,        # 正文：所有标签、输入框、下拉框
    "SunValleyBodyStrongFont": 12,  # 加粗正文：按钮文字
    "SunValleyBodyLargeFont": 12,   # 大号正文
    "SunValleyCaptionFont": 10,     # 小字说明（灰色提示、单位 mm/°）
    "SunValleySubtitleFont": 12,    # 副标题
    "SunValleyTitleFont": 14,       # 标题
    "SunValleyTitleLargeFont": 16,  # 大标题
    "SunValleyDisplayFont": 18,     # 展示级大字
}
UI_FONT_FAMILY = "Microsoft YaHei UI"
UI_FONT_SIZE = 12
MUTED_FALLBACK = "#5B616B"


def system_dpi() -> float:
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


def muted_color(root: "tk.Tk") -> str:
    """Muted foreground matching the active theme (fallback: fixed grey)."""
    try:
        return root.tk.call("ttk::style", "lookup", "TLabel", "-foreground") or MUTED_FALLBACK
    except tk.TclError:
        return MUTED_FALLBACK


def apply_visual_theme(root: "tk.Tk", px=lambda v: int(v)) -> None:
    """应用主题字体与控件密度（幂等）。px 为逻辑像素 → 物理像素的换算函数。"""
    if HAS_SV_TTK:
        sv_ttk.set_theme("light")
    # 全局字体：微软雅黑（用户指定）。
    # 注意：sv-ttk 给 ttk 控件定义了专用 SunValley*Font（11pt Segoe UI），
    # 只改 TkDefaultFont 等命名字体对 ttk 控件无效，必须一并覆盖。
    import tkinter.font as tkfont

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
        tkfont.nametofont(name).configure(family=UI_FONT_FAMILY, size=UI_FONT_SIZE)
    for name, size in SV_TTK_FONTS.items():
        try:
            tkfont.Font(root=root, name=name, exists=True).configure(
                family=UI_FONT_FAMILY, size=size
            )
        except tk.TclError:
            pass  # 主题未加载（无 sv_ttk）时该字体不存在
    style = ttk.Style(root)
    # 紧凑控件密度：分组框留白尽量小，行距收窄，保持可用
    style.configure("TLabelframe", padding=px(4))
    style.configure("TLabelframe.Label", padding=(0, 0, 0, px(1)))
    style.configure("TButton", padding=(px(10), px(3)))
    style.configure("Accent.TButton", padding=(px(14), px(3)))
