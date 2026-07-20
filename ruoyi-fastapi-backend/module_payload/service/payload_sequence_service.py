import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from redis import asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_assembler import is_broadcast_hex
from module_payload.dao.payload_sequence_dao import PayloadSequenceDao
from module_payload.entity.vo.payload_sequence_vo import (
    DeletePayloadSequenceModel,
    PayloadSequenceModel,
    PayloadSequencePageQueryModel,
)
from module_payload.redis_store import get_seq_run, list_seq_run_history, push_seq_run_history, save_seq_run
from utils.common_util import CamelCaseUtil
from utils.log_util import logger


class PayloadSequenceService:
    """
    指令序列管理服务层
    """

    @classmethod
    async def get_sequence_list_services(
        cls, query_db: AsyncSession, query_object: PayloadSequencePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """
        获取指令序列列表信息service

        :param query_db: orm对象
        :param query_object: 查询参数对象
        :param is_page: 是否开启分页
        :return: 指令序列列表信息对象
        """
        sequence_list_result = await PayloadSequenceDao.get_sequence_list(query_db, query_object, is_page)

        return sequence_list_result

    @classmethod
    async def add_sequence_services(
        cls, query_db: AsyncSession, page_object: PayloadSequenceModel
    ) -> CrudResponseModel:
        """
        新增指令序列信息service

        :param query_db: orm对象
        :param page_object: 新增指令序列对象
        :return: 新增指令序列校验结果
        """
        try:
            db_sequence = await PayloadSequenceDao.add_sequence_dao(query_db, page_object)
            # flush 后即可取自增主键；commit 后属性会 expire，同步读取会触发 MissingGreenlet
            seq_id = db_sequence.seq_id
            await query_db.commit()
            return CrudResponseModel(
                is_success=True,
                message='新增成功',
                result={'seqId': seq_id},
            )
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_sequence_services(
        cls, query_db: AsyncSession, page_object: PayloadSequenceModel
    ) -> CrudResponseModel:
        """
        编辑指令序列信息service

        :param query_db: orm对象
        :param page_object: 编辑指令序列对象
        :return: 编辑指令序列校验结果
        """
        edit_sequence = page_object.model_dump(exclude_unset=True)
        sequence_info = await cls.sequence_detail_services(query_db, page_object.seq_id)
        if sequence_info.seq_id:
            try:
                await PayloadSequenceDao.edit_sequence_dao(query_db, edit_sequence)
                await query_db.commit()
                return CrudResponseModel(is_success=True, message='修改成功')
            except Exception as e:
                await query_db.rollback()
                raise e
        else:
            raise ServiceException(message='指令序列不存在')

    @classmethod
    async def delete_sequence_services(
        cls, query_db: AsyncSession, page_object: DeletePayloadSequenceModel
    ) -> CrudResponseModel:
        """
        删除指令序列信息service

        :param query_db: orm对象
        :param page_object: 删除指令序列对象
        :return: 删除指令序列校验结果
        """
        if page_object.seq_ids:
            seq_id_list = page_object.seq_ids.split(',')
            try:
                for seq_id in seq_id_list:
                    await PayloadSequenceDao.delete_sequence_dao(query_db, PayloadSequenceModel(seqId=seq_id))
                await query_db.commit()
                return CrudResponseModel(is_success=True, message='删除成功')
            except Exception as e:
                await query_db.rollback()
                raise e
        else:
            raise ServiceException(message='传入指令序列id为空')

    @classmethod
    async def sequence_detail_services(cls, query_db: AsyncSession, seq_id: int) -> PayloadSequenceModel:
        """
        获取指令序列详细信息service

        :param query_db: orm对象
        :param seq_id: 指令序列id
        :return: 指令序列id对应的信息
        """
        sequence = await PayloadSequenceDao.get_sequence_detail_by_id(query_db, seq_id=seq_id)
        result = (
            PayloadSequenceModel(**CamelCaseUtil.transform_result(sequence)) if sequence else PayloadSequenceModel()
        )

        return result

    @classmethod
    async def copy_sequence_services(cls, query_db: AsyncSession, seq_id: int) -> PayloadSequenceModel:
        detail = await cls.sequence_detail_services(query_db, seq_id)
        if not detail.seq_id:
            raise ServiceException(message='指令序列不存在')
        draft = detail.model_copy()
        draft.seq_id = None
        draft.seq_name = f'{detail.seq_name or ""}-副本'
        return draft

    @classmethod
    async def run_sequence_services(
        cls, redis: aioredis.Redis, query_db: AsyncSession, seq_id: int, device_id: str
    ) -> dict[str, Any]:
        """启动异步执行：立即返回 runId，进度写入 Redis，前端轮询。"""
        detail = await cls.sequence_detail_services(query_db, seq_id)
        if not detail.seq_id:
            raise ServiceException(message='指令序列不存在')
        try:
            commands, default_interval = cls._parse_sequence_commands(detail.commands)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise ServiceException(message='指令序列内容格式错误') from e
        if not commands:
            raise ServiceException(message='指令序列为空，无法执行')
        for cmd in commands:
            if is_broadcast_hex(cmd.get('hex', '')):
                raise ServiceException(message='序列包含广播帧，禁止执行')
            if not (cmd.get('hex') or '').strip():
                raise ServiceException(message='序列包含空 HEX 指令，禁止执行')

        run_id = str(uuid.uuid4())
        now = datetime.now().isoformat(timespec='milliseconds')
        items = [
            {
                'index': i,
                'name': cmd.get('name') or cmd.get('orderId') or f'#{i + 1}',
                'orderId': cmd.get('orderId') or cmd.get('order_id') or '',
                'hex': (cmd.get('hex') or '').upper(),
                'status': 'pending',
                'message': '',
                'time': '',
            }
            for i, cmd in enumerate(commands)
        ]
        run_state: dict[str, Any] = {
            'runId': run_id,
            'seqId': seq_id,
            'seqName': detail.seq_name or '',
            'deviceId': device_id,
            'status': 'running',
            'total': len(commands),
            'current': 0,
            'ok': 0,
            'fail': 0,
            'items': items,
            'startTime': now,
            'endTime': '',
            'message': '',
        }
        await save_seq_run(redis, run_state)
        await push_seq_run_history(redis, seq_id, run_id)
        asyncio.create_task(
            cls._execute_sequence_run(redis, run_id, device_id, commands, default_interval),
            name=f'seq-run-{run_id}',
        )
        return {
            'runId': run_id,
            'seqId': seq_id,
            'total': len(commands),
            'status': 'running',
        }

    @classmethod
    async def get_run_progress_services(cls, redis: aioredis.Redis, run_id: str) -> dict[str, Any]:
        run = await get_seq_run(redis, run_id)
        if not run:
            raise ServiceException(message='执行记录不存在或已过期')
        return run

    @classmethod
    async def list_run_history_services(
        cls, redis: aioredis.Redis, seq_id: int, limit: int = 30
    ) -> list[dict[str, Any]]:
        return await list_seq_run_history(redis, seq_id, limit)

    @classmethod
    async def _execute_sequence_run(
        cls,
        redis: aioredis.Redis,
        run_id: str,
        device_id: str,
        commands: list[dict[str, Any]],
        default_interval: int,
    ) -> None:
        from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
        from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService

        run = await get_seq_run(redis, run_id)
        if not run:
            return
        fallback = int(default_interval) if int(default_interval) >= 0 else 2000
        items = run.get('items') or []
        ok = 0
        fail = 0
        final_status = 'success'
        stop_message = ''

        try:
            for i, cmd in enumerate(commands):
                hex_text = (cmd.get('hex') or '').strip().upper()
                items[i]['status'] = 'running'
                items[i]['time'] = datetime.now().isoformat(timespec='milliseconds')
                run['current'] = i + 1
                run['items'] = items
                await save_seq_run(redis, run)

                if not hex_text:
                    fail += 1
                    items[i]['status'] = 'failed'
                    items[i]['message'] = 'HEX 为空'
                    final_status = 'failed'
                    stop_message = f'第 {i + 1} 条指令 HEX 为空，已停止'
                    break

                body = TelecontrolSendModel(
                    deviceId=device_id,
                    hex=hex_text,
                    name=cmd.get('name') or cmd.get('orderId'),
                    broadcast=is_broadcast_hex(hex_text),
                )
                try:
                    result = await PayloadTelecontrolService.send(redis, body)
                except Exception as e:  # noqa: BLE001
                    result = {'success': False, 'message': str(e)}

                success = bool(result.get('success'))
                items[i]['status'] = 'success' if success else 'failed'
                items[i]['message'] = result.get('message') or ('发送成功' if success else '发送失败')
                items[i]['time'] = datetime.now().isoformat(timespec='milliseconds')
                if success:
                    ok += 1
                else:
                    fail += 1
                    final_status = 'failed'
                    stop_message = f'第 {i + 1} 条指令执行失败，已停止：{items[i]["message"]}'
                    run['ok'] = ok
                    run['fail'] = fail
                    run['items'] = items
                    await save_seq_run(redis, run)
                    break

                run['ok'] = ok
                run['fail'] = fail
                run['items'] = items
                await save_seq_run(redis, run)

                if i < len(commands) - 1:
                    try:
                        interval = int(cmd.get('interval', -1))
                    except (TypeError, ValueError):
                        interval = -1
                    if interval < 0:
                        interval = fallback
                    await asyncio.sleep(interval / 1000.0)

            if final_status == 'failed':
                for j in range(run.get('current', 0), len(items)):
                    if items[j].get('status') == 'pending':
                        items[j]['status'] = 'skipped'
                        items[j]['message'] = '因前置失败未执行'
        except Exception as e:  # noqa: BLE001
            logger.exception('序列异步执行异常 runId={}', run_id)
            final_status = 'failed'
            stop_message = str(e)
            fail = max(fail, 1)
        finally:
            run['ok'] = ok
            run['fail'] = fail
            run['status'] = final_status
            run['message'] = stop_message
            run['items'] = items
            run['endTime'] = datetime.now().isoformat(timespec='milliseconds')
            await save_seq_run(redis, run)

    @staticmethod
    def _parse_sequence_commands(raw: str | None) -> tuple[list[dict[str, Any]], int]:
        """兼容旧版数组，以及 { defaultInterval, items } 对象格式。interval=-1 表示用序列默认间隔。"""
        data = json.loads(raw or '[]')
        if isinstance(data, dict):
            items = data.get('items') or data.get('commands') or []
            if not isinstance(items, list):
                items = []
            try:
                default_interval = int(data.get('defaultInterval', data.get('default_interval', 2000)))
            except (TypeError, ValueError):
                default_interval = 2000
            if default_interval < 0:
                default_interval = 2000
            return items, default_interval
        if isinstance(data, list):
            return data, 2000
        return [], 2000
