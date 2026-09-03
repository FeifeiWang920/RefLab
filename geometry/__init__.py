# SPDX-License-Identifier: MIT
"""Geometry generation, NURBS and export."""

import os
import sys

# 面片求解是小矩阵稠密运算：OpenBLAS/MKL 内部多线程在 200×200 量级矩阵上
# 全是同步开销，真正有效的并行层是 engine 自己的面片线程池。
# 环境变量只在 numpy 首次导入前生效；main.py 已在入口设置，
# 这里兜底覆盖「直接 import geometry」的场景（如测试）。用户显式设置优先。
if "numpy" not in sys.modules:
    for _blas in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(_blas, "1")

from .engine import generate_facets
from .mesh_export import facets_to_mesh, export_stl, export_obj
from .step_export import export_step, facets_to_step
from . import nurbs

__all__ = [
    "generate_facets",
    "facets_to_mesh",
    "export_stl",
    "export_obj",
    "export_step",
    "facets_to_step",
    "nurbs",
]
