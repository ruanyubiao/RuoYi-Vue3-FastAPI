"""采集监工入口。与 app.py 同级。

python app_collector.py [--host 标识] [--env 环境]
--host 标识：采集机标识，覆盖环境变量 COLLECTOR_HOST
--env 环境：环境配置文件，覆盖环境变量 COLLECTOR_ENV
不传 --host 时，默认读取环境变量 COLLECTOR_HOST
不传 --env 时，默认读取环境变量 COLLECTOR_ENV。
不传 --host 和 --env 时，默认读取环境变量 COLLECTOR_HOST 和 COLLECTOR_ENV。

python app_collector.py
python app_collector.py --host box-a
python app_collector.py --env=dev --host box-a

"""

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)


def main() -> None:
    """解析 --host 后启动监工。--env 由 config.env 解析，不传时用 .env.prod。"""
    parser = argparse.ArgumentParser(description='采集监工')
    parser.add_argument('--host', default='', help='采集机标识，覆盖环境变量 COLLECTOR_HOST')
    args, _unknown = parser.parse_known_args()
    host = str(args.host or '').strip()
    if host:
        from module_payload.collector_host import normalize_collector_host

        if normalize_collector_host(host) != host:
            raise SystemExit(f'非法采集机标识: {host}（只允许字母、数字、下划线和连字符）')
        os.environ['COLLECTOR_HOST'] = host
    from module_payload.collectors.supervisor import serve

    try:
        serve()
    except KeyboardInterrupt:
        raise SystemExit(0) from None


if __name__ == '__main__':
    main()
