from typing import Annotated

from fastapi import Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.entity.vo.payload_telemetry_vo import (
    CanYcInjectModel,
    CurveBatchQueryModel,
    HistoryCurveBatchQueryModel,
    PipelineInjectModel,
    TelemetryTableBatchModel,
    TmCalcModel,
)
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telemetry_archive_service import PayloadTelemetryArchiveService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService
from module_payload.service.payload_tm_calc_service import PayloadTmCalcService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_telemetry_controller = APIRouterPro(
    prefix='/payload/telemetry', order_num=32, tags=['地检平台-遥测'], dependencies=[PreAuthDependency()]
)


@payload_telemetry_controller.get(
    '/config',
    summary='获取遥测表配置接口',
    description='由各遥测配置文件的 table 派生表列表，用于遥测表切换下拉',
    response_model=DataResponseModel,
)
async def get_telemetry_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
    family: Annotated[str | None, Query(description='可选过滤：biu | xl')] = None,
) -> Response:
    result = PayloadConfigService.get_telemetry_pages(reload=reload, family=family)
    logger.info('获取遥测页配置成功')

    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/def',
    summary='获取遥测表定义接口',
    description='按数据类型返回遥测表字段定义(row)，用于渲染表头/描述与曲线遥测量下拉',
    response_model=DataResponseModel,
)
async def get_telemetry_table_def(
    request: Request,
    type: Annotated[str, Query(description='遥测数据类型(HEX, 如 FF)')],
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
    family: Annotated[str | None, Query(description='可选：biu | xl')] = None,
) -> Response:
    result = PayloadConfigService.get_telemetry_table_def(type, reload=reload, family=family)
    logger.info(f'获取遥测表[{type}]定义成功')

    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/table',
    summary='获取遥测表最新值',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:view')],
)
async def get_telemetry_table(
    request: Request,
    type: Annotated[str, Query(description='遥测数据类型(HEX)')],
    data_id: Annotated[
        str | None, Query(alias='dataId', description='客户端已持有的数据快照ID，相同则不返回行列表')
    ] = None,
    need_cfg: Annotated[
        bool, Query(alias='needCfg', description='为 true 时一并返回表字段配置 cfg')
    ] = False,
) -> Response:
    result = await PayloadTelemetryService.get_table(
        request.app.state.redis, type, data_id, need_cfg
    )
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/table/batch',
    summary='批量获取遥测表最新值',
    description='body.items 为参数对象数组，字段与单次 GET /table 一致（type/dataId/needCfg）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:view')],
)
async def get_telemetry_table_batch(request: Request, body: TelemetryTableBatchModel) -> Response:
    items = []
    for it in body.items or []:
        items.append(
            await PayloadTelemetryService.get_table(
                request.app.state.redis,
                it.type,
                it.data_id_str(),
                bool(it.need_cfg),
            )
        )
    return ResponseUtil.success(data={'items': items})


@payload_telemetry_controller.get(
    '/fields',
    summary='获取遥测量列表',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:view')],
)
async def get_telemetry_fields(
    request: Request,
    type: Annotated[str, Query(description='遥测数据类型(HEX)')],
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
    family: Annotated[str | None, Query(description='可选：biu | xl')] = None,
) -> Response:
    result = PayloadTelemetryService.get_fields(type, reload=reload, family=family)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/curve/data',
    summary='获取遥测曲线数据',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:curve')],
)
async def get_telemetry_curve_data(
    request: Request,
    type: Annotated[str, Query()],
    field: Annotated[str, Query()],
    limit: Annotated[int, Query()] = 500,
    since_t: Annotated[int | None, Query(alias='sinceT', description='仅返回该时间戳(ms)之后的新点')] = None,
) -> Response:
    result = await PayloadTelemetryService.get_curve_data(
        request.app.state.redis, type, field, limit, since_t
    )
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/curve/data/batch',
    summary='批量获取遥测曲线数据',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:curve')],
)
async def get_telemetry_curve_data_batch(
    request: Request,
    body: CurveBatchQueryModel,
) -> Response:
    items = [
        {
            'type': i.type,
            'field': i.field,
            'limit': i.limit,
            'since_t': i.since_t,
        }
        for i in body.items
    ]
    result = await PayloadTelemetryService.get_curve_data_batch(request.app.state.redis, items)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/history/curve/batch',
    summary='批量获取归档遥测曲线数据',
    description='从 MySQL 按 [startT, endT] 查询历史数值点，供归档曲线页使用',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:archive')],
)
async def get_telemetry_history_curve_batch(
    request: Request,
    body: HistoryCurveBatchQueryModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    items = [
        {
            'type': i.type,
            'field': i.field,
            'start_t': i.start_t,
            'end_t': i.end_t,
            'limit': i.limit,
        }
        for i in body.items
    ]
    result = await PayloadTelemetryArchiveService.get_history_curve_data_batch(query_db, items)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/dev/can-yc',
    summary='开发测试：注入CAN遥测复合帧',
    description='模拟 CAN 库组帧后的完整遥测应答，校验后解析并写入 Redis，供遥测界面轮询显示',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:devtest:view')],
)
async def inject_can_yc_test(request: Request, body: CanYcInjectModel) -> Response:
    result = await PayloadTelemetryService.inject_can_yc(request.app.state.redis, body.hex)
    logger.info(f'注入CAN遥测测试数据成功 type={result.get("dataType")}')
    return ResponseUtil.success(data=result, msg='注入成功')


@payload_telemetry_controller.post(
    '/dev/pipeline',
    summary='通用数据发送模拟：组装器+解析器',
    description='HEX 先经组装器还原完整载荷，再交给解析器写入 Redis（来源 http:devtest）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:devtest:view')],
)
async def inject_pipeline_test(request: Request, body: PipelineInjectModel) -> Response:
    result = await PayloadTelemetryService.inject_pipeline(
        request.app.state.redis,
        body.hex,
        body.assembler_id,
        body.parser_id,
    )
    logger.info(
        f'通用模拟注入成功 asm={result.get("assemblerId")} parser={result.get("parserId")} '
        f'type={result.get("dataType")}'
    )
    return ResponseUtil.success(data=result, msg='注入成功')


@payload_telemetry_controller.post(
    '/calc',
    summary='遥测单字段计算',
    description='按表/字段配置用 parse_line_hex 解析 Hex，结果插入 Redis 历史（最多 100 条）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:tmcalc:view')],
)
async def telemetry_calc(request: Request, body: TmCalcModel) -> Response:
    result = await PayloadTmCalcService.calculate(
        request.app.state.redis,
        table_type=body.type,
        field_id=body.field,
        hex_text=body.hex,
        pad_tail=body.pad_tail,
    )
    logger.info(
        f'遥测计算 type={body.type} field={body.field} padTail={body.pad_tail} err={result.get("err")}'
    )
    # err=true 仍返回 200 + data（便于前端入库展示）；msg 提示解析告警
    msg = result.get('warnMsg') or '计算成功'
    return ResponseUtil.success(data=result, msg=msg)


@payload_telemetry_controller.get(
    '/calc/history',
    summary='遥测计算历史',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:tmcalc:view')],
)
async def telemetry_calc_history(request: Request) -> Response:
    result = await PayloadTmCalcService.get_history(request.app.state.redis)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.delete(
    '/calc/history',
    summary='清空遥测计算历史',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:tmcalc:view')],
)
async def telemetry_calc_history_clear(request: Request) -> Response:
    await PayloadTmCalcService.clear_history(request.app.state.redis)
    return ResponseUtil.success(msg='已清空')
