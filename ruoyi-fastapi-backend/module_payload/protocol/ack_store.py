"""应答等待队列，以及按 cmdId 回写发送历史。

历史仍是 List。更新用 Lua 按 ``cmdId`` 查找再 ``LSET``，避免 ``LPUSH`` 把下标挤开。
同一 ``corrId`` 的等待队列是 FIFO：新记录从左侧入队，应答从右侧取出最老的一条。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from module_payload import redis_keys as rk
from module_payload.collectors.redis_cmd_helper import RedisOp
from module_payload.protocol.ack import (
    ACK_ERROR,
    ACK_OK,
    ACK_TIMEOUT,
    ACK_TIMEOUT_MS,
    EXPECT_ALWAYS,
    EXPECT_ON_ERROR,
    MSG_ACK_TIMEOUT,
    MSG_NO_ERROR_ACK,
    AckHit,
)
from module_payload.store.jsonutil import dumps_json

logger = logging.getLogger(__name__)

# 按 cmdId 合并字段。ARGV[1]=cmdId，ARGV[2]=补丁 JSON。
_PATCH_LUA = """
local cmdId = ARGV[1]
local patch = cjson.decode(ARGV[2])
local n = redis.call('LLEN', KEYS[1])
for i = 0, n - 1 do
  local raw = redis.call('LINDEX', KEYS[1], i)
  if raw then
    local ok, obj = pcall(cjson.decode, raw)
    if ok and type(obj) == 'table' and obj['cmdId'] == cmdId then
      for k, v in pairs(patch) do
        obj[k] = v
      end
      redis.call('LSET', KEYS[1], i, cjson.encode(obj))
      return 1
    end
  end
end
return 0
"""

# 弹出最老一条（RPOP）。空了就从索引集合去掉。
_RPOP_LUA = """
local raw = redis.call('RPOP', KEYS[1])
if not raw then
  redis.call('SREM', KEYS[2], KEYS[1])
  return false
end
if redis.call('LLEN', KEYS[1]) == 0 then
  redis.call('SREM', KEYS[2], KEYS[1])
end
return raw
"""

# 拆出已到期项并重写队列。ARGV[1]=now_ms。返回到期 JSON 数组。
_EXPIRE_LUA = """
local now = tonumber(ARGV[1])
local n = redis.call('LLEN', KEYS[1])
local keep = {}
local expired = {}
for i = 0, n - 1 do
  local raw = redis.call('LINDEX', KEYS[1], i)
  local ok, obj = pcall(cjson.decode, raw)
  local due = ok and type(obj) == 'table' and tonumber(obj['expireAt'] or 0) or 0
  if due <= now then
    table.insert(expired, raw)
  else
    table.insert(keep, raw)
  end
end
redis.call('DEL', KEYS[1])
for i = #keep, 1, -1 do
  redis.call('LPUSH', KEYS[1], keep[i])
end
if #keep == 0 then
  redis.call('SREM', KEYS[2], KEYS[1])
