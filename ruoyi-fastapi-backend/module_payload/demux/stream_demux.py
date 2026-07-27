"""流式拆帧分流：按路由表从混流中取出完整帧并标注下游组装器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _parse_hex_bytes(value: Any, *, field_name: str = 'hex') -> bytes:
    if value is None:
        raise ValueError(f'{field_name} 不能为空')
    if isinstance(value, (bytes, bytearray, memoryview)):
        out = bytes(value)
        if not out:
            raise ValueError(f'{field_name} 不能为空')
        return out
    s = str(value).strip().replace(' ', '').replace('0x', '').replace('0X', '')
    if not s:
        raise ValueError(f'{field_name} 不能为空')
    if len(s) % 2:
        s = '0' + s
    try:
        return bytes.fromhex(s)
    except ValueError as e:
        raise ValueError(f'{field_name} 非法十六进制: {value!r}') from e


def _parse_type_byte(value: Any) -> int | None:
    if value is None or value == '':
        return None
    if isinstance(value, int):
        return value & 0xFF
    s = str(value).strip()
    if s.lower().startswith('0x'):
        return int(s, 16) & 0xFF
    if all(c in '0123456789abcdefABCDEF' for c in s) and len(s) <= 2:
        return int(s, 16) & 0xFF
    return int(s, 0) & 0xFF


@dataclass(slots=True)
class DemuxRoute:
    """一条分流规则。"""

    id: str
    framing: str
    header: bytes
    assembler_id: str
    parser_id: str = ''
    frame_size: int | None = None
    trailers: tuple[bytes, ...] = ()
    type_at: int | None = None
    type_value: int | None = None
    max_frame_size: int = 1 << 16
    min_frame_size: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DemuxRoute:
        rid = str(raw.get('id') or raw.get('assemblerId') or 'route').strip()
        framing = str(raw.get('framing') or '').strip().lower().replace('-', '_')
        aliases = {
            'header_len': 'header_len',
            'fixed_header_len': 'header_len',
            'header_trailer': 'header_trailer',
            'fixed_header_trailer': 'header_trailer',
            'header_len_trailer': 'header_len_trailer',
            'fixed_header_len_trailer': 'header_len_trailer',
        }
        framing = aliases.get(framing, framing)
        if framing not in ('header_len', 'header_trailer', 'header_len_trailer'):
            raise ValueError(f'未知 framing: {raw.get("framing")!r}')

        header = _parse_hex_bytes(raw.get('header'), field_name='header')
        assembler_id = str(raw.get('assemblerId') or raw.get('assembler_id') or '').strip()
        if not assembler_id:
            raise ValueError(f'route {rid} 缺少 assemblerId')

        frame_size = raw.get('frameSize', raw.get('frame_size'))
        frame_size_i = int(frame_size) if frame_size is not None else None

        trailers_raw = raw.get('trailers')
        trailer_one = raw.get('trailer')
        ends: list[bytes] = []
        if trailer_one is not None:
            ends.append(_parse_hex_bytes(trailer_one, field_name='trailer'))
        if trailers_raw:
            for i, t in enumerate(trailers_raw):
                ends.append(_parse_hex_bytes(t, field_name=f'trailers[{i}]'))

        type_at = raw.get('typeAt', raw.get('type_at'))
        type_at_i = int(type_at) if type_at is not None and type_at != '' else None
        type_value = _parse_type_byte(raw.get('type', raw.get('typeValue', raw.get('type_value'))))

        max_frame = int(raw.get('maxFrameSize', raw.get('max_frame_size', 1 << 16)))
        min_frame = raw.get('minFrameSize', raw.get('min_frame_size'))
        min_frame_i = int(min_frame) if min_frame is not None else None

        if framing == 'header_len':
            if frame_size_i is None or frame_size_i < len(header):
                raise ValueError(f'route {rid}: header_len 需要有效 frameSize')
        elif framing == 'header_len_trailer':
            if frame_size_i is None or not ends:
                raise ValueError(f'route {rid}: header_len_trailer 需要 frameSize 与 trailers')
            tlen = len(ends[0])
            if any(len(t) != tlen for t in ends):
                raise ValueError(f'route {rid}: trailers 长度须一致')
            if frame_size_i < len(header) + tlen:
                raise ValueError(f'route {rid}: frameSize 过小')
        elif framing == 'header_trailer':
            if not ends:
                raise ValueError(f'route {rid}: header_trailer 需要 trailer/trailers')
            if len(ends) != 1:
                # 变长搜尾仅支持单尾；多尾取第一个并允许后续扩展
                ends = ends[:1]

        return cls(
            id=rid,
            framing=framing,
            header=header,
            assembler_id=assembler_id,
            parser_id=str(raw.get('parserId') or raw.get('parser_id') or '').strip(),
            frame_size=frame_size_i,
            trailers=tuple(ends),
            type_at=type_at_i,
            type_value=type_value,
            max_frame_size=max_frame,
            min_frame_size=min_frame_i,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            'id': self.id,
            'framing': self.framing,
            'header': self.header.hex().upper(),
            'assemblerId': self.assembler_id,
            'parserId': self.parser_id,
        }
        if self.frame_size is not None:
            d['frameSize'] = self.frame_size
        if self.trailers:
            d['trailers'] = [t.hex().upper() for t in self.trailers]
        if self.type_at is not None:
            d['typeAt'] = self.type_at
        if self.type_value is not None:
            d['type'] = f'{self.type_value:02X}'
        if self.framing == 'header_trailer':
            d['maxFrameSize'] = self.max_frame_size
            if self.min_frame_size is not None:
                d['minFrameSize'] = self.min_frame_size
        return d

    def type_matches(self, frame: bytes) -> bool:
        if self.type_at is None or self.type_value is None:
            return True
        if self.type_at < 0 or self.type_at >= len(frame):
            return False
        return frame[self.type_at] == self.type_value

    @property
    def specificity(self) -> int:
        """匹配优先级：有 type 过滤的更具体。"""
        score = 0
        if self.type_at is not None and self.type_value is not None:
            score += 10
        if self.framing == 'header_len_trailer':
            score += 2
        elif self.framing == 'header_len':
            score += 1
        return score


@dataclass(slots=True)
class DemuxHit:
    assembler_id: str
    frame: bytes
    route_id: str
    parser_id: str = ''
    route: DemuxRoute | None = field(default=None, repr=False)


_NEED_MORE = object()
_SKIP_HEADER = object()


class StreamDemux:
    """共享缓冲的多规则拆帧分流器（互斥路由，不 fan-out）。"""

    __slots__ = ('_routes', '_buf', '_start', '_max_buffer', '_compact_at')

    def __init__(
        self,
        routes: list[DemuxRoute] | list[dict[str, Any]],
        *,
        max_buffer: int = 1 << 20,
        compact_at: int = 8192,
    ) -> None:
        parsed: list[DemuxRoute] = []
        for r in routes:
            if isinstance(r, DemuxRoute):
                parsed.append(r)
            else:
                parsed.append(DemuxRoute.from_dict(r))
        if not parsed:
            raise ValueError('routes 不能为空')
        # 同位置多候选时按 specificity 降序
        self._routes = sorted(parsed, key=lambda r: (-r.specificity, r.id))
        self._buf = bytearray()
        self._start = 0
        self._max_buffer = int(max_buffer)
        self._compact_at = max(int(compact_at), 64)

    @property
    def routes(self) -> tuple[DemuxRoute, ...]:
        return tuple(self._routes)

    @property
    def pending(self) -> int:
        return len(self._buf) - self._start

    def clear(self) -> None:
        self._buf.clear()
        self._start = 0

    def write(self, data: bytes | bytearray | memoryview) -> None:
        if not data:
            return
        if self._start >= self._compact_at:
            self._compact()
        self._buf.extend(data)
        if self.pending > self._max_buffer:
            keep = max((len(r.header) for r in self._routes), default=1) - 1
            self._buf = self._buf[-keep:] if keep > 0 else bytearray()
            self._start = 0

    def drain(self, limit: int | None = None) -> list[DemuxHit]:
        out: list[DemuxHit] = []
        while limit is None or len(out) < limit:
            hit = self._try_one()
            if hit is None:
                break
            out.append(hit)
        return out

    def _compact(self) -> None:
        if self._start <= 0:
            return
        if self._start >= len(self._buf):
            self._buf.clear()
            self._start = 0
            return
        del self._buf[: self._start]
        self._start = 0

    def _trim_partial(self) -> None:
        self._compact()
        if not self._buf:
            return
        keep = 0
        for r in self._routes:
            hdr = r.header
            upper = min(len(hdr) - 1, len(self._buf))
            for k in range(upper, 0, -1):
                if self._buf.endswith(hdr[:k]):
                    keep = max(keep, k)
                    break
        if keep == 0:
            self._buf.clear()
        elif keep < len(self._buf):
            del self._buf[:-keep]

    def _try_one(self) -> DemuxHit | None:
        buf = self._buf
        start = self._start
        available = len(buf) - start
        if available <= 0:
            return None

        # 找所有 route 中最早出现的帧头
        best_idx = -1
        candidates: list[DemuxRoute] = []
        for route in self._routes:
            idx = buf.find(route.header, start)
            if idx < 0:
                continue
            if best_idx < 0 or idx < best_idx:
                best_idx = idx
                candidates = [route]
            elif idx == best_idx:
                candidates.append(route)

        if best_idx < 0:
            self._trim_partial()
            return None

        if best_idx > start:
            self._start = best_idx
            start = best_idx

        # 同位置候选：先抽帧，再按 type 匹配最具体的 route
        candidates = sorted(candidates, key=lambda r: (-r.specificity, r.id))
        # 按 framing 分组尝试抽取
        tried_skip = False
        for route in candidates:
            result = self._extract_at(start, route)
            if result is _NEED_MORE:
                return None
            if result is _SKIP_HEADER:
                tried_skip = True
                continue
            assert isinstance(result, (bytes, bytearray))
            frame = bytes(result)
            # 在同 framing/size 的候选中找 type 匹配
            matched: DemuxRoute | None = None
            for r in candidates:
                if r.framing != route.framing:
                    continue
                if r.frame_size is not None and r.frame_size != len(frame):
                    continue
                if r.type_matches(frame):
                    matched = r
                    break
            if matched is None:
                # 已对齐定长帧但 type 全不匹配：消费掉，避免死循环
                if route.framing in ('header_len', 'header_len_trailer'):
                    self._start = start + len(frame)
                    if self._start >= self._compact_at:
                        self._compact()
                    return self._try_one()
                # 变长：滑过 1 字节
                self._start = start + 1
                return self._try_one()

            self._start = start + len(frame)
            if self._start >= self._compact_at:
                self._compact()
            return DemuxHit(
                assembler_id=matched.assembler_id,
                frame=frame,
                route_id=matched.id,
                parser_id=matched.parser_id,
                route=matched,
            )

        # 伪起始：滑过最短帧头
        if tried_skip or candidates:
            slide = min(len(r.header) for r in candidates)
            self._start = start + max(1, slide)
            if self._start >= self._compact_at:
                self._compact()
            return self._try_one()
        return None

    def _extract_at(self, start: int, route: DemuxRoute) -> object:
        buf = self._buf
        available = len(buf) - start
        hdr = route.header
        if available < len(hdr):
            return _NEED_MORE
        if bytes(buf[start : start + len(hdr)]) != hdr:
            return _SKIP_HEADER

        if route.framing == 'header_len':
            size = int(route.frame_size or 0)
            if available < size:
                return _NEED_MORE
            return bytes(buf[start : start + size])

        if route.framing == 'header_len_trailer':
            size = int(route.frame_size or 0)
            if available < size:
                return _NEED_MORE
            tlen = len(route.trailers[0])
            tail = bytes(buf[start + size - tlen : start + size])
            if tail not in route.trailers:
                return _SKIP_HEADER
            return bytes(buf[start : start + size])

        # header_trailer
        trl = route.trailers[0]
        min_size = route.min_frame_size or (len(hdr) + len(trl))
        max_size = route.max_frame_size
        search_from = start + len(hdr)
        if search_from >= len(buf):
            return _NEED_MORE
        search_to = min(start + max_size, len(buf))
        trl_idx = buf.find(trl, search_from, search_to)
        if trl_idx < 0:
            if available >= max_size:
                return _SKIP_HEADER
            return _NEED_MORE
        end = trl_idx + len(trl)
        if end - start < min_size:
            return _SKIP_HEADER
        return bytes(buf[start:end])


def normalize_routes(raw: Any) -> list[dict[str, Any]]:
    """校验并归一化为可序列化的 routes 列表；非法抛 ValueError。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError('routes 必须是数组')
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f'routes[{i}] 必须是对象')
        route = DemuxRoute.from_dict(item)
        out.append(route.to_dict())
    return out


def routes_fingerprint(routes: list[dict[str, Any]] | None) -> str:
    """用于 collector 判断 demux 配置是否变化。"""
    import json

    return json.dumps(routes or [], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
