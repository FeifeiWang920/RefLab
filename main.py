#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""RefLab entry point."""

from __future__ import annotations
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# BLAS 单线程：小矩阵稠密求解下多线程 BLAS 只有同步开销（真正的并行在面片线程池）。
# 必须在 numpy 首次导入前设置——ui.main_window 先 import models（触发 numpy），
# geometry/__init__.py 的兜底只覆盖直接 import geometry 的场景。用户显式设置优先。
for _blas in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_blas, "1")

from catia import detect_catia
from ui.main_window import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger(__name__)
    try:
        from importlib.metadata import version

        logger.info("RefLab %s", version("reflab"))
    except Exception:
        pass  # 未以包形式安装（直接 python main.py）时没有发行版元数据
    # Startup probe (also shown inside the UI)
    status = detect_catia()
    logger.info("[CATIA] %s: %s", status.state.value, status.message)
    run()


if __name__ == "__main__":
    main()
