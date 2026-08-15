"""pgt 安装包根。wheel 安装后位于 site-packages/pgt/。

把本目录插入 sys.path，使 ``import module_payload`` / ``import cli`` 等
顶层导入在安装后仍然有效（无需改业务代码）。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
