# SPDX-License-Identifier: MIT
"""SpreadsConfig 单元测试：角度列表解析、per_facet 表、缩放/平移。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from models import SpreadsConfig


def test_two_value_list_is_linear():
    s = SpreadsConfig(h_angles="-20,20", v_angles="-10,10")
    assert s.target_angles_on_facet(0, 0, 0.0, 0.5) == (-20.0, 0.0)
    assert s.target_angles_on_facet(0, 0, 0.5, 0.5)[0] == pytest.approx(0.0)
    assert s.target_angles_on_facet(0, 0, 1.0, 0.5) == (20.0, 0.0)


def test_multi_value_list_is_piecewise_linear():
    s = SpreadsConfig(h_angles="0,5,10,15,20", v_angles="-10,10")
    # 等参数步映射到角度列表的分段线性插值
    assert s.target_angles_on_facet(0, 0, 0.25, 0.5)[0] == pytest.approx(5.0)
    assert s.target_angles_on_facet(0, 0, 0.75, 0.5)[0] == pytest.approx(15.0)


def test_empty_list_falls_back_to_global_span():
    s = SpreadsConfig(h_angles="", v_angles="", global_h_deg=40.0, global_v_deg=20.0)
    assert s.target_angles_on_facet(0, 0, 0.0, 0.0) == (-20.0, -10.0)
    assert s.target_angles_on_facet(0, 0, 1.0, 1.0) == (20.0, 10.0)


def test_single_value_list_falls_back_to_global_span():
    # 现行行为：单值列表同样回退到 ±global/2（docstring 只承诺空列表回退，已知偏差）。
    s = SpreadsConfig(h_angles="5", v_angles="-10,10", global_h_deg=40.0)
    assert s.target_angles_on_facet(0, 0, 0.0, 0.5)[0] == -20.0


def test_per_facet_table_overrides_global_lists():
    s = SpreadsConfig(h_angles="-20,20", v_angles="-10,10")
    s.per_facet = [[([-30.0, 30.0], [-5.0, 5.0])]]  # [n_v][n_u]
    assert s.target_angles_on_facet(0, 0, 1.0, 0.5) == (30.0, 0.0)
    assert s.get_facet_spread(0, 0)[:2] == (-30.0, 30.0)


def test_global_scale_and_shift_apply_after_lists():
    s = SpreadsConfig(h_angles="-20,20", v_angles="-10,10")
    s.global_scale_h = 2.0
    s.global_shift_h = 5.0
    assert s.target_angles_on_facet(0, 0, 0.0, 0.5) == (
        pytest.approx(-35.0),
        pytest.approx(0.0),
    )


def test_global_shift_flips_order_for_hilo():
    s = SpreadsConfig(h_angles="-10,10", v_angles="-10,10")
    s.global_shift_h = 100.0
    # H 列表变为 (90, 110)——端点仍按参数序
    assert s.target_angles_on_facet(0, 0, 0.0, 0.5)[0] == 90.0
    assert s.target_angles_on_facet(0, 0, 1.0, 0.5)[0] == 110.0


def test_frac_clipped_to_unit_range():
    s = SpreadsConfig(h_angles="-20,20", v_angles="-10,10")
    assert s.target_angles_on_facet(0, 0, -3.0, 0.5)[0] == -20.0
    assert s.target_angles_on_facet(0, 0, 7.0, 0.5)[0] == 20.0
