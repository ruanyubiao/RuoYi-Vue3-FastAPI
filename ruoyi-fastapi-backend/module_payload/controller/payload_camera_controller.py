from typing import Annotated, Any

from fastapi import Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_camera
from module_payload.entity.vo.payload_camera_vo import CameraStartModel
from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
from module_payload.service.payload_camera_service import PayloadCameraService
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from utils.response_util import ResponseUtil

payload_camera_controller = APIRouterPro(
    prefix='/payload/camera', order_num=33, tags=['地检平台-相机'], dependencies=[PreAuthDependency()]
)


class CameraAssembleModel(BaseModel):
    """相机遥控组帧请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str
    values: list[Any] = Field(default_factory=list)
    seq: int = 0
    protocol: str = 'v16'


class CameraSendModel(BaseModel):
    """相机遥控下发请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    order_id: str
    values: list[Any] = Field(default_factory=list)
    seq: int = 0
    name: str | None = None
    protocol: str = 'v16'


@payload_camera_controller.get(
    '/telecontrol/config',
    summary='获取相机遥控配置',
    response_model=DataResponseModel,
)
async def get_camera_telecontrol_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
    protocol: Annotated[str, Query(description='v16|v17')] = 'v16',
) -> Response:
    """获取相机遥控配置。"""
    return ResponseUtil.success(
        data=PayloadConfigService.get_camera_telecontrol_config(reload=reload, protocol=protocol)
    )


@payload_camera_controller.get(
    '/telemetry/config',
    summary='获取相机遥测配置',
    response_model=DataResponseModel,
)
async def get_camera_telemetry_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
    protocol: Annotated[str, Query(description='v16|v17')] = 'v16',
) -> Response:
    """获取相机遥测配置。"""
    return ResponseUtil.success(
        data=PayloadConfigService.get_camera_telemetry_config(reload=reload, protocol=protocol)
    )


@payload_camera_controller.post(
    '/telecontrol/assemble',
    summary='组装相机遥控帧',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def assemble_camera_telecontrol(request: Request, body: CameraAssembleModel) -> Response:
    """组装相机遥控帧。"""
    result = TeleControlCfgManager.assemble(
        cfg_id_for_camera(body.protocol), body.order_id, body.values, seq=body.seq
    )
    return ResponseUtil.success(data=result)


@payload_camera_controller.post(
    '/telecontrol/send',
    summary='下发相机遥控帧',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def send_camera_telecontrol(request: Request, body: CameraSendModel) -> Response:
    """下发相机遥控帧。"""
    cfg_id = cfg_id_for_camera(body.protocol)
    tc = TeleControlCfgManager.get(cfg_id)
    order = tc.get_order(body.order_id)
    assembled = TeleControlCfgManager.assemble(cfg_id, body.order_id, body.values, seq=body.seq)
    send_body = TelecontrolSendModel.model_validate(
        {
            'deviceId': body.device_id,
            'orderId': body.order_id,
            'name': body.name or order.get('name') or body.order_id,
            'hex': assembled['hex'],
        }
    )
    result = await PayloadTelecontrolService.send(request.app.state.redis, send_body)
    result['hex'] = assembled['hex']
    result['seq'] = assembled['seq']
    return ResponseUtil.success(data=result)


@payload_camera_controller.post(
    '/start',
    summary='启动相机采集',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def start_camera(request: Request, body: CameraStartModel) -> Response:
    """启动相机采集。"""
    result = PayloadCameraService.start(body)
    return ResponseUtil.success(data=result)


@payload_camera_controller.post(
    '/stop',
    summary='停止相机采集',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def stop_camera(
    request: Request,
    port: Annotated[str, Query(description='串口号')],
) -> Response:
    """停止相机采集。"""
    result = PayloadCameraService.stop(port)
    return ResponseUtil.success(data=result)


@payload_camera_controller.get(
    '/image',
    summary='获取最新图像与采集状态',
    description='返回 { image: {meta,data,format}, status: {deviceId,connected,message,state} }，均读 Redis',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def get_camera_image(
    request: Request,
    port: Annotated[str, Query(description='串口号')],
) -> Response:
    """获取最新图像与采集状态。"""
    result = await PayloadCameraService.get_image(request.app.state.redis, port)
    return ResponseUtil.success(data=result)


@payload_camera_controller.get(
    '/status',
    summary='获取相机采集状态',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def get_camera_status(
    request: Request,
    port: Annotated[str, Query(description='串口号')],
) -> Response:
    """获取相机采集状态。"""
    result = await PayloadCameraService.get_camera_status(request.app.state.redis, port)
    return ResponseUtil.success(data=result)
