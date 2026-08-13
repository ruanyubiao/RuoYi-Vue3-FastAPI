"""工程遥测子包组装器（0x1ACF 帧）。

粘包拆帧交给 FixedHeaderLenTrailerFrameBuffer（固定头/定长/定尾）；
本模块保留校验、有效数据提取、子包序号拼装。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from module_payload.assemblers.base import AssembledPayload, BaseAssembler
from module_payload.constants import ASSEMBLER_ENG_TM_SUBPKT
from module_payload.error_text import checksum_mismatch, frame_len_mismatch, frame_len_over_limit
from module_payload.framing import FixedHeaderLenTrailerFrameBuffer

logger = logging.getLogger(__name__)

# 工程遥测子包帧（大端）
ENG_START = 0x1ACF
# 文档写 0x0A0D（线上字节 0A 0D）；实测常见 CRLF 0D 0A（值 0x0D0A），两者都认
ENG_END = 0x0A0D
ENG_END_CRLF = 0x0D0A
ENG_DATA_CAPACITY = 1024
ENG_FRAME_SIZE = 2 + 2 + 2 + 2 + 2 + 2 + ENG_DATA_CAPACITY + 2 + 2  # 1040

ENG_HEADER = ENG_START.to_bytes(2, 'big')
ENG_TRAILERS = (
    ENG_END.to_bytes(2, 'big'),
    ENG_END_CRLF.to_bytes(2, 'big'),
)


def _emit_warn(msg: str) -> None:
    """采集子进程默认无 logging handler，同时打 stderr 与 logger。"""
    logger.warning(msg)
    print(f'[assembler:eng_tm_subpkt] {msg}', file=sys.stderr, flush=True)


class EngTmSubpktAssembler(BaseAssembler):
    """工程遥测子包组装：按子包序号连续拼装有效数据。

    流处理（FixedHeaderLenTrailerFrameBuffer）:
      找固定头 0x1ACF → 取定长 1040 → 判定尾（0x0A0D / 0x0D0A）

    业务（本类）:
      校验和、长度、子包序号 → 按 dataLen 提有效数据 → 按序号拼装

    丢包/不连续策略（序号从 1 起）:
      - 单包到达但尚有未完成缓存 → 丢弃缓存，接受本单包
      - 无缓存且非首帧(序号≠1) → 丢弃当前帧
      - 有缓存但与上一序号不连续 → 丢弃缓存 + 当前帧
      - 收到新的首帧(序号=1)且有未完成缓存 → 丢弃缓存，从本帧重新开始
      - 源/目的/总包数变化 → 丢弃缓存；当前非首帧则一并丢弃
    """

    ASSEMBLER_ID = ASSEMBLER_ENG_TM_SUBPKT

    def __init__(self) -> None:
        self._frames = FixedHeaderLenTrailerFrameBuffer(
            ENG_HEADER,
            ENG_FRAME_SIZE,
            trailers=ENG_TRAILERS,
        )
        self._slots: dict[int, bytes] = {}
        self._expected: int | None = None
        self._src: int | None = None
        self._dst: int | None = None
        self._last_index: int = 0
        self.last_errors: list[str] = []

    def reset(self) -> None:
        self._frames.clear()
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
        """单组装器兼容路径：写入字节流 → 内部 framing 拆帧 → 业务拼装。

        混流 demux 路径请用 accept_frame()，避免二次粘包处理。
        """
        if not chunk:
            return []
        self._frames.write(chunk)
        out: list[AssembledPayload] = []
        while True:
            frame = self._frames.read_frame()
            if frame is None:
                break
            try:
                parsed = self.parse_frame(frame, check_end=False)
            except ValueError as e:
                msg = f'帧校验失败 {e}'
                self.last_errors.append(msg)
                _emit_warn(msg)
                continue
            done = self._accept_parsed(parsed)
            if done is not None:
                out.append(done)
        return out

    def accept_frame(self, raw: bytes) -> AssembledPayload | None:
        """demux / 插件已拆好的完整 1040B 帧入口（不做粘包缓冲）。"""
        if not raw:
            return None
        try:
            # demux 已验尾时仍再验一次，防止路由误配
            parsed = self.parse_frame(raw, check_end=True)
        except ValueError as e:
            msg = f'帧校验失败 {e}'
            self.last_errors.append(msg)
            _emit_warn(msg)
            return None
        return self._accept_parsed(parsed)

    @staticmethod
    def parse_frame(frame: bytes, *, check_end: bool = True) -> dict[str, Any]:
        """校验并解析单帧；失败抛 ValueError。

        check_end=False 时跳过结束码（流缓冲已先验过结尾）。
        有效数据按 dataLen 从 1024 数据区截取。
        """
        if len(frame) != ENG_FRAME_SIZE:
            data_len = int.from_bytes(frame[2:4], 'big') if len(frame) >= 4 else 0
            raise ValueError(frame_len_mismatch('工程遥测', data_len, ENG_FRAME_SIZE, len(frame)))

        errors: list[str] = []
        start = int.from_bytes(frame[0:2], 'big')
        if start != ENG_START:
            errors.append(f'工程遥测起始码错误: 期望：{ENG_START:04X}， 帧内：{start:04X}')

        if check_end:
            end = int.from_bytes(frame[1038:1040], 'big')
            if end not in (ENG_END, ENG_END_CRLF):
                errors.append(
                    f'工程遥测结束码错误: 期望：{ENG_END:04X} 或 {ENG_END_CRLF:04X}， 帧内：{end:04X}'
                )

        data_len = int.from_bytes(frame[2:4], 'big')
        if data_len > ENG_DATA_CAPACITY:
            errors.append(frame_len_over_limit('工程遥测', data_len, ENG_FRAME_SIZE, ENG_DATA_CAPACITY))

        sub_count = int.from_bytes(frame[8:10], 'big')
        sub_index = int.from_bytes(frame[10:12], 'big')
        if sub_count <= 0 or sub_index <= 0 or sub_index > sub_count:
            errors.append(f'工程遥测子包序号非法: {sub_index}/{sub_count}')

        checksum = int.from_bytes(frame[1036:1038], 'big')
        calc = sum(frame[0:1036]) & 0xFFFF
        if checksum != calc:
            errors.append(checksum_mismatch('工程遥测', calc, checksum, width=4))

        if errors:
            raise ValueError('；'.join(errors))

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

        if sub_count == 1:
            if self._slots:
                self._drop_assembly('收到单包但存在未完成拼装，丢弃缓存')
            self._expected = 1
            self._src = src
            self._dst = dst
            self._slots[1] = data
            self._last_index = 1
            return self._finish(1)

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

        if not self._slots:
            self._drop_assembly(f'无缓存且非首帧，丢弃当前帧 {sub_index}/{sub_count}')
            return None

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
