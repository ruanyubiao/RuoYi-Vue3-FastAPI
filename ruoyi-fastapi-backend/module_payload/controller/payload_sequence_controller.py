from datetime import datetime
from typing import Annotated

from fastapi import Path, Query, Request, Response
from pydantic_validation_decorator import ValidateFields
from sqlalchemy.ext.asyncio import AsyncSession

from common.annotation.log_annotation import Log
from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import CurrentUserDependency, PreAuthDependency
from common.enums import BusinessType
from common.router import APIRouterPro
from common.vo import DataResponseModel, PageResponseModel, ResponseBaseModel
from module_admin.entity.vo.user_vo import CurrentUserModel
from module_payload.entity.vo.payload_sequence_vo import (
    DeletePayloadSequenceModel,
    PayloadSequenceModel,
    PayloadSequencePageQueryModel,
    SequenceRunModel,
)
from module_payload.service.payload_sequence_service import PayloadSequenceService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_sequence_controller = APIRouterPro(
    prefix='/payload/sequence', order_num=30, tags=['地检平台-指令序列'], dependencies=[PreAuthDependency()]
)


@payload_sequence_controller.get(
    '/list',
    summary='获取指令序列分页列表接口',
    description='用于获取指令序列分页列表',
    response_model=PageResponseModel[PayloadSequenceModel],
    dependencies=[UserInterfaceAuthDependency('payload:sequence:list')],
)
async def get_payload_sequence_list(
    request: Request,
    sequence_page_query: Annotated[PayloadSequencePageQueryModel, Query()],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await PayloadSequenceService.get_sequence_list_services(query_db, sequence_page_query, is_page=True)
    logger.info('获取成功')

    return ResponseUtil.success(model_content=result)


@payload_sequence_controller.get(
    '/run/{run_id}',
    summary='查询序列执行进度/详情',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:sequence:query')],
)
async def get_payload_sequence_run(
    request: Request,
    run_id: Annotated[str, Path(description='执行任务ID')],
) -> Response:
    result = await PayloadSequenceService.get_run_progress_services(request.app.state.redis, run_id)
    return ResponseUtil.success(data=result)


@payload_sequence_controller.post(
    '',
    summary='新增指令序列接口',
    description='用于新增指令序列',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('payload:sequence:add')],
)
@ValidateFields(validate_model='add_sequence')
@Log(title='指令序列', business_type=BusinessType.INSERT)
async def add_payload_sequence(
    request: Request,
    add_sequence: PayloadSequenceModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    add_sequence.create_by = current_user.user.user_name
    add_sequence.create_time = datetime.now()
    add_sequence.update_by = current_user.user.user_name
    add_sequence.update_time = datetime.now()
    add_sequence_result = await PayloadSequenceService.add_sequence_services(query_db, add_sequence)
    logger.info(add_sequence_result.message)

    return ResponseUtil.success(msg=add_sequence_result.message, data=add_sequence_result.result)


@payload_sequence_controller.put(
    '',
    summary='编辑指令序列接口',
    description='用于编辑指令序列',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('payload:sequence:edit')],
)
@ValidateFields(validate_model='edit_sequence')
@Log(title='指令序列', business_type=BusinessType.UPDATE)
async def edit_payload_sequence(
    request: Request,
    edit_sequence: PayloadSequenceModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    current_user: Annotated[CurrentUserModel, CurrentUserDependency()],
) -> Response:
    edit_sequence.update_by = current_user.user.user_name
    edit_sequence.update_time = datetime.now()
    edit_sequence_result = await PayloadSequenceService.edit_sequence_services(query_db, edit_sequence)
    logger.info(edit_sequence_result.message)

    return ResponseUtil.success(msg=edit_sequence_result.message)


@payload_sequence_controller.delete(
    '/{seq_ids}',
    summary='删除指令序列接口',
    description='用于删除指令序列',
    response_model=ResponseBaseModel,
    dependencies=[UserInterfaceAuthDependency('payload:sequence:remove')],
)
@Log(title='指令序列', business_type=BusinessType.DELETE)
async def delete_payload_sequence(
    request: Request,
    seq_ids: Annotated[str, Path(description='需要删除的指令序列ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    delete_sequence = DeletePayloadSequenceModel(seqIds=seq_ids)
    delete_sequence_result = await PayloadSequenceService.delete_sequence_services(query_db, delete_sequence)
    logger.info(delete_sequence_result.message)

    return ResponseUtil.success(msg=delete_sequence_result.message)


@payload_sequence_controller.get(
    '/{seq_id}',
    summary='获取指令序列详情接口',
    description='用于获取指定指令序列的详细信息',
    response_model=DataResponseModel[PayloadSequenceModel],
    dependencies=[UserInterfaceAuthDependency('payload:sequence:query')],
)
async def get_payload_sequence_detail(
    request: Request,
    seq_id: Annotated[int, Path(description='指令序列ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    sequence_detail_result = await PayloadSequenceService.sequence_detail_services(query_db, seq_id)
    logger.info(f'获取seq_id为{seq_id}的信息成功')

    return ResponseUtil.success(data=sequence_detail_result)


@payload_sequence_controller.post(
    '/{seq_id}/copy',
    summary='复制指令序列(返回草稿)',
    response_model=DataResponseModel[PayloadSequenceModel],
    dependencies=[UserInterfaceAuthDependency('payload:sequence:add')],
)
async def copy_payload_sequence(
    request: Request,
    seq_id: Annotated[int, Path(description='指令序列ID')],
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    draft = await PayloadSequenceService.copy_sequence_services(query_db, seq_id)
    return ResponseUtil.success(data=draft)


@payload_sequence_controller.post(
    '/{seq_id}/run',
    summary='执行指令序列（异步，立即返回 runId）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:sequence:edit')],
)
async def run_payload_sequence(
    request: Request,
    seq_id: Annotated[int, Path(description='指令序列ID')],
    body: SequenceRunModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    result = await PayloadSequenceService.run_sequence_services(
        request.app.state.redis, query_db, seq_id, body.device_id
    )
    return ResponseUtil.success(data=result)


@payload_sequence_controller.get(
    '/{seq_id}/runs',
    summary='查询序列执行历史',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:sequence:query')],
)
async def list_payload_sequence_runs(
    request: Request,
    seq_id: Annotated[int, Path(description='指令序列ID')],
    limit: Annotated[int, Query(description='返回条数')] = 30,
) -> Response:
    result = await PayloadSequenceService.list_run_history_services(
        request.app.state.redis, seq_id, limit=max(1, min(limit, 100))
    )
    return ResponseUtil.success(data=result)
