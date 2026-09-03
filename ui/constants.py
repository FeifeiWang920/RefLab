# SPDX-License-Identifier: MIT
"""UI 布局与交互常量（逻辑像素，随 DPI 缩放）。"""

from __future__ import annotations

# 主窗口（客户区）
WINDOW_SIZE = (760, 520)
MIN_WINDOW_SIZE = (560, 430)

# 设计页两列并排的最小窗口逻辑宽度（低于则切换单列堆叠）
TWO_COLUMN_THRESHOLD = 740

# 后台任务轮询与超时
POLL_INTERVAL_MS = 50
GENERATION_TIMEOUT_S = 120

# 对话框内「已应用」状态文字的颜色
STATUS_OK_COLOR = "#1a5f2a"
