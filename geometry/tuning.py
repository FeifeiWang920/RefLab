# SPDX-License-Identifier: MIT
"""求解器调参常量。

集中在此便于调参与审阅。⚠️ 改值会改变光学结果——
黄金基线测试（tests/test_golden_height_field.py）会拦截未经评估的改动。
"""

from __future__ import annotations

# ---- 单面片定态迭代（_solve_facet_optical）----
# 路径积分保持 iso-V 不弯、LS 保持单一光滑图，二者按此权重混合
PATHS_LS_BLEND = (0.35, 0.65)
# 边界区间权重：高于内部权重以守住远场矩形轮廓（即使坡度场不可积）
EDGE_WEIGHT = 2.5

# ---- 逆问题迭代（远场纠偏，_build_height_field Pass 3）----
SPATIAL_PASSES_UNIFORM = 5  # 均匀光强模式的轮数（非均匀为 1）
GAIN_SCHEDULE_BASE = 0.75   # gain = BASE * DECAY**k
GAIN_SCHEDULE_DECAY = 0.8
GAIN_FIXED = 0.85           # 非均匀模式的固定增益

# ---- 远场矩形抛光（_polish_farfield_rectangle，均匀光强模式）----
POLISH_PASSES = 6           # 请求轮数（函数内按历史行为钳到 3）
POLISH_GAIN_BASE = 0.40     # 行内 H 平移/拉伸的增益调度
POLISH_GAIN_DECAY = 0.85
POLISH_PIN_GAIN_BASE = 0.50  # V 端行钉扎的增益调度
POLISH_ZCLIP = 0.12          # V 钉扎的单步高度变化限幅

# ---- 行内 H 预加重（_row_h_preemphasis，均匀光强模式）----
PREEMPHASIS_GAIN = 0.55
PREEMPHASIS_SCALE_CLIP = (0.90, 1.10)  # 每行缩放比例的限幅
PREEMPHASIS_HALF_FACTOR = 1.12         # 钳制半宽 = 0.5 * |want| * 该系数

# ---- 能量映射（_energy_fracs）----
GAMMA_CLIP = (0.8, 2.0)  # flux 幂指数的允许范围

# ---- 可分离逆问题（_separable_inverse_target）----
SEP_ENDPOINT_KEEP = 0.35   # 端点软化：asked 端点 = KEEP*asked + (1-KEEP)*target
SEP_SMOOTH_KERNEL = (0.25, 0.50, 0.25)  # 内部节点三点平滑
SEP_SPAN_FLOOR = 1e-3      # 目标角跨度下限（防退化列表除零）
