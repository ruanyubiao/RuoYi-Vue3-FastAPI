from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from exceptions.exception import ServiceException
from module_payload.entity.vo.payload_device_vo import (
    CanCableUpdateModel,
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


@payload_device_controller.get(
    '/connect-defaults',
    summary='设备默认连接配置',
    response_model=DataResponseModel,
)
async def get_device_connect_defaults(
    key: Annotated[str | None, Query(description='来源唯一标识，如 camera_ctrl；空则返回全部')] = None,
) -> Response:
    """设备默认连接配置。"""
    from module_payload.cfg.payload_config_loader import PayloadConfigLoader

    if key and key.strip():
        entry = PayloadConfigLoader.get_device_connect_entry(key.strip())
        if not entry:
            raise ServiceException(message=f'未找到连接默认配置: {key}')
        return ResponseUtil.success(data={'key': key.strip(), 'entry': entry})
    return ResponseUtil.success(data=PayloadConfigLoader.get_device_connect_cfg())


@payload_device_controller.get('/version', summary='地检平台服务版本', response_model=DataResponseModel)
async def get_payload_app_version() -> Response:
    """地检平台服务版本。"""
    from version import appVersion

    return ResponseUtil.success(data={'appVersion': appVersion})


@payload_device_controller.get('/can/vendors', summary='列出CAN厂商', response_model=DataResponseModel)
async def list_can_vendors(request: Request) -> Response:
    """列出CAN厂商。"""
    result = PayloadDeviceService.list_can_vendors()
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/can/list', summary='列出CAN通道', response_model=DataResponseModel)
async def list_can_channels(request: Request) -> Response:
    """列出CAN通道。"""
    result = PayloadDeviceService.list_can_channels()
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/can/open', summary='打开CAN通道', response_model=DataResponseModel)
async def open_can_channel(request: Request, body: CanOpenModel) -> Response:
    """打开CAN通道。"""
    result = await PayloadDeviceService.open_can(body)
    logger.info(f'打开CAN通道 {result["deviceId"]}')
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/can/close', summary='关闭CAN通道', response_model=DataResponseModel)
async def close_can_channel(request: Request, body: CanOpenModel) -> Response:
    """关闭CAN通道。"""
    result = await PayloadDeviceService.close_can(body)
    return ResponseUtil.success(data=result)


@payload_device_controller.post(
    '/can/cable',
    summary='更新CAN业务线缆参数',
    description='热更新已打开通道的目标地址/线缆（不重开设备）',
    response_model=DataResponseModel,
)
async def set_can_cable(request: Request, body: CanCableUpdateModel) -> Response:
    """更新CAN业务线缆参数。"""
    result = await PayloadDeviceService.set_can_cable(body)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/serial/list', summary='列出串口', response_model=DataResponseModel)
async def list_serial_ports(request: Request) -> Response:
    """列出串口。"""
    result = PayloadDeviceService.list_serial_ports()
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/serial/opened', summary='列出已打开串口', response_model=DataResponseModel)
async def list_serial_opened(request: Request) -> Response:
    """列出已打开串口。"""
    result = PayloadDeviceService.list_serial_opened()
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/serial/open', summary='打开串口', response_model=DataResponseModel)
async def open_serial_port(request: Request, body: SerialOpenModel) -> Response:
    """打开串口。"""
    try:
        result = await PayloadDeviceService.open_serial(body)
    except RuntimeError as e:
        raise ServiceException(message=str(e)) from e
    except ServiceException:
        raise
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
    """关闭串口。"""
    result = await PayloadDeviceService.close_serial(port)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/net/addresses', summary='列出本机地址', response_model=DataResponseModel)
async def list_local_addresses(request: Request) -> Response:
    """列出本机地址。"""
    result = PayloadDeviceService.list_local_addresses()
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/net/opened', summary='列出已打开网络连接', response_model=DataResponseModel)
async def list_net_opened(request: Request) -> Response:
    """列出已打开网络连接。"""
    result = PayloadDeviceService.list_net_opened()
    return ResponseUtil.success(data=result)


@payload_device_controller.post('/net/open', summary='打开网络连接(UDP)', response_model=DataResponseModel)
async def open_net(request: Request, body: NetOpenModel) -> Response:
    """打开网络连接(UDP)。"""
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
    """关闭网络连接。"""
    result = await PayloadDeviceService.close_net(body.proto, body.local_host, body.local_port)
    return ResponseUtil.success(data=result)


@payload_device_controller.post(
    '/close-all',
    summary='关闭全部设备连接',
    description='一次性关闭当前已打开的 CAN / 串口 / UDP，避免前端连打单条 close',
    response_model=DataResponseModel,
)
async def close_all_devices(request: Request) -> Response:
    """关闭全部设备连接。"""
    result = await PayloadDeviceService.close_all()
    logger.info(f'关闭全部连接 ok={result.get("ok")} fail={result.get("fail")}')
    return ResponseUtil.success(data=result, msg='已关闭全部连接')


@payload_device_controller.get('/io-log', summary='查询设备原始收发日志', response_model=DataResponseModel)
async def get_device_io_log(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId')],
    since_seq: Annotated[int, Query(alias='sinceSeq')] = 0,
    limit: Annotated[int, Query()] = 200,
) -> Response:
    """查询设备原始收发日志。"""
    result = await PayloadDeviceService.get_io_log(request.app.state.redis, device_id, since_seq, limit)
    return ResponseUtil.success(data=result)


@payload_device_controller.delete('/io-log', summary='清空设备原始收发日志', response_model=DataResponseModel)
async def clear_device_io_log(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId')],
) -> Response:
    """清空设备原始收发日志。"""
    result = await PayloadDeviceService.clear_io_log(request.app.state.redis, device_id)
    return ResponseUtil.success(data=result)


@payload_device_controller.get(
    '/snapshot',
    summary='设备只读数据批量快照',
    description='parts 逗号分隔：can,serialList,serialOpened,netOpened,sessions,parsers,assemblers',
    response_model=DataResponseModel,
)
async def get_device_snapshot(
    request: Request,
    parts: Annotated[
        str,
        Query(description='逗号分隔的数据块，如 serialOpened,parsers,assemblers'),
    ] = '',
) -> Response:
    """设备只读数据批量快照。"""
    result = await PayloadDeviceService.get_snapshot(request.app.state.redis, parts)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/status', summary='查询设备状态', response_model=DataResponseModel)
async def get_device_status(
    request: Request,
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')],
) -> Response:
    """查询设备状态。"""
    result = await PayloadDeviceService.get_device_status(request.app.state.redis, device_id)
    return ResponseUtil.success(data=result)


@payload_device_controller.get('/parsers', summary='列出可用解释器', response_model=DataResponseModel)
async def list_parsers(request: Request) -> Response:
    """列出可用解释器。"""
    return ResponseUtil.success(data=PayloadSessionService.list_parser_options())


@payload_device_controller.get('/assemblers', summary='列出可用组装器', response_model=DataResponseModel)
async def list_assemblers(request: Request, srcKind: str | None = None) -> Response:
    """列出可用组装器。"""
    # srcKind=can 时仅返回 CAN-BIU/CAN-XL；其它类型排除 CAN 专属组装器
    return ResponseUtil.success(data=PayloadSessionService.list_assembler_options(srcKind))


@payload_device_controller.get('/sessions', summary='列出已打开设备会话', response_model=DataResponseModel)
async def list_sessions(request: Request) -> Response:
    """列出已打开设备会话。"""
    result = await PayloadDeviceService.list_alive_sessions(request.app.state.redis)
    return ResponseUtil.success(data=result)


@payload_device_controller.post(
    '/bind-parser',
    summary='绑定/解绑解释器与组装器',
    description='parserId 为空则解绑解释器；assemblerId 在 updateAssembler=true 时写入（默认透传）',
    response_model=DataResponseModel,
)
async def bind_parser(request: Request, body: DeviceBindParserModel) -> Response:
    """绑定/解绑解释器与组装器。"""
    result = await PayloadSessionService.bind_parser(
        request.app.state.redis,
        src_param=body.src_param,
        parser_id=body.parser_id,
        src_kind=body.src_kind,
        assembler_id=body.assembler_id,
        update_assembler=body.update_assembler,
        routes=body.routes,
        update_routes=body.update_routes,
        source=body.source,
    )
    if body.source is not None or body.update_routes or body.routes is not None:
        from module_payload.collectors.process_manager import CollectorProcessManager

        CollectorProcessManager.instance().notify_session_changed(body.src_param)
    logger.info(
        f'设备绑定 src={body.src_param} parser={body.parser_id or "(解绑)"} '
        f'assembler={result.get("assemblerId") or "passthrough"} '
        f'routes={len(result.get("routes") or [])} '
        f'source={result.get("source") or ""}'
    )
    return ResponseUtil.success(data=result, msg='绑定已更新')
