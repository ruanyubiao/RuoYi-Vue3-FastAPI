"""业务代码缺陷修复的回归测试（均为增量修复，原行为保留）。"""

from __future__ import annotations

import asyncio
import gc
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from config.env import UploadConfig
from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel
from module_payload.service import payload_sequence_service as seq_mod
from module_payload.service.payload_sequence_service import PayloadSequenceService
from utils.upload_util import UploadUtil


# ---------- 上传工具 ----------
def test_random_code_999_is_valid() -> None:
    """generate_random_number 可能生成 999，校验必须接受。"""
    name = f'a_20260101120000{UploadConfig.UPLOAD_MACHINE}999.png'
    assert UploadUtil.check_file_random_code(name)
    assert UploadUtil.check_file_random_code(f'a_20260101120000{UploadConfig.UPLOAD_MACHINE}001.png')
    assert not UploadUtil.check_file_random_code(f'a_20260101120000{UploadConfig.UPLOAD_MACHINE}000.png')


def test_generated_codes_always_pass_validation() -> None:
    with patch('utils.upload_util.random.randint', return_value=999):
        code = UploadUtil.generate_random_number()
    assert UploadUtil.check_file_random_code(f'x{UploadConfig.UPLOAD_MACHINE}{code}.png')


@pytest.mark.parametrize('name', ['a.png', '.png', '', 'ab'])
def test_check_file_machine_short_name_no_index_error(name: str) -> None:
    assert UploadUtil.check_file_machine(name) is False


def test_check_file_machine_original_behavior() -> None:
    assert UploadUtil.check_file_machine(f'a_20260101120000{UploadConfig.UPLOAD_MACHINE}123.png')
    assert not UploadUtil.check_file_machine('a_20260101120000Z123.png')


@pytest.mark.parametrize('filename', [None, ''])
def test_check_file_extension_without_filename(filename: str | None) -> None:
    assert UploadUtil.check_file_extension(SimpleNamespace(filename=filename)) is False


# ---------- 指令序列后台任务 ----------
def test_sequence_task_reference_kept_until_done() -> None:
    gate = asyncio.Event

    async def scenario() -> None:
        started, release = gate(), gate()

        async def fake_run(*_a, **_k) -> None:
            started.set()
            await release.wait()

        detail = PayloadSequenceModel(seqId=1, seqName='s', commands='[{"hex": "01 02"}]')
        with (
            patch.object(PayloadSequenceService, 'sequence_detail_services', AsyncMock(return_value=detail)),
            patch.object(PayloadSequenceService, '_execute_sequence_run', fake_run),
            patch.object(seq_mod, 'save_seq_run', AsyncMock()),
            patch.object(seq_mod, 'push_seq_run_history', AsyncMock()),
            patch.object(seq_mod, 'is_broadcast_hex', return_value=False),
        ):
            out = await PayloadSequenceService.run_sequence_services(AsyncMock(), AsyncMock(), 1, 'can:3:0:0')
            assert out['status'] == 'running'
            assert len(seq_mod._RUNNING_SEQ_TASKS) == 1
            gc.collect()
            await asyncio.wait_for(started.wait(), 2)
            assert len(seq_mod._RUNNING_SEQ_TASKS) == 1
            release.set()
            for _ in range(10):
                await asyncio.sleep(0)
            assert len(seq_mod._RUNNING_SEQ_TASKS) == 0

    asyncio.run(scenario())
