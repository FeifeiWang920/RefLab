#!/usr/bin/env python3
"""MF Reflector entry point."""

from __future__ import annotations
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# 面片求解是小矩阵稠密运算，OpenBLAS 内部多线程在这里纯属同步开销；
# 并行层是 engine 自己的面片线程池。必须在 numpy 首次导入前设置。
# 用户显式设置的值优先。
for _blas in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_blas, "1")

from catia import detect_catia
from ui.main_window import run


def main() -> None:
    # Startup probe (also shown inside the UI)
    status = detect_catia()
    print(f"[CATIA] {status.state.value}: {status.message}")
    run()


if __name__ == "__main__":
    main()
