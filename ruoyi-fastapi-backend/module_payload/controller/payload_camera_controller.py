from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.entity.vo.payload_camera_vo import CameraStartModel
from module_payload.service.payload_camera_service import PayloadCameraService
from utils.response_util import ResponseUtil

payload_camera_controller = APIRouterPro(
    prefix='/payload/camera', order_num=33, tags=['地检平台-相机'], dependencies=[PreAuthDependency()]
)


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
    summary='获取最新图像',
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
