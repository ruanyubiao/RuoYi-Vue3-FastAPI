from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.entity.vo.payload_telemetry_vo import CanYcInjectModel, CurveSubscribeModel
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_telemetry_controller = APIRouterPro(
    prefix='/payload/telemetry', order_num=32, tags=['地检平台-遥测'], dependencies=[PreAuthDependency()]
)


@payload_telemetry_controller.get(
    '/config',
    summary='获取遥测页配置接口',
    description='读取 TeleMetryCfg.json 的 page 列表，用于二级菜单与遥测表切换下拉',
    response_model=DataResponseModel,
)
async def get_telemetry_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
) -> Response:
    result = PayloadConfigService.get_telemetry_pages(reload=reload)
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
) -> Response:
    result = PayloadConfigService.get_telemetry_table_def(type, reload=reload)
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
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')],
    type: Annotated[str, Query(description='遥测数据类型(HEX)')],
    data_id: Annotated[
        str | None, Query(alias='dataId', description='客户端已持有的数据快照ID，相同则不返回行列表')
    ] = None,
    need_cfg: Annotated[
        bool, Query(alias='needCfg', description='为 true 时一并返回表字段配置 cfg')
    ] = False,
) -> Response:
    result = await PayloadTelemetryService.get_table(
        request.app.state.redis, device_id, type, data_id, need_cfg
    )
    return ResponseUtil.success(data=result)


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
) -> Response:
    result = PayloadTelemetryService.get_fields(type, reload=reload)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/curve/subscribe',
    summary='订阅遥测曲线',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:curve')],
)
async def subscribe_telemetry_curve(request: Request, body: CurveSubscribeModel) -> Response:
    await PayloadTelemetryService.subscribe_curve(
        request.app.state.redis, body.device_id, body.type, body.field, body.enabled
    )
    return ResponseUtil.success(msg='订阅成功')


@payload_telemetry_controller.get(
    '/curve/data',
    summary='获取遥测曲线数据',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telemetry:curve')],
)
async def get_telemetry_curve_data(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId')],
    type: Annotated[str, Query()],
    field: Annotated[str, Query()],
    limit: Annotated[int, Query()] = 600,
) -> Response:
    result = await PayloadTelemetryService.get_curve_data(request.app.state.redis, device_id, type, field, limit)
    return ResponseUtil.success(data=result)


@payload_telemetry_controller.post(
    '/dev/can-yc',
    summary='开发测试：注入CAN遥测复合帧',
    description='模拟 CAN 库组帧后的完整遥测应答，校验后解析并写入 Redis，供遥测界面轮询显示',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:devtest:view')],
)
async def inject_can_yc_test(request: Request, body: CanYcInjectModel) -> Response:
    result = await PayloadTelemetryService.inject_can_yc(request.app.state.redis, body.device_id, body.hex)
    logger.info(f'注入CAN遥测测试数据成功 device={body.device_id} type={result.get("dataType")}')
    return ResponseUtil.success(data=result, msg='注入成功')
