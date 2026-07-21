from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_device_vo import (
    CanOpenModel,
    DeviceBindParserModel,
    NetOpenModel,
    SerialOpenModel,
)
from module_payload.service.payload_device_service import PayloadDeviceService
from module_payload.service.payload_session_service import PayloadSessionService
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
    result = await PayloadDeviceService.open_can(body)
    logger.info(f'打开CAN通道 {result["deviceId"]}')
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/can/close', summary='关闭CAN通道', response_model=DataResponseModel)
async def close_can_channel(request: Request, body: CanOpenModel) -> Response:
    result = await PayloadDeviceService.close_can(body)
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
    try:
        result = await PayloadDeviceService.open_serial(body)
    except RuntimeError as e:
        raise ServiceException(message=str(e)) from e
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
    result = await PayloadDeviceService.close_serial(port)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/net/addresses', summary='列出本机地址', response_model=DataResponseModel)
async def list_local_addresses(request: Request) -> Response:
    result = PayloadDeviceService.list_local_addresses()
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/net/opened', summary='列出已打开网络连接', response_model=DataResponseModel)
async def list_net_opened(request: Request) -> Response:
    result = PayloadDeviceService.list_net_opened()
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/net/open', summary='打开网络连接(UDP)', response_model=DataResponseModel)
async def open_net(request: Request, body: NetOpenModel) -> Response:
    try:
        result = await PayloadDeviceService.open_net(body)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    except RuntimeError as e:
        raise ServiceException(message=str(e)) from e
    logger.info(f'打开网络连接 {result["deviceId"]}')
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/net/close', summary='关闭网络连接', response_model=DataResponseModel)
async def close_net(request: Request, body: NetOpenModel) -> Response:
    result = await PayloadDeviceService.close_net(body.proto, body.local_host, body.local_port)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/io-log', summary='查询设备原始收发日志', response_model=DataResponseModel)
async def get_device_io_log(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId')],
    since_seq: Annotated[int, Query(alias='sinceSeq')] = 0,
    limit: Annotated[int, Query()] = 200,
) -> Response:
    result = await PayloadDeviceService.get_io_log(request.app.state.redis, device_id, since_seq, limit)
    return ResponseUtil.success(data=result)


@payload_device_controller.delete('/io-log', summary='清空设备原始收发日志', response_model=DataResponseModel)
async def clear_device_io_log(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId')],
) -> Response:
    result = await PayloadDeviceService.clear_io_log(request.app.state.redis, device_id)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/status', summary='查询设备状态', response_model=DataResponseModel)
async def get_device_status(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')],
) -> Response:
    result = await PayloadDeviceService.get_device_status(request.app.state.redis, device_id)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/parsers', summary='列出可用解释器', response_model=DataResponseModel)
async def list_parsers(request: Request) -> Response:
    return ResponseUtil.success(data=PayloadSessionService.list_parser_options())


@payload_device_controller.get('/sessions', summary='列出已打开设备会话', response_model=DataResponseModel)
async def list_sessions(request: Request) -> Response:
    result = await PayloadSessionService.list_sessions(request.app.state.redis)
    return ResponseUtil.success(data=result)


@payload_device_controller.post(
    '/bind-parser',
    summary='绑定/解绑解释器',
    description='parserId 为空则解绑；未绑定的设备采集数据不会解析、不写遥测归档',
    response_model=DataResponseModel,
)
async def bind_parser(request: Request, body: DeviceBindParserModel) -> Response:
    result = await PayloadSessionService.bind_parser(
        request.app.state.redis,
        src_param=body.src_param,
        parser_id=body.parser_id,
        src_kind=body.src_kind,
    )
    logger.info(f'设备绑定解释器 src={body.src_param} parser={body.parser_id or "(解绑)"}')
    return ResponseUtil.success(data=result, msg='绑定已更新')