end
return expired
"""


def _now_ms() -> int:
    return int(time.time() * 1000)


def _ack_ts() -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S') + f'.{int(time.time() * 1000) % 1000:03d}'


def _text(value: Any) -> str:
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


def _loads(raw: Any) -> dict[str, Any] | None:
    import json

    text = _text(raw)
    if not text:
        return None
    try:
        obj = json.loads(text)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _redis_call(redis: Any, name: str, *args: Any) -> Any:
    """优先走采集封装上的同名方法，否则打到底层 client。"""
    fn = getattr(redis, name, None)
    if callable(fn):
        return fn(*args)
    client = getattr(redis, '_client', None)
    fn = getattr(client, name, None) if client is not None else None
    if callable(fn):
        return fn(*args)
    raise AttributeError(name)


def _flush(redis: Any) -> None:
    flush = getattr(redis, 'flush', None)
    if callable(flush):
        flush()


def _can_eval(redis: Any) -> bool:
    client = getattr(redis, '_client', redis)
    return callable(getattr(client, 'eval', None)) or callable(getattr(redis, 'eval', None))


def _eval(redis: Any, script: str, numkeys: int, *args: Any) -> Any:
    _flush(redis)
    eval_fn = getattr(redis, 'eval', None)
    if callable(eval_fn):
        return eval_fn(script, numkeys, *args)
    client = getattr(redis, '_client', None)
    return client.eval(script, numkeys, *args)


def _list_items(redis: Any, key: str) -> list[str]:
    raw = _redis_call(redis, 'lrange', key, 0, -1) or []
    return [_text(x) for x in raw]


def _replace_list(redis: Any, key: str, items: list[str]) -> None:
    _redis_call(redis, 'delete', key)
    if items:
        _redis_call(redis, 'rpush', key, *items)


def patch_history(redis: Any, source: str, cmd_id: str, fields: dict[str, Any]) -> bool:
    """按 cmdId 更新该来源历史中的一条。找到返回 True。"""
    if not source or not cmd_id:
        return False
    key = rk.source_history_key(source)
    payload = dumps_json(fields)
    if _can_eval(redis):
        try:
            return int(_eval(redis, _PATCH_LUA, 1, key, cmd_id, payload) or 0) == 1
        except Exception:
            logger.exception('应答历史 Lua 更新失败，改为整表重写 source=%s', source)
    import json

    patch = json.loads(payload)
    found = False
    out: list[str] = []
    for raw in _list_items(redis, key):
        obj = _loads(raw)
        if obj is not None and not found and str(obj.get('cmdId') or '') == cmd_id:
            obj.update(patch)
            out.append(dumps_json(obj))
            found = True
        else:
            out.append(raw)
    if not found:
        return False
    _replace_list(redis, key, out)
    return found


def note_pending(redis: Any, source: str, entry: dict[str, Any]) -> None:
    """线发成功且需要应答时，把 cmdId 放进 FIFO。调用方应已把历史写入缓冲。"""
    corr = str(entry.get('corrId') or '')
    cmd_id = str(entry.get('cmdId') or '')
    expect = str(entry.get('expectAck') or '')
    if not source or not corr or not cmd_id or expect not in (EXPECT_ALWAYS, EXPECT_ON_ERROR):
        return
    key = rk.ack_pending_key(source, corr)
    item = dumps_json(
        {
            'cmdId': cmd_id,
            'expectAck': expect,
            'expireAt': _now_ms() + ACK_TIMEOUT_MS,
            'source': source,
        }
    )
    write = getattr(redis, 'write_batch', None)
    if callable(write):
        write(
            [
                RedisOp('lpush', (key, item)),
                RedisOp('sadd', (rk.ack_pending_index_key(), key)),
            ]
        )
        _flush(redis)
        return
    _redis_call(redis, 'lpush', key, item)
    _redis_call(redis, 'sadd', rk.ack_pending_index_key(), key)


def _pop_oldest(redis: Any, source: str, corr_id: str) -> dict[str, Any] | None:
    key = rk.ack_pending_key(source, corr_id)
    index = rk.ack_pending_index_key()
    raw: Any = None
    if _can_eval(redis):
        try:
            raw = _eval(redis, _RPOP_LUA, 2, key, index)
        except Exception:
            logger.exception('应答队列 Lua 弹出失败 source=%s', source)
            raw = None
    else:
        raw = _redis_call(redis, 'rpop', key)
        if not _list_items(redis, key):
            _redis_call(redis, 'srem', index, key)
    if raw in (None, False, b'', ''):
        return None
    return _loads(raw)


def apply_rx(redis: Any, source: str, hit: AckHit) -> bool:
    """把一帧应答配到该 corrId 最老的发送。没有等待中的发送则只记日志。"""
    if not source or hit is None or not hit.corr_id:
        return False
    pending = _pop_oldest(redis, source, hit.corr_id)
    if pending is None:
        logger.info('未匹配的应答 source=%s corr=%s hex=%s', source, hit.corr_id, hit.hex_text)
        return False
    status = ACK_OK if hit.status == ACK_OK else ACK_ERROR
    fields = {
        'ackStatus': status,
        'ackMessage': hit.message or (MSG_ACK_OK if status == ACK_OK else ''),
        'ackHex': hit.hex_text or '',
        'ackTs': _ack_ts(),
    }
    cmd_id = str(pending.get('cmdId') or '')
    if not patch_history(redis, source, cmd_id, fields):
        logger.info('应答未写回历史 source=%s cmdId=%s', source, cmd_id)
        return False
    return True


def _finish_expired(redis: Any, item: dict[str, Any]) -> None:
    expect = str(item.get('expectAck') or '')
    source = str(item.get('source') or '')
    cmd_id = str(item.get('cmdId') or '')
    if expect == EXPECT_ON_ERROR:
        fields = {
            'ackStatus': ACK_OK,
            'ackMessage': MSG_NO_ERROR_ACK,
            'ackHex': '',
            'ackTs': _ack_ts(),
        }
    else:
        fields = {
            'ackStatus': ACK_TIMEOUT,
            'ackMessage': MSG_ACK_TIMEOUT,
            'ackHex': '',
            'ackTs': _ack_ts(),
        }
    patch_history(redis, source, cmd_id, fields)


def expire_pending(redis: Any, *, now_ms: int | None = None) -> int:
    """处理已到时的等待。返回结案条数。"""
    now = _now_ms() if now_ms is None else int(now_ms)
    index = rk.ack_pending_index_key()
    try:
        keys = _redis_call(redis, 'smembers', index) or []
    except Exception:
        return 0
    done = 0
    for key in keys:
        key_text = _text(key)
        expired: list[Any] = []
        if _can_eval(redis):
            try:
                expired = list(_eval(redis, _EXPIRE_LUA, 2, key_text, index, str(now)) or [])
            except Exception:
                logger.exception('应答超时 Lua 失败 key=%s', key_text)
                expired = []
        else:
            kept: list[str] = []
            for raw in _list_items(redis, key_text):
                obj = _loads(raw)
                due = int((obj or {}).get('expireAt') or 0)
                if obj is not None and due <= now:
                    expired.append(raw)
                else:
                    kept.append(raw)
            _replace_list(redis, key_text, kept)
            if not kept:
                _redis_call(redis, 'srem', index, key_text)
        for raw in expired:
            obj = _loads(raw)
            if obj is None:
                continue
            _finish_expired(redis, obj)
            done += 1
    return done
