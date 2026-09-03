# SPDX-License-Identifier: MIT
"""nurbs.py 纯 Python 版与 numba 版基函数的数值等价性（防双实现漂移）。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry import nurbs

needs_numba = pytest.mark.skipif(
    not getattr(nurbs, "_HAS_NUMBA", False), reason="numba unavailable"
)


@needs_numba
@pytest.mark.parametrize("degree,n_ctrl", [(1, 3), (2, 4), (3, 5), (5, 7)])
def test_find_span_and_basis_equivalence(degree, n_ctrl):
    knots = nurbs.open_uniform_knots(n_ctrl, degree)
    for u in np.linspace(0.0, 1.0, 21):
        span_py = nurbs.find_span(n_ctrl, degree, float(u), knots)
        span_nb = nurbs._find_span_nb(n_ctrl, degree, float(u), knots)
        assert span_py == span_nb, f"span mismatch at u={u}"
        n_py = nurbs.basis_funs(float(u), span_py, degree, knots)
        n_nb = nurbs._basis_funs_nb(float(u), span_py, degree, knots)
        assert np.allclose(n_py, n_nb), f"basis mismatch at u={u}"


@needs_numba
def test_eval_surface_matches_python_math():
    """numba 版 eval_surface 与纯 Python 基函数求和逐点一致。"""
    rng = np.random.default_rng(42)
    degree_u = degree_v = 3
    nu = nv = 6
    ku = nurbs.open_uniform_knots(nu, degree_u)
    kv = nurbs.open_uniform_knots(nv, degree_v)
    ctrl = rng.uniform(-5.0, 5.0, size=(nv, nu, 3))
    for u in (0.0, 0.13, 0.5, 0.77, 1.0):
        for v in (0.0, 0.31, 0.5, 0.86, 1.0):
            got = nurbs.eval_surface(ctrl, degree_u, degree_v, ku, kv, u, v)
            span_u = nurbs.find_span(nu, degree_u, u, ku)
            span_v = nurbs.find_span(nv, degree_v, v, kv)
            Nu = nurbs.basis_funs(u, span_u, degree_u, ku)
            Nv = nurbs.basis_funs(v, span_v, degree_v, kv)
            want = np.zeros(3)
            for j in range(degree_v + 1):
                row = np.zeros(3)
                for i in range(degree_u + 1):
                    row += Nu[i] * ctrl[span_v - degree_v + j, span_u - degree_u + i]
                want += Nv[j] * row
            assert np.allclose(got, want), f"surface mismatch at (u={u}, v={v})"
