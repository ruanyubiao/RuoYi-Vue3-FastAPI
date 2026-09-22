"""用 logs_data/raw 里的真实接收文件检查文件回放。

不写死文件名：遍历接收文件，按文件名开头的源前缀对应遥测表。
有文件就各解两帧，最多检查两个。文件数量不够不算失败。
表未登记、拆帧抛错、解字段失败记进同一份反馈。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.collectors.connection_transfer_logger import default_log_root
from module_payload.fileplay.detect import FileIndex, detect_file_kind, iter_bin_frames, iter_hex_frames
from module_payload.fileplay.parse_frame import parse_frame
from module_payload.fileplay.registry import resolve_fileplay

# 文件名源前缀 → 遥测表。长前缀靠匹配时按长度优先，避免 camera_ctrl 吃掉 camera_ctrl_v17。
RAW_PREFIX_TABLES: dict[str, tuple[str, ...]] = {
    'camera_ctrl_v17': ('D8V17', 'D9V17'),
    'camera_ctrl': ('D8', 'D9'),
    'cpazx': ('CPAZX',),
    'zk': ('ZK',),
    'rkdj': ('RKDJ',),
    'xl_udp_dj': ('DJ',),
    'biu_can_a': ('BIU:FF',),
    'biu_can_b': ('BIU:FF',),
    'xl_can_a': ('XL:FF',),
    'xl_can_b': ('XL:FF',),
}

_LINK_MARKS = ('_serial_', '_can_', '_udp_')


def _recv_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.is_dir():
        return files
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith('_recv.bin') or name.endswith('_recv.txt'):
            files.append(path)
    return files


def _source_prefix(name: str) -> str:
    """``cpazx_serial_COM1_..._recv.bin`` → ``cpazx``。对不上已登记前缀时，取链路标记前的一段。"""
    for prefix in sorted(RAW_PREFIX_TABLES, key=len, reverse=True):
        if name.startswith(prefix + '_'):
            return prefix
    for mark in _LINK_MARKS:
        if mark in name:
            return name.split(mark, 1)[0]
    return ''


def _two_frames(path: Path, table: str) -> list:
    kind = detect_file_kind(path)
    frames = []
    stream = iter_hex_frames(path, table) if kind == 'hex' else iter_bin_frames(path, table, keep_raw=True)
    for ref in stream:
        frames.append(ref)
        if len(frames) >= 2:
            break
    return frames


def test_raw_recv_files_parse_two_frames() -> None:
    """每种源前缀最多用两个接收文件，各解两帧。文件不够不失败。"""
    root = default_log_root()
    files = _recv_files(root)
    if not files:
        pytest.skip(f'{root} 下没有接收文件')

    grouped: dict[str, list[Path]] = {}
    for path in files:
        if path.stat().st_size <= 0:
            continue
        prefix = _source_prefix(path.name)
        if not prefix:
            continue
        grouped.setdefault(prefix, []).append(path)

    problems: list[str] = []
    cfg = PayloadConfigLoader.get_device_connect_cfg()

    def parser_id_of(source: str) -> str:
        entry = cfg.get(source)
        if not isinstance(entry, dict):
            return ''
        return str(entry.get('parserId') or '').strip().lower()

    for prefix, paths in sorted(grouped.items()):
        if prefix in RAW_PREFIX_TABLES:
            continue
        if parser_id_of(prefix) == 'none':
            continue
        problems.append(f'遗漏了类型: 文件名前缀 {prefix} 有 {len(paths)} 个接收文件，未对应遥测表')

    for prefix, tables in RAW_PREFIX_TABLES.items():
        paths = sorted(grouped.get(prefix, []), key=lambda p: p.stat().st_size)
        if not paths:
            continue
        for table in tables:
            if resolve_fileplay(table) is None:
                problems.append(f'遗漏了类型: {prefix} → {table} 未登记文件回放解析')
                continue
            ok = 0
            for path in paths:
                if ok >= 2:
                    break
                try:
                    frames = _two_frames(path, table)
                except Exception as exc:
                    problems.append(f'{path.name} / {table} 拆帧失败: {exc}')
                    continue
                if len(frames) < 2:
                    continue
                idx = FileIndex(
                    path=str(path),
                    table_type=table,
                    kind=detect_file_kind(path),
                    size=path.stat().st_size,
                    frames=frames,
                    frame_count=len(frames),
                    frame_count_exact=False,
                )
                try:
                    for n in (1, 2):
                        snap = parse_frame(idx, n)
                        if not snap.get('rows'):
                            raise ValueError('解析结果没有字段')
                except Exception as exc:
                    problems.append(f'{path.name} / {table} 帧解析错误: {exc}')
                    continue
                ok += 1

    if problems:
        pytest.fail('文件回放真实接收文件:\n' + '\n'.join(problems))
