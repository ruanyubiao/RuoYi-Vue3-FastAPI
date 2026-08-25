"""遥测单字段计算调试：parse_line_hex + Redis 历史。"""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis

from exceptions.exception import ServiceException
from module_payload import redis_keys as rk
from module_payload.constants import HISTORY_MAX
from module_payload.parsers.tm_field_util import line_to_field_dict
from module_payload.service.payload_config_service import PayloadConfigService


class PayloadTmCalcService:
    """调试菜单「遥测计算」：按表/字段解析 Hex，结果写入 Redis 历史。"""

    @classmethod
    def _find_row_cfg(cls, table_type: str, field_id: str) -> dict[str, Any] | None:
        table_def = PayloadConfigService.get_telemetry_table_def(table_type)
        fid = (field_id or '').strip()
        if not fid:
            return None
        for row in table_def.get('row') or []:
            if str(row.get('id') or '') == fid:
                return row if isinstance(row, dict) else None
        return None

    @classmethod
    def _field_byte_len(cls, row_cfg: dict[str, Any]) -> int:
        """按 bits 推算字段占用字节数（向上取整，至少 1）。"""
        try:
            bits = int(row_cfg.get('bits') or 0)
        except (TypeError, ValueError):
            bits = 0
        if bits <= 0:
            return 1
        return max(1, (bits + 7) // 8)

    @classmethod
    def _hex_to_bytes(cls, hex_text: str) -> bytes:
        from module_payload.cfg.hex_text import hex_to_bytes

        try:
            return hex_to_bytes(hex_text)
        except ValueError as e:
            raise ServiceException(message=f'Hex 格式错误: {e}') from e

    @classmethod
    def _pad_field_hex(cls, hex_text: str, row_cfg: dict[str, Any], *, pad_tail: bool) -> str:
        """
        按字段字节长度补 00。
        例：需 4 字节、输入 33 01 02 →
          前补零: 00 33 01 02；后补零: 33 01 02 00
        """
        raw = cls._hex_to_bytes(hex_text)
        need = cls._field_byte_len(row_cfg)
        if need <= 0 or len(raw) >= need:
            data = raw
        else:
            pad = b'\x00' * (need - len(raw))
            data = raw + pad if pad_tail else pad + raw
        return ' '.join(f'{b:02X}' for b in data)

    @classmethod
    def _parse_line(cls, row_cfg: dict[str, Any], hex_text: str) -> Any:
        from TeleMetryParser import parse_line_hex

        # 单字段 Hex（与遥测表 HEX 列一致）时 bytepos 相对于本段缓冲，置 0
        cfg = copy.deepcopy(row_cfg)
        cfg['bytepos'] = 0
        return parse_line_hex(cfg, hex_text)

    @classmethod
    async def get_history(cls, redis: aioredis.Redis, limit: int = HISTORY_MAX) -> list[dict[str, Any]]:
        n = max(1, min(int(limit or HISTORY_MAX), HISTORY_MAX))
        items = await redis.lrange(rk.tm_calc_history_key(), 0, n - 1)
        out: list[dict[str, Any]] = []
        for raw in items:
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out

    @classmethod
    async def clear_history(cls, redis: aioredis.Redis) -> None:
        await redis.delete(rk.tm_calc_history_key())

    @classmethod
    async def calculate(
        cls,
        redis: aioredis.Redis,
        *,
        table_type: str,
        field_id: str,
        hex_text: str,
        pad_tail: bool = True,
    ) -> dict[str, Any]:
        tkey = (table_type or '').strip().upper()
        fid = (field_id or '').strip()
        hx = (hex_text or '').strip()
        if not tkey:
            raise ServiceException(message='请选择遥测表')
        if not fid:
            raise ServiceException(message='请选择遥测量')
        if not hx:
            raise ServiceException(message='请输入 Hex 文本')

        row_cfg = cls._find_row_cfg(tkey, fid)
        if row_cfg is None:
            raise ServiceException(message=f'字段不存在: 表[{tkey}] 字段[{fid}]')

        padded_hex = cls._pad_field_hex(hx, row_cfg, pad_tail=bool(pad_tail))

        try:
            ln = cls._parse_line(row_cfg, padded_hex)
        except ServiceException:
            raise
        except Exception as e:
            raise ServiceException(message=f'解析失败: {e}') from e

        parse_err = bool(getattr(ln, 'err', False))
        field = line_to_field_dict(ln, unit=row_cfg.get('unit') or getattr(ln, 'unit', '') or '')
        field['id'] = fid
        if row_cfg.get('name'):
            field['name'] = row_cfg.get('name') or field['name']

        now = datetime.now()
        entry = {
            'id': field['id'],
            'name': field['name'],
            'value': field.get('calc_val', field.get('value')),
            'show': field.get('show', ''),
            'calc_val': field.get('calc_val'),
            'unit': field.get('unit', ''),
            'hex': field.get('hex') or padded_hex,
            'inputHex': hx,
            'paddedHex': padded_hex,
            'padTail': bool(pad_tail),
            'ts': now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
            'tableType': tkey,
            'cfg': row_cfg,
            'err': parse_err,
        }

        dumped = json.dumps(entry, ensure_ascii=False, default=str)
        key = rk.tm_calc_history_key()
        await redis.lpush(key, dumped)
        await redis.ltrim(key, 0, HISTORY_MAX - 1)

        history = await cls.get_history(redis)
        return {
            'row': entry,
            'history': history,
            'err': parse_err,
            'warnMsg': '解析失败: 字段解析返回错误' if parse_err else '',
        }
