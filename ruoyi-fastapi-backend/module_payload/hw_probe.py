"""硬件枚举探测：带超时，避免 gpcan / pyserial 阻塞 FastAPI 与 E2E。"""

from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from typing import TypeVar

from utils.log_util import logger

T = TypeVar('T')

# 枚举 CAN 卡、系统串口时允许的最长等待（秒）
HW_PROBE_TIMEOUT_SEC = 5.0


def call_with_timeout(fn: Callable[[], T], timeout: float = HW_PROBE_TIMEOUT_SEC, *, label: str = 'hw_probe') -> T:
    """在线程中执行阻塞探测；超时则抛 TimeoutError（不等待卡死线程结束）。"""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as e:
        logger.warning(f'{label} 超时 ({timeout}s)，使用降级结果')
        pool.shutdown(wait=False, cancel_futures=True)
        raise TimeoutError(f'{label} timed out after {timeout}s') from e
    except Exception:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
