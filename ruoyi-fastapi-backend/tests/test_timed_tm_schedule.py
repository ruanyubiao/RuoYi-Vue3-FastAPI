"""定时遥测顺序、定时广播通道轮询、控制 op 解析。"""

from module_payload.collectors.can_timers import next_round_robin_can, parse_timer_op
from module_payload.collectors.timed_tm import next_biu_tm_data_code, next_xl_tm_sec_header


def test_biu_odd_ticks_always_type1():
    for tick in range(0, 20, 2):
        assert next_biu_tm_data_code(tick) == 0xFF


def test_biu_even_ticks_rotate_2_to_5():
    codes = [next_biu_tm_data_code(t) for t in range(1, 9, 2)]
    assert codes == [0xFD, 0xFB, 0xF9, 0xF7]


def test_biu_sequence_first_eight():
    assert [next_biu_tm_data_code(t) for t in range(8)] == [
        0xFF,
        0xFD,
        0xFF,
        0xFB,
        0xFF,
        0xF9,
        0xFF,
        0xF7,
    ]


def test_xl_every_fifth_is_slow():
    headers = [next_xl_tm_sec_header(t) for t in range(10)]
    assert headers == [0x01, 0x01, 0x01, 0x01, 0x02, 0x01, 0x01, 0x01, 0x01, 0x02]


def test_round_robin_empty_stops():
    assert next_round_robin_can([], None) is None
    assert next_round_robin_can([], 0) is None


def test_round_robin_only_a():
    assert next_round_robin_can([0], None) == 0
    assert next_round_robin_can([0], 0) == 0


def test_round_robin_only_b():
    assert next_round_robin_can([1], None) == 1
    assert next_round_robin_can([1], 1) == 1


def test_round_robin_a_then_b_then_a():
    assert next_round_robin_can([0, 1], None) == 0
    assert next_round_robin_can([0, 1], 0) == 1
    assert next_round_robin_can([0, 1], 1) == 0


def test_round_robin_b_opens_after_only_a():
    """只开 A 时一直用 A；B 随后打开，上次是 A，下次取列表中 A 的下一个 = B。"""
    last = 0
    assert next_round_robin_can([0], last) == 0
    assert next_round_robin_can([0, 1], last) == 1


def test_round_robin_close_one_of_two():
    """双开后关掉上次通道：从剩余列表里找下一个。"""
    assert next_round_robin_can([1], 0) == 1
    assert next_round_robin_can([0], 1) == 0


def test_round_robin_wrap_when_last_is_tail():
    assert next_round_robin_can([0, 1], 1) == 0
    assert next_round_robin_can([2, 5, 9], 9) == 2


def test_pick_timed_tm_prefers_selected():
    from module_payload.collectors.can_timers import pick_timed_tm_can

    assert pick_timed_tm_can([0, 1], 1) == 1
    assert pick_timed_tm_can([0, 1], 0) == 0
    assert pick_timed_tm_can([1], 0) == 1
    assert pick_timed_tm_can([0, 1], 0) == 0
    assert pick_timed_tm_can([], 0) is None


def test_pick_timed_tm_reopen_prefer():
    from module_payload.collectors.can_timers import pick_timed_tm_can

    prefer = 0
    assert pick_timed_tm_can([1], prefer) == 1
    assert pick_timed_tm_can([0, 1], prefer) == 0


def test_can_port_label():
    from module_payload.collectors.can_timers import can_port_label

    assert can_port_label(0, 0) == 'CAN-A'
    assert can_port_label(1, 1) == 'CAN-B'
    assert can_port_label(0) == 'CAN-A'
    assert can_port_label(1) == 'CAN-B'


def test_parse_timer_set_offset():
    cmd = parse_timer_op('biu.timeSync.setOffset', {'offsetMs': 12})
    assert cmd == {'kind': 'set_offset', 'offsetMs': 12, 'family': 'biu'}
    cmd = parse_timer_op('xl.timeSync.set_offset', {'offset_ms': -3})
    assert cmd == {'kind': 'set_offset', 'offsetMs': -3, 'family': 'xl'}


def test_parse_timer_set_start_and_broadcast():
    start = parse_timer_op('biu.timeSync.setStart', {'utc': '2026-08-17 01:00:00'})
    assert start['kind'] == 'set_start'
    assert start['utc'] == '2026-08-17 01:00:00'
    assert start['family'] == 'biu'
    bc = parse_timer_op('xl.timeSync.broadcast', {'enable': True, 'gnssValid': False})
    assert bc == {'kind': 'timed_sync', 'enable': True, 'gnssValid': False, 'family': 'xl'}


def test_parse_timer_get_status():
    assert parse_timer_op('biu.timeSync.get', {}) == {'kind': 'get_status', 'family': 'biu'}
    assert parse_timer_op('xl.timeSync.get', {})['family'] == 'xl'


def test_parse_timer_tm_enable_keeps_family():
    assert parse_timer_op('xl.timedTm.enable', {'enable': True}) == {
        'kind': 'timed_tm',
        'enable': True,
        'family': 'xl',
    }
    assert parse_timer_op('biu.timedTm.enable', {'enable': False})['family'] == 'biu'


def test_parse_timer_reported_ops():
    assert parse_timer_op('biu.timeSync.setStart', {'utc': '2026-08-17 01:14:09'})['kind'] == 'set_start'
    assert parse_timer_op('xl.timeSync.setStart', {'utc': 'x'})['kind'] == 'set_start'
    assert parse_timer_op('xl.timeSync.setOffset', {'offsetMs': 1})['kind'] == 'set_offset'
    assert parse_timer_op('biu.timeSync.setOffset', {'offsetMs': 1})['kind'] == 'set_offset'
    assert parse_timer_op('xl.timeSync.resetStart', {})['kind'] == 'reset_start'
    assert parse_timer_op('biu.timeSync.resetStart', {})['kind'] == 'reset_start'


def test_utc_floor_sec():
    from datetime import datetime, timezone

    from module_payload.collectors.can_timers import utc_to_epoch_ms_floor_sec

    ms = utc_to_epoch_ms_floor_sec('2026-08-17 01:14:09')
    assert ms % 1000 == 0
    expect = int(datetime(2026, 8, 17, 1, 14, 9, tzinfo=timezone.utc).timestamp()) * 1000
    assert ms == expect


def test_time_sync_manager_isolates_protocols():
    from gpcan import TimeSyncManager, CanProtocolType
    from module_payload.collectors.can_timers import time_sync_for_family

    TimeSyncManager.reset()
    biu = time_sync_for_family('biu')
    xl = time_sync_for_family('xl')
    assert biu is time_sync_for_family('biu')
    assert biu is not xl
    biu.set_offset(11)
    xl.set_offset(22)
    assert time_sync_for_family('biu').offset_ms == 11
    assert time_sync_for_family('xl').offset_ms == 22
    assert TimeSyncManager.find(CanProtocolType.BIU) is biu
    TimeSyncManager.reset()


def test_parse_timer_unknown_is_none():
    assert parse_timer_op('biu.timeSync.unknown', {}) is None
    assert parse_timer_op('foo.timeSync.setOffset', {}) is None
