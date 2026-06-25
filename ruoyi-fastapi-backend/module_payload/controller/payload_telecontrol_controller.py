from typing import Annotated

from fastapi import Path, Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.entity.vo.payload_telecontrol_vo import CanRawSendModel, ControlOpModel, TelecontrolAssembleModel, TelecontrolSendModel
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_telecontrol_controller = APIRouterPro(
    prefix='/payload/telecontrol', order_num=31, tags=['地检平台-遥控'], dependencies=[PreAuthDependency()]
)


@payload_telecontrol_controller.get(
    '/config',
    summary='获取遥控配置接口',
    description='读取 TeleControlCfg.json，返回分类页与指令定义，用于构建遥控指令树与参数表单',
    response_model=DataResponseModel,
)
async def get_telecontrol_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
) -> Response:
    result = PayloadConfigService.get_telecontrol_config(reload=reload)
    logger.info('获取遥控配置成功')

    return ResponseUtil.success(data=result)


@payload_telecontrol_controller.get(
    '/order/{order_id}',
    summary='获取单条遥控指令定义',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telecontrol:send')],
)
async def get_telecontrol_order(
    request: Request,
    order_id: Annotated[str, Path(description='指令代号')],
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
) -> Response:
    result = PayloadTelecontrolService.get_order(order_id, reload=reload)
    return ResponseUtil.success(data=result)


@payload_telecontrol_controller.post(
    '/assemble',
    summary='组装遥控指令HEX',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telecontrol:send')],
)
async def assemble_telecontrol_order(request: Request, body: TelecontrolAssembleModel) -> Response:
    result = PayloadTelecontrolService.assemble(body)
    return ResponseUtil.success(data=result)


@payload_telecontrol_controller.post(
    '/send',
    summary='下发遥控指令',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telecontrol:send')],
)
async def send_telecontrol_order(request: Request, body: TelecontrolSendModel) -> Response:
    result = await PayloadTelecontrolService.send(request.app.state.redis, body)
    return ResponseUtil.success(data=result)


@payload_telecontrol_controller.post(
    '/raw/can/send',
    summary='CAN 原始下发(send/sendObj)',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telecontrol:send')],
)
async def send_can_raw(request: Request, body: CanRawSendModel) -> Response:
    result = await PayloadTelecontrolService.send_can_raw(
        request.app.state.redis,
        body.device_id,
        body.frame_id_hex,
        body.data_hex,
    )
    return ResponseUtil.success(data=result)


@payload_telecontrol_controller.get(
    '/history',
    summary='获取发送历史',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telecontrol:send')],
)
async def get_telecontrol_history(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')],
    limit: Annotated[int, Query(description='条数')] = 50,
) -> Response:
    result = await PayloadTelecontrolService.get_send_history(request.app.state.redis, device_id, limit)
    return ResponseUtil.success(data=result)


@payload_telecontrol_controller.delete(
    '/history',
    summary='清空发送历史',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:telecontrol:send')],
)
async def clear_telecontrol_history(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')],
) -> Response:
    await PayloadTelecontrolService.clear_send_history(request.app.state.redis, device_id)
    return ResponseUtil.success(msg='发送历史已清空')


@payload_telecontrol_controller.post(
    '/control/op',
    summary='控制开关操作',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:control:view')],
)
async def telecontrol_control_op(request: Request, body: ControlOpModel) -> Response:
    result = await PayloadTelecontrolService.control_op(request.app.state.redis, body)
    return ResponseUtil.success(data=result)
