from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.entity.vo.payload_device_vo import CanOpenModel, SerialOpenModel
from module_payload.service.payload_device_service import PayloadDeviceService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_device_controller = APIRouterPro(
    prefix='/payload/device', order_num=29, tags=['地检平台-设备'], dependencies=[PreAuthDependency()]
)


@payload_device_controller.get('/can/vendors', summary='列出CAN厂商', response_model=DataResponseModel)
async def list_can_vendors(request: Request) -> Response:
    result = PayloadDeviceService.list_can_vendors()
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/can/list', summary='列出CAN通道', response_model=DataResponseModel)
async def list_can_channels(request: Request) -> Response:
    result = PayloadDeviceService.list_can_channels()
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/can/open', summary='打开CAN通道', response_model=DataResponseModel)
async def open_can_channel(request: Request, body: CanOpenModel) -> Response:
    result = PayloadDeviceService.open_can(body)
    logger.info(f'打开CAN通道 {result["deviceId"]}')
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/can/close', summary='关闭CAN通道', response_model=DataResponseModel)
async def close_can_channel(request: Request, body: CanOpenModel) -> Response:
    result = PayloadDeviceService.close_can(body)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/serial/list', summary='列出串口', response_model=DataResponseModel)
async def list_serial_ports(request: Request) -> Response:
    result = PayloadDeviceService.list_serial_ports()
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/serial/opened', summary='列出已打开串口', response_model=DataResponseModel)
async def list_serial_opened(request: Request) -> Response:
    result = PayloadDeviceService.list_serial_opened()
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/serial/open', summary='打开串口', response_model=DataResponseModel)
async def open_serial_port(request: Request, body: SerialOpenModel) -> Response:
    result = PayloadDeviceService.open_serial(body)
    return ResponseUtil.success(data=result)


@payload_device_controller.post(
    '/serial/close',
    summary='关闭串口',
    response_model=DataResponseModel,
)
async def close_serial_port(
    request: Request,
    port: Annotated[str, Query(description='串口号')],
) -> Response:
    result = PayloadDeviceService.close_serial(port)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/status', summary='查询设备状态', response_model=DataResponseModel)
async def get_device_status(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')],
) -> Response:
    result = await PayloadDeviceService.get_device_status(request.app.state.redis, device_id)
    return ResponseUtil.success(data=result)
