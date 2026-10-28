"""定时最近发送：按协议族隔离；关闭后再打开不因命名冲突崩溃。"""

from __future__ import annotations

from unittest.mock import MagicMock

from module_payload.collectors.can_collector import CanCollector
from module_payload import redis_keys as rk


def _collector():
    c = CanCollector.__new__(CanCollector)
    c.device_id = 'can:3:0'
    c._timed_tm = True
    c._timed_tm_family = 'yj216'
    c._timed_sync = True
    c._timed_sync_family = 'yj216'
    c._timed_tm_last_send = {'yj216': '2026-10-28 09:38:49.700'}
    c._timed_tm_last_can_label = {'yj216': 'CAN-A'}
    c._timed_sync_last_send = {'yj216': '2026-10-28 09:39:52.916'}
    c._timed_sync_last_can_label = {'yj216': 'CAN-A'}
    # 轮询通道 index（与 label 字典不得同名冲突）
    c._timed_sync_last_can = 0
    c._timed_tm_prefer_can = None
    c._channels = {}
    c._gnss_valid = True
    c._start_utc = {'yj216': '', 'biu': '', 'xl': ''}
    c._redis = MagicMock()
    return c


def test_timer_status_key_is_per_family():
    yj = rk.timer_status_key('can:3:0', 'yj216')
    xl = rk.timer_status_key('can:3:0', 'xl')
    assert yj.endswith(':dev:can:3:0:timer:yj216:status')
    assert xl.endswith(':dev:can:3:0:timer:xl:status')
    assert yj != xl


def test_timer_status_fields_isolated_by_family():
    c = _collector()
    yj = c._timer_status_fields('yj216')
    assert yj['timedTmLastSend'] == '2026-10-28 09:38:49.700'
    assert yj['timedTmLastCan'] == 'CAN-A'
    assert yj['timeSyncLastSend'] == '2026-10-28 09:39:52.916'
    assert yj['timeSyncLastCan'] == 'CAN-A'
    xl = c._timer_status_fields('xl')
    assert xl['timedTmLastSend'] == ''
    assert xl['timeSyncLastSend'] == ''


def test_mark_timed_send_writes_family_key():
    c = _collector()
    c._timed_tm_last_send = {}
    c._timed_tm_last_can_label = {}
    c._redis.write_batch = MagicMock()
    c._mark_timed_send('timed_tm', 'yj216', 'CAN-A')
    assert c._timed_tm_last_send['yj216']
    assert c._timed_tm_last_can_label['yj216'] == 'CAN-A'
    ops = c._redis.write_batch.call_args[0][0]
    assert ops[0].args[0] == rk.timer_status_key(c.device_id, 'yj216')


def test_mark_timed_sync_does_not_leak_to_other_family():
    c = _collector()
    c._timed_sync_last_send = {'yj216': 'old'}
    c._timed_sync_last_can_label = {'yj216': 'CAN-A'}
    c._redis.write_batch = MagicMock()
    c._mark_timed_send('timed_sync', 'xl', 'CAN-B')
    assert c._timed_sync_last_send['xl']
    assert c._timed_sync_last_can_label['xl'] == 'CAN-B'
    assert c._timed_sync_last_send['yj216'] == 'old'


def test_close_sync_sets_round_robin_none_fields_still_ok():
    """关闭定时同步会把 _timed_sync_last_can(轮询 index) 置 None；label 字典须独立，.get 不崩。"""
    c = _collector()
    ch = {'cfg': {'cable_flag': 0}, 'channel_device_id': 'can:3:0:0'}
    # close broadcast (same as _handle_timer timed_sync enable=False)
    c._timed_sync_last_can = None
    out = c._handle_timer(ch, {'kind': 'timed_sync', 'enable': False, 'family': 'yj216'})
    assert out['success'] is True
    assert out['timeSyncLastSend'] == '2026-10-28 09:39:52.916'
    # reopen
    out2 = c._handle_timer(ch, {'kind': 'timed_sync', 'enable': True, 'family': 'yj216'})
    assert out2['success'] is True
    fields = c._timer_status_fields('yj216')
    assert fields['timeSyncLastCan'] == 'CAN-A'


def test_close_reopen_timed_tm_ok():
    c = _collector()
    ch = {'cfg': {'cable_flag': 0}, 'channel_device_id': 'can:3:0:0'}
    c._channels = {0: ch}
    out = c._handle_timer(ch, {'kind': 'timed_tm', 'enable': False, 'family': 'yj216'})
    assert out['success'] is True
    out2 = c._handle_timer(ch, {'kind': 'timed_tm', 'enable': True, 'family': 'yj216'})
    assert out2['success'] is True
    assert 'NoneType' not in str(out2.get('message', ''))
