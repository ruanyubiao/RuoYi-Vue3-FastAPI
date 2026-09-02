from typing import Annotated

from fastapi import File, Query, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from common.aspect.db_seesion import DBSessionDependency
from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.entity.vo.payload_telemetry_vo import (
    CanYcInjectModel,
    CurveBatchQueryModel,
    FileCurveQueryModel,
    FileParseModel,
    HistoryCurveBatchQueryModel,
    HistoryFramesOpenModel,
    PipelineInjectModel,
    TelemetryTableBatchModel,
    TmCalcModel,
)
from module_payload.service.payload_canplay_service import PayloadCanPlayService
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_fileplay_service import PayloadFilePlayService
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
    """获取遥测表配置接口。"""
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
    """获取遥测表定义接口。"""
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
    source: Annotated[
        str,
        Query(
            description='live=实时 Redis；db=历史库；file=历史文件。非 live 不返回 Redis 热层'
        ),
    ] = 'live',
) -> Response:
    """获取遥测表最新值。"""
    result = await PayloadTelemetryService.get_table(
        request.app.state.redis, type, data_id, need_cfg, source
    )
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/table/batch',
    summary='批量获取遥测表最新值',
    description='body.items 字段与 GET /table 一致（type/dataId/needCfg/source）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:view')],
)
async def get_telemetry_table_batch(request: Request, body: TelemetryTableBatchModel) -> Response:
    """批量获取遥测表最新值。"""
    items = []
    for it in body.items or []:
        items.append(
            await PayloadTelemetryService.get_table(
                request.app.state.redis,
                it.type,
                it.data_id_str(),
                bool(it.need_cfg),
                it.source,
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
    """获取遥测量列表。"""
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
    """获取遥测曲线数据。"""
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
    """批量获取遥测曲线数据。"""
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
    """批量获取归档遥测曲线数据。"""
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
    """开发测试：注入CAN遥测复合帧。"""
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
    """通用数据发送模拟：组装器+解析器。"""
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


@payload_telemetry_controller.get(
    '/dev/sample',
    summary='通用数据发送模拟：示例 HEX',
    description='按黄金用例 key 或组装器+解析器返回样本对象（无 fields）；匹配不到返回空对象',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:devtest:view')],
)
async def get_simulate_sample(
    request: Request,
    key: Annotated[str, Query(description='黄金用例 id，如 passthrough_cam_d8')] = '',
    assembler_id: Annotated[str, Query(alias='assemblerId', description='组装器 ID')] = '',
    parser_id: Annotated[str, Query(alias='parserId', description='解析器 ID')] = '',
) -> Response:
    """通用模拟示例 HEX。"""
    result = PayloadTelemetryService.get_simulate_sample(
        key=key, assembler_id=assembler_id, parser_id=parser_id
    )
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/dev/samples',
    summary='通用数据发送模拟：示例 HEX 列表',
    description='按组装器+解析器返回可选黄金样本（key/label/tooltip）；无匹配返回空列表',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:devtest:view')],
)
async def list_simulate_samples(
    request: Request,
    assembler_id: Annotated[str, Query(alias='assemblerId', description='组装器 ID')] = '',
    parser_id: Annotated[str, Query(alias='parserId', description='解析器 ID')] = '',
) -> Response:
    """通用模拟可选示例列表（不自动填充 HEX）。"""
    result = PayloadTelemetryService.list_simulate_samples(
        assembler_id=assembler_id, parser_id=parser_id
    )
    return ResponseUtil.success(data={'items': result})


@payload_telemetry_controller.post(
    '/calc',
    summary='遥测单字段计算',
    description='按表/字段配置用 parse_line_hex 解析 Hex，结果插入 Redis 历史（最多 100 条）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:tmcalc:view')],
)
async def telemetry_calc(request: Request, body: TmCalcModel) -> Response:
    """遥测单字段计算。"""
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
    """遥测计算历史。"""
    result = await PayloadTmCalcService.get_history(request.app.state.redis)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.delete(
    '/calc/history',
    summary='清空遥测计算历史',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:tmcalc:view')],
)
async def telemetry_calc_history_clear(request: Request) -> Response:
    """清空遥测计算历史。"""
    await PayloadTmCalcService.clear_history(request.app.state.redis)
    return ResponseUtil.success(msg='已清空')


