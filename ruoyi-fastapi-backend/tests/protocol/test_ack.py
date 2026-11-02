"""应答策略、等待队列与历史回写。"""

from __future__ import annotations

import json

from module_payload import redis_keys as rk
from module_payload.protocol.ack import MSG_NO_ERROR_ACK
from module_payload.protocol.ack_store import apply_rx, expire_pending, note_pending, patch_history
from module_payload.protocol.registry import load_bindings, resolve_ack_policy
from module_payload.protocol.xl.can.ack import XlCanAckPolicy
from module_payload.protocol.yj216.rs422.ack import MSG_NO_ENG_TM, Yj216Rs422AckPolicy
from module_payload.store.jsonutil import dumps_json


class MemRedis:
    """只实现应答存储用到的 List / Set。没有 eval，走 Python 回写。"""

    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.sets: dict[str, set[str]] = {}

    def lpush(self, key: str, *vals: str) -> int:
        lst = self.lists.setdefault(key, [])
        for val in vals:
            lst.insert(0, val)
        return len(lst)

    def rpop(self, key: str) -> str | None:
        lst = self.lists.get(key) or []
        if not lst:
            return None
        return lst.pop()

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = list(self.lists.get(key) or [])
        if end == -1:
            end = len(lst) - 1
        if end < 0 or start > end or not lst:
            return []
        return lst[start : end + 1]

    def rpush(self, key: str, *vals: str) -> int:
        lst = self.lists.setdefault(key, [])
        lst.extend(vals)
        return len(lst)

    def delete(self, *keys: str) -> int:
        n = 0
        for key in keys:
            if key in self.lists or key in self.sets:
                n += 1
            self.lists.pop(key, None)
            self.sets.pop(key, None)
        return n

    def sadd(self, key: str, *members: str) -> int:
        bucket = self.sets.setdefault(key, set())
        before = len(bucket)
        bucket.update(members)
        return len(bucket) - before

    def srem(self, key: str, *members: str) -> int:
        bucket = self.sets.setdefault(key, set())
        n = 0
        for member in members:
            if member in bucket:
                bucket.remove(member)
                n += 1
        return n

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key) or ())


def _push_hist(mem: MemRedis, source: str, cmd_id: str, **extra: object) -> None:
    entry = {'cmdId': cmd_id, 'ackStatus': 'pending', 'name': cmd_id}
    entry.update(extra)
    mem.lpush(rk.source_history_key(source), dumps_json(entry))


def _read_hist(mem: MemRedis, source: str) -> list[dict]:
    key = rk.source_history_key(source)
    return [json.loads(raw) for raw in mem.lrange(key, 0, -1)]


def test_bindings_only_xl_and_rs422() -> None:
    assert load_bindings('module_payload.protocol.xl.can').ack_policy is XlCanAckPolicy
    assert load_bindings('module_payload.protocol.yj216.rs422.tm').ack_policy is Yj216Rs422AckPolicy
    assert load_bindings('module_payload.protocol.biu.can').ack_policy is None
    assert load_bindings('module_payload.protocol.yj216.can').ack_policy is None
    assert isinstance(resolve_ack_policy({'assemblerId': 'can_xl'}), XlCanAckPolicy)
    assert resolve_ack_policy({'assemblerId': 'can_biu'}) is None
    assert resolve_ack_policy({'assemblerId': 'can_yj216'}) is None
    assert isinstance(resolve_ack_policy({'parserId': 'tm_yj216_rs422'}), Yj216Rs422AckPolicy)


def test_patch_history_finds_cmd_after_newer_push() -> None:
    mem = MemRedis()
    source = 'xl_can_a'
    _push_hist(mem, source, 'old')
    _push_hist(mem, source, 'new')
    assert patch_history(mem, source, 'old', {'ackStatus': 'ok', 'ackMessage': '应答成功'})
    rows = {row['cmdId']: row for row in _read_hist(mem, source)}
    assert rows['old']['ackStatus'] == 'ok'
    assert rows['new']['ackStatus'] == 'pending'


def test_same_corr_matches_oldest_only() -> None:
    mem = MemRedis()
    source = 'xl_can_a'
    corr = '0014:01'
    _push_hist(mem, source, 'first')
    _push_hist(mem, source, 'second')
    note_pending(mem, source, {'cmdId': 'first', 'expectAck': 'always', 'corrId': corr})
    note_pending(mem, source, {'cmdId': 'second', 'expectAck': 'always', 'corrId': corr})
    hit = XlCanAckPolicy().classify_rx(_AckMsg('telecommand_ack', '0014', 1))
    assert hit is not None
    assert apply_rx(mem, source, hit)
    rows = {row['cmdId']: row for row in _read_hist(mem, source)}
    assert rows['first']['ackStatus'] == 'ok'
    assert rows['second']['ackStatus'] == 'pending'
    assert apply_rx(mem, source, hit)
    rows = {row['cmdId']: row for row in _read_hist(mem, source)}
    assert rows['second']['ackStatus'] == 'ok'


