from typing import Annotated, Any

from fastapi import Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.cfg.camera_telecontrol_assembler import assemble_camera_order, assemble_camera_order_by_id
from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.entity.vo.payload_camera_vo import CameraStartModel
from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
from module_payload.service.payload_camera_service import PayloadCameraService
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService
from utils.response_util import ResponseUtil

payload_camera_controller = APIRouterPro(
    prefix='/payload/camera', order_num=33, tags=['地检平台-相机'], dependencies=[PreAuthDependency()]
)


class CameraAssembleModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str
    values: list[Any] = Field(default_factory=list)
    seq: int = 0


class CameraSendModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    order_id: str
    values: list[Any] = Field(default_factory=list)
    seq: int = 0
    name: str | None = None


@payload_camera_controller.get(
    '/telecontrol/config',
    summary='获取相机遥控配置',
    response_model=DataResponseModel,
)
async def get_camera_telecontrol_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    return ResponseUtil.success(data=PayloadConfigService.get_camera_telecontrol_config(reload=reload))


@payload_camera_controller.get(
    '/telemetry/config',
    summary='获取相机遥测配置',
    response_model=DataResponseModel,
)
async def get_camera_telemetry_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    return ResponseUtil.success(data=PayloadConfigService.get_camera_telemetry_config(reload=reload))


@payload_camera_controller.get(
    '/telemetry/table',
    summary='获取相机遥测最新值(D8慢遥/D9快遥)',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def get_camera_telemetry_table(
    request: Request,
    data_id: Annotated[str | None, Query(alias='dataId')] = None,
    need_cfg: Annotated[bool, Query(alias='needCfg')] = False,
    table_key: Annotated[str, Query(alias='tableKey')] = 'D8',
) -> Response:
    key = (table_key or 'D8').strip().upper()
    if key not in ('D8', 'D9'):
        key = 'D8'
    result = await PayloadTelemetryService.get_table(request.app.state.redis, key, data_id, need_cfg=False)
    cam = PayloadConfigLoader.get_camera_telemetry_cfg()
    table_cfg = (cam.get('table') or {}).get(key) or {}
    if need_cfg:
        result['cfg'] = table_cfg
        result['pages'] = cam.get('page') or []
    if not result.get('name'):
        result['name'] = table_cfg.get('name', '慢遥测(全窗)' if key == 'D8' else '快遥测(开窗)')
    result['tableKey'] = key
    # 无热层数据时仍返回配置行，保证前端空表可见
    if not result.get('rows') and (result.get('changed', True) or need_cfg):
        result['rows'] = [
            {
                'id': r.get('id', ''),
                'name': r.get('name', ''),
                'value': '',
                'show': '',
                'unit': r.get('unit', ''),
                'hex': '',
            }
            for r in (table_cfg.get('row') or [])
            if r.get('id')
        ]
        result['changed'] = True
    return ResponseUtil.success(data=result)


@payload_camera_controller.post(
    '/telecontrol/assemble',
    summary='组装相机遥控帧',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def assemble_camera_telecontrol(request: Request, body: CameraAssembleModel) -> Response:
    result = assemble_camera_order_by_id(body.order_id, body.values, seq=body.seq)
    return ResponseUtil.success(data=result)


@payload_camera_controller.post(
    '/telecontrol/send',
    summary='下发相机遥控帧',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:camera:view')],
)
async def send_camera_telecontrol(request: Request, body: CameraSendModel) -> Response:
    cfg = PayloadConfigLoader.get_camera_telecontrol_cfg()
    order = (cfg.get('order') or {}).get(body.order_id) or {}
    assembled = assemble_camera_order(order, body.values, seq=body.seq)
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
    result = await PayloadCameraService.get_camera_status(request.app.state.redis, port)
    return ResponseUtil.success(data=result)
