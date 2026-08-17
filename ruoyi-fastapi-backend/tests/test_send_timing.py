"""send_timing 追踪文件写入。"""

import json
import time

from module_payload.collectors.send_timing import mark, start_trace, trace_file_path


def test_trace_writes_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(
        'module_payload.collectors.send_timing.get_logs_data_dir',
        lambda: tmp_path,
        raising=False,
    )
    # patch via trace_file_path dependency
    import module_payload.collectors.send_timing as st

    monkeypatch.setattr(st, 'trace_file_path', lambda: tmp_path / 'can_send_timing.jsonl')

    tid = 'test-trace-1'
    start_trace(tid, label='xl.timedTm.enable')
    mark(tid, 'api.redis.lpush.done', pushMs=1.2)
    mark(tid, 'collector.can.send_msg.done', ms=980.5, tick=0)

    path = tmp_path / 'can_send_timing.jsonl'
    assert path.is_file()
    lines = [json.loads(x) for x in path.read_text(encoding='utf-8').strip().splitlines()]
    assert lines[0]['stage'] == 'trace.start'
    assert lines[-1]['stage'] == 'collector.can.send_msg.done'
    assert lines[-1]['sinceStartMs'] >= 0
