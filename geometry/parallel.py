# SPDX-License-Identifier: MIT
"""面片级并行执行原语。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os

import logging




logger = logging.getLogger(__name__)



def _facet_worker_count(n_tasks: int) -> int:
    """Independent facet solves share a pool; LAPACK / NumPy release the GIL."""
    if n_tasks <= 1:
        return 1
    env = os.environ.get("MF_REFLECTOR_JOBS", "").strip()
    if env:
        try:
            return max(1, min(n_tasks, int(env)))
        except ValueError:
            logger.warning(
                "MF_REFLECTOR_JOBS=%r 不是有效整数，已忽略（使用全部 CPU 核心）", env
            )
    return max(1, min(n_tasks, os.cpu_count() or 1))


def _parallel_map(fn, items):
    items = list(items)

    def run_one(item):
        try:
            return fn(item)
        except Exception as exc:
            ctx = f"facet {item}" if isinstance(item, tuple) else repr(item)
            raise RuntimeError(f"面片求解失败（{ctx}）: {exc}") from exc

    workers = _facet_worker_count(len(items))
    if workers <= 1:
        return [run_one(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run_one, items))
