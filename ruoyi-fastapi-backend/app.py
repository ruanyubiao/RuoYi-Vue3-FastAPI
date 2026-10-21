import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

import uvicorn

from config.env import AppConfig
from server import create_app

_LOG = logging.getLogger(__name__)


def apply_process_layout() -> tuple[bool, int]:
    """多 worker 与内嵌采集、热重载冲突时降级，并写回环境变量。

    uvicorn 拉起的子进程会重新读配置。只改本进程内存不会传过去。
    load_dotenv 不覆盖已有环境变量，所以这里写入的值会保留。
    """
    workers = max(1, int(AppConfig.app_workers or 1))
    reload = bool(AppConfig.app_reload)
    if AppConfig.collector_embedded and workers > 1:
        _LOG.warning(
            'APP_WORKERS=%s 且采集内嵌已打开，改为 1 个 worker。内嵌采集只跟随这一个进程。',
            workers,
        )
        workers = 1
    elif workers > 1 and reload:
        _LOG.warning('APP_WORKERS=%s 与热重载不能同时使用，已关闭热重载。', workers)
        reload = False
    os.environ['APP_WORKERS'] = str(workers)
    os.environ['APP_RELOAD'] = 'true' if reload else 'false'
    AppConfig.app_workers = workers
    AppConfig.app_reload = reload
    return reload, workers


if __name__ != '__main__':
    app = create_app()

if __name__ == '__main__':
    _reload, _workers = apply_process_layout()
    uvicorn.run(
        app='server:create_app',
        host=AppConfig.app_host,
        port=AppConfig.app_port,
        root_path=AppConfig.app_root_path,
        reload=_reload,
        workers=_workers,
        factory=True,
    )