def test_expire_always_and_on_error() -> None:
    mem = MemRedis()
    source = 'mix'
    _push_hist(mem, source, 'always-cmd')
    _push_hist(mem, source, 'quiet-cmd')
    note_pending(mem, source, {'cmdId': 'always-cmd', 'expectAck': 'always', 'corrId': 'a'})
    note_pending(mem, source, {'cmdId': 'quiet-cmd', 'expectAck': 'on_error', 'corrId': 'b'})
    assert expire_pending(mem, now_ms=10**15) == 2
    rows = {row['cmdId']: row for row in _read_hist(mem, source)}
    assert rows['always-cmd']['ackStatus'] == 'timeout'
    assert rows['always-cmd']['ackMessage'] == '应答超时'
    assert rows['quiet-cmd']['ackStatus'] == 'ok'
    assert rows['quiet-cmd']['ackMessage'] == MSG_NO_ERROR_ACK


def test_orphan_ack_does_not_create_history() -> None:
    mem = MemRedis()
    hit = Yj216Rs422AckPolicy().classify_rx(bytes.fromhex('EB90AA0001000000'))
    assert hit is not None
    assert apply_rx(mem, 'yj216-rs422', hit) is False
    assert _read_hist(mem, 'yj216-rs422') == []


def test_rs422_request_and_error_frame() -> None:
    policy = Yj216Rs422AckPolicy()
    described = policy.describe_send({'hex': 'EB 90 FF 00 00 00 FF'})
    assert described == {'expectAck': 'on_error', 'corrId': 'rs422:tm_req'}
    assert policy.describe_send({'hex': 'EB 90 01 00 01 02 00 03'})['expectAck'] == 'none'
    hit = policy.classify_rx(bytes.fromhex('EB90AA0001000000'))
    assert hit is not None
    assert hit.message == MSG_NO_ENG_TM
    assert policy.classify_rx(bytes.fromhex('EB90AA000200010000')) is None


def test_rs422_error_frame_does_not_enter_tm(monkeypatch) -> None:
    from module_payload.protocol.yj216.rs422.tm import Yj216Rs422TmIngest, clear_rx_sticky

    clear_rx_sticky()
    queued: list[object] = []
    monkeypatch.setattr(
        'module_payload.protocol.yj216.rs422.tm.enqueue_prepared_many',
        lambda *args, **kwargs: queued.append(args),
    )
    monkeypatch.setattr(
        'module_payload.store.session_store.get_session_sync',
        lambda *args, **kwargs: {'source': 'yj216-rs422'},
    )
    mem = MemRedis()
    source = 'yj216-rs422'
    _push_hist(mem, source, 'req')
    note_pending(
        mem,
        source,
        {'cmdId': 'req', 'expectAck': 'on_error', 'corrId': 'rs422:tm_req'},
    )
    result = Yj216Rs422TmIngest.ingest_bytes_sync(
        mem,
        bytes.fromhex('EB90AA0001000000'),
        src_param='serial:COM1',
    )
    assert result is None
    assert queued == []
    rows = _read_hist(mem, source)
    assert rows[0]['ackStatus'] == 'error'
    assert rows[0]['ackMessage'] == MSG_NO_ENG_TM


class _AckMsg:
    def __init__(self, kind: str, apid_hex: str, sec: int) -> None:
        self.data = bytes.fromhex('58 14 C0 00 00 01 01 2E')
        self.packet_param = {
            'msg_kind': kind,
            'ack_status': 'ok',
            'apid': int(apid_hex, 16),
            'sec_header': sec,
        }


def test_xl_gpcan_ack_roundtrip() -> None:
    from gpcan.protocol.xl import ProtocolBuilder, ProtocolParser
    from gpcan.sdk.can_sdk_def import CanRecvObj

    built = ProtocolBuilder().build_telecommand(bytes.fromhex('0A91000100015555'))
    policy = XlCanAckPolicy()
    described = policy.describe_send({'expect_ack': built.expect_ack, 'corr_id': built.corr_id})
    assert described['expectAck'] == 'always'
    apid_hex, sec_hex = described['corrId'].split(':')
    ack = ProtocolBuilder().build_ack(
        'telecommand',
        apid=int(apid_hex, 16),
        sec_header=int(sec_hex, 16),
    )
    assert ack is not None
    frames = []
    for frame in ack.frames:
        data = bytes(frame.str_data)
        frames.append(CanRecvObj(un_id=int(frame.un_id), str_data=data, un_data_len=len(data)))
    parser = ProtocolParser({})
    parser.feed(frames)
    msg = parser.get_msg()
    assert msg is not None
    hit = policy.classify_rx(msg)
    assert hit is not None
    assert hit.corr_id == described['corrId']
    assert hit.status == 'ok'
    assert policy.classify_rx(b'\x00\x01') is None
