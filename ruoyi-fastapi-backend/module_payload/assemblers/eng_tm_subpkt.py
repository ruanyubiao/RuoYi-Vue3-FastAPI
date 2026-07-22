"""工程遥测子包组装器（0x1ACF 帧）。"""

from __future__ import annotations

import logging
import sys
from typing import Any

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT

logger = logging.getLogger(__name__)

# 工程遥测子包帧（大端）
ENG_START = 0x1ACF
# 文档写 0x0A0D（线上字节 0A 0D）；实测常见 CRLF 0D 0A（值 0x0D0A），两者都认
ENG_END = 0x0A0D
ENG_END_CRLF = 0x0D0A
ENG_DATA_CAPACITY = 1024
ENG_FRAME_SIZE = 2 + 2 + 2 + 2 + 2 + 2 + ENG_DATA_CAPACITY + 2 + 2  # 1040


def _emit_warn(msg: str) -> None:
    """采集子进程默认无 logging handler，同时打 stderr 与 logger。"""
    logger.warning(msg)
    print(f'[assembler:eng_tm_subpkt] {msg}', file=sys.stderr, flush=True)


class EngTmSubpktAssembler(BaseAssembler):
    """工程遥测子包组装：按子包序号连续拼装有效数据。

    拆帧流程（粘包循环）:
      1. 找固定起始头 0x1ACF
      2. 取固定长度 1040
      3. 判固定结尾（兼容 0x0A0D / 0x0D0A）；不对则滑窗重搜
      4. 校验和、长度、子包序号
      5. 按 dataLen 提取有效数据，再按子包序号拼装
      6. 本帧处理完后循环处理缓冲剩余数据

    丢包/不连续策略（参考 StrictImageAssembler 思路，序号从 1 起）:
      - 单包到达但尚有未完成缓存 → 丢弃缓存，接受本单包
      - 无缓存且非首帧(序号≠1) → 丢弃当前帧
      - 有缓存但与上一序号不连续 → 丢弃缓存 + 当前帧
      - 收到新的首帧(序号=1)且有未完成缓存 → 丢弃缓存，从本帧重新开始
      - 源/目的/总包数变化 → 丢弃缓存；当前非首帧则一并丢弃
    """

    ASSEMBLER_ID = ASSEMBLER_ENG_TM_SUBPKT

    def __init__(self) -> None:
        self._buf = bytearray()
        self._slots: dict[int, bytes] = {}
        self._expected: int | None = None
        self._src: int | None = None
        self._dst: int | None = None
        self._last_index: int = 0
        self.last_errors: list[str] = []

    def reset(self) -> None:
        self._buf.clear()
        self._clear_assembly()
        self.last_errors.clear()

    def _clear_assembly(self) -> None:
        self._slots.clear()
        self._expected = None
        self._src = None
        self._dst = None
        self._last_index = 0

    def _drop_assembly(self, reason: str) -> None:
        if self._slots or self._expected is not None:
            msg = (
                f'{reason}；丢弃未完成缓存 '
                f'slots={len(self._slots)}/{self._expected or 0} lastIndex={self._last_index}'
            )
        else:
            msg = reason
        self.last_errors.append(msg)
        _emit_warn(msg)
        self._clear_assembly()

    def take_errors(self) -> list[str]:
        errs = list(self.last_errors)
        self.last_errors.clear()
        return errs

    def feed(self, chunk: bytes) -> list[AssembledPayload]:
        """追加数据后循环拆帧，直到缓冲不足以再取完整帧。"""
        if not chunk:
            return []
        self._buf.extend(chunk)
        out: list[AssembledPayload] = []
        # 循环处理后续还有的数据（粘包一包多帧）
        while True:
            parsed = self._pop_parsed_frame()
            if parsed is None:
                break
            done = self._accept_parsed(parsed)
            if done is not None:
                out.append(done)
        return out

    def _find_start(self) -> int:
        """找固定起始头 0x1ACF；找不到返回 -1。"""
        i = 0
        while i + 1 < len(self._buf):
            if (self._buf[i] << 8 | self._buf[i + 1]) == ENG_START:
                return i
            i += 1
        return -1

    def _pop_parsed_frame(self) -> dict[str, Any] | None:
        """拆一帧：找起始头 → 取固定 1040 → 判结尾 → 校验 → 提有效数据。

        本帧处理完后由 feed() 再调本方法，循环处理缓冲中剩余数据。
        数据不够 1040 时返回 None 等待下次 feed。
        """
        while True:
            # 1) 找固定起始头 0x1ACF
            found = self._find_start()
            if found < 0:
                if self._buf:
                    keep = self._buf[-1:]  # 可能半个起始码
                    self._buf.clear()
                    self._buf.extend(keep)
                return None
            if found > 0:
                msg = f'丢弃起始码前杂散字节 {found}'
                self.last_errors.append(msg)
                _emit_warn(msg)
                del self._buf[:found]

            # 2) 起始头后按固定长度 1040 取候选帧；不够则等待
            if len(self._buf) < ENG_FRAME_SIZE:
                return None
            candidate = bytes(self._buf[:ENG_FRAME_SIZE])

            # 3) 判断固定结尾（兼容 0A0D / 0D0A）
            end = int.from_bytes(candidate[1038:1040], 'big')
            if end not in (ENG_END, ENG_END_CRLF):
                msg = (
                    f'结束码错误: 0x{end:04X}，期望 0x{ENG_END:04X}(字节0A0D) '
                    f'或 0x{ENG_END_CRLF:04X}(字节0D0A)；视为伪起始，滑窗重搜'
                )
                self.last_errors.append(msg)
                _emit_warn(msg)
                del self._buf[:2]  # 滑过当前伪 1ACF，继续找下一个起始头
                continue

            # 4) 校验和、长度、子包序号等
            try:
                parsed = self.parse_frame(candidate, check_end=False)
            except ValueError as e:
                msg = f'帧校验失败 {e}'
                self.last_errors.append(msg)
                _emit_warn(msg)
                # 起始+结尾已对齐，整帧丢弃，继续循环拆后续数据
                del self._buf[:ENG_FRAME_SIZE]
                continue

            # 5) 消费本帧，返回有效字段；feed 循环再处理剩余缓冲
            del self._buf[:ENG_FRAME_SIZE]
            return parsed

    @staticmethod
    def parse_frame(frame: bytes, *, check_end: bool = True) -> dict[str, Any]:
        """校验并解析单帧；失败抛 ValueError。

        check_end=False 时跳过结束码（调用方已先验过结尾）。
        有效数据按 dataLen 从 1024 数据区截取。
        """
        if len(frame) != ENG_FRAME_SIZE:
            raise ValueError(f'工程遥测帧长错误: {len(frame)}，期望 {ENG_FRAME_SIZE}')

        errors: list[str] = []
        start = int.from_bytes(frame[0:2], 'big')
        if start != ENG_START:
            errors.append(f'起始码错误: 0x{start:04X}，期望 0x{ENG_START:04X}')

        if check_end:
            end = int.from_bytes(frame[1038:1040], 'big')
            if end not in (ENG_END, ENG_END_CRLF):
                errors.append(
                    f'结束码错误: 0x{end:04X}，期望 0x{ENG_END:04X}(字节0A0D) '
                    f'或 0x{ENG_END_CRLF:04X}(字节0D0A)'
                )

        data_len = int.from_bytes(frame[2:4], 'big')
        if data_len > ENG_DATA_CAPACITY:
            errors.append(
                f'有效长度越界: {data_len}(0x{data_len:04X})，最大 {ENG_DATA_CAPACITY}；'
                f'该字段是数据区有效长度，不是整帧长度{ENG_FRAME_SIZE}'
            )

        sub_count = int.from_bytes(frame[8:10], 'big')
        sub_index = int.from_bytes(frame[10:12], 'big')
        if sub_count <= 0 or sub_index <= 0 or sub_index > sub_count:
            errors.append(f'子包序号非法: {sub_index}/{sub_count}')

        checksum = int.from_bytes(frame[1036:1038], 'big')
        calc = sum(frame[0:1036]) & 0xFFFF
        if checksum != calc:
            errors.append(f'校验失败: 帧内=0x{checksum:04X} 计算=0x{calc:04X}')

        if errors:
            raise ValueError('；'.join(errors))

        # 提取有效数据（按 dataLen，尾部填充忽略）
        src = int.from_bytes(frame[4:6], 'big')
        dst = int.from_bytes(frame[6:8], 'big')
        payload = frame[12 : 12 + data_len]
        return {
            'srcAddr': src,
            'destAddr': dst,
            'subCount': sub_count,
            'subIndex': sub_index,
            'data': payload,
            'dataLen': data_len,
        }

    def _finish(self, sub_count: int) -> AssembledPayload:
        data = b''.join(self._slots[i] for i in range(1, sub_count + 1))
        meta = {
            'srcAddr': self._src,
            'destAddr': self._dst,
            'subCount': sub_count,
            'assemblerId': self.ASSEMBLER_ID,
        }
        info = (
            f'组装完成 src=0x{(self._src or 0):04X} dest=0x{(self._dst or 0):04X} '
            f'subCount={sub_count} dataLen={len(data)}'
        )
        logger.info(info)
        print(f'[assembler:eng_tm_subpkt] {info}', file=sys.stderr, flush=True)
        self._clear_assembly()
        return AssembledPayload(data=data, meta=meta)

    def _accept_parsed(self, parsed: dict[str, Any]) -> AssembledPayload | None:
        sub_count = int(parsed['subCount'])
        sub_index = int(parsed['subIndex'])
        src = int(parsed['srcAddr'])
        dst = int(parsed['destAddr'])
        data = parsed['data']

        # 单包：有未完成多包缓存则丢弃缓存，本帧直接产出
        if sub_count == 1:
            if self._slots:
                self._drop_assembly('收到单包但存在未完成拼装，丢弃缓存')
            self._expected = 1
            self._src = src
            self._dst = dst
            self._slots[1] = data
            self._last_index = 1
            return self._finish(1)

        # —— 多包 ——
        # 会话参数变化：丢缓存；当前非首帧则连当前一起丢
        if self._expected is not None and (
            self._expected != sub_count or self._src != src or self._dst != dst
        ):
            self._drop_assembly(
                f'会话参数变化 '
                f'subCount={self._expected}→{sub_count} '
                f'src={self._src}→{src} dst={self._dst}→{dst}'
            )
            if sub_index != 1:
                self.last_errors.append(f'会话重置后非首帧，丢弃当前帧 {sub_index}/{sub_count}')
                _emit_warn(self.last_errors[-1])
                return None

        # 新的首帧：未完成缓存作废，从本帧重开
        if sub_index == 1:
            if self._slots:
                self._drop_assembly(f'收到首帧，丢弃未完成拼装 lastIndex={self._last_index}')
            self._expected = sub_count
            self._src = src
            self._dst = dst
            self._slots[1] = data
            self._last_index = 1
            if sub_count == 1:
                return self._finish(1)
            return None

        # 无缓存且非首帧
        if not self._slots:
            self._drop_assembly(f'无缓存且非首帧，丢弃当前帧 {sub_index}/{sub_count}')
            return None

        # 与上一序号不连续 → 丢缓存 + 当前帧
        if sub_index != self._last_index + 1:
            self._drop_assembly(
                f'子包不连续 expect={self._last_index + 1} got={sub_index}/{sub_count}，'
                f'丢弃缓存与当前帧'
            )
            return None

        self._slots[sub_index] = data
        self._last_index = sub_index
        if self._last_index < sub_count:
            return None
        return self._finish(sub_count)