@payload_telemetry_controller.post(
    '/file/upload',
    summary='历史文件上传到 log_data（支持分片，可覆盖）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency(['payload:telemetry:fileHistory', 'payload:telemetry:fileCurve'])],
)
async def telemetry_file_upload(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    filename: Annotated[str, Query()] = '',
    chunk_index: Annotated[int, Query(alias='chunkIndex')] = 0,
    total_chunks: Annotated[int, Query(alias='totalChunks')] = 1,
) -> Response:
    """分片上传到 ``{UPLOAD_PATH}/log_data``，同名覆盖。"""
    result = await PayloadFilePlayService.upload_chunk(
        file,
        filename or (file.filename or ''),
        chunk_index=chunk_index,
        total_chunks=total_chunks,
    )
    return ResponseUtil.success(data=result, msg='上传成功' if result.get('done') else '分片已接收')


@payload_telemetry_controller.get(
    '/file/browse',
    summary='浏览上传文件或本地日志目录',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency(['payload:telemetry:fileHistory', 'payload:telemetry:fileCurve'])],
)
async def telemetry_file_browse(
    request: Request,
    root: Annotated[str, Query(description='upload | logs')] = 'upload',
    path: Annotated[str, Query()] = '',
) -> Response:
    """列出 upload/logs 根下目录；文件仅 ``*_recv*`` 可选。"""
    result = PayloadFilePlayService.browse(root, path)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/file/locate',
    summary='按已填路径定位浏览目录（须在 upload/logs 白名单内且文件存在）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency(['payload:telemetry:fileHistory', 'payload:telemetry:fileCurve'])],
)
async def telemetry_file_locate(
    request: Request,
    path: Annotated[str, Query()] = '',
) -> Response:
    """路径越界或不存在时 found=false，弹窗回首页。"""
    result = PayloadFilePlayService.locate(path)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/file/parse',
    summary='解析历史文件（子进程拆帧，独立 Redis Hash）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency(['payload:telemetry:fileHistory', 'payload:telemetry:fileCurve'])],
)
async def telemetry_file_parse(request: Request, body: FileParseModel) -> Response:
    """通知子进程拆帧，立即返回当前 status；前端轮询 /file/status。"""
    result = await PayloadFilePlayService.parse(request.app.state.redis, body.type, body.path)
    return ResponseUtil.success(data=result, msg='已开始解析')


@payload_telemetry_controller.get(
    '/file/status',
    summary='查询历史文件解析状态（parsing/ready/error，ready 带第 1 帧）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency(['payload:telemetry:fileHistory', 'payload:telemetry:fileCurve'])],
)
async def telemetry_file_status(
    request: Request,
    path: Annotated[str, Query()],
) -> Response:
    """前端定时拉取；ready 后停表。超时由前端控制。"""
    result = await PayloadFilePlayService.get_status(request.app.state.redis, path)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/file/frame',
    summary='取历史文件第 N 帧（最多等 Redis 1s，响应含总帧数）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency(['payload:telemetry:fileHistory', 'payload:telemetry:fileCurve'])],
)
async def telemetry_file_frame(
    request: Request,
    path: Annotated[str, Query()],
    index: Annotated[int, Query()] = 1,
) -> Response:
    """取第 N 帧；响应始终含当前总帧数（预估改精确后滑块可更新）。"""
    result = await PayloadFilePlayService.get_frame(request.app.state.redis, path, index)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/file/curve',
    summary='历史文件曲线点列',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:fileCurve')],
)
async def telemetry_file_curve(request: Request, body: FileCurveQueryModel) -> Response:
    """从已解析帧抽曲线点列，不足则通知 worker 补解析。"""
    result = await PayloadFilePlayService.get_curve(
        request.app.state.redis,
        body.model_dump(by_alias=True),
    )
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/history/frames/open',
    summary='打开历史 CAN 表回放会话',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:canHistory')],
)
async def telemetry_history_frames_open(
    request: Request,
    body: HistoryFramesOpenModel,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
) -> Response:
    """按时间窗 COUNT 归档帧并开会话；返回 session 与精确 frameCount。"""
    result = await PayloadCanPlayService.open(
        query_db, request.app.state.redis, body.type, body.start, body.end
    )
    return ResponseUtil.success(data=result, msg='解析成功')


@payload_telemetry_controller.get(
    '/history/frames',
    summary='取历史 CAN 第 N 帧',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:canHistory')],
)
async def telemetry_history_frames(
    request: Request,
    query_db: Annotated[AsyncSession, DBSessionDependency()],
    session: Annotated[str, Query()],
    index: Annotated[int, Query()] = 1,
) -> Response:
    """按会话取第 N 帧（MySQL offset，Redis 缓存）。"""
    result = await PayloadCanPlayService.get_frame(query_db, request.app.state.redis, session, index)
    return ResponseUtil.success(data=result)
