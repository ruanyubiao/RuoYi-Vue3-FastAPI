from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.service.payload_lvds_service import PayloadLvdsService
from utils.response_util import ResponseUtil

payload_lvds_controller = APIRouterPro(
    prefix='/payload/lvds', order_num=34, tags=['地检平台-LVDS'], dependencies=[PreAuthDependency()]
)


@payload_lvds_controller.get(
    '/signals',
    summary='获取工程遥测信号列表',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:lvds:view')],
)
async def list_lvds_signals(
    request: Request,
    type: Annotated[str, Query(description='工程遥测表类型', alias='type')] = '7E9B',
) -> Response:
    result = PayloadLvdsService.list_signals(type)
    return ResponseUtil.success(data=result)


@payload_lvds_controller.get(
    '/data',
    summary='获取工程遥测波形数据',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:lvds:view')],
)
async def get_lvds_data(
    request: Request,
    signal: Annotated[str, Query(description='信号ID')],
    device_id: Annotated[str, Query(alias='deviceId', description='设备ID')] = 'lvds:demo',
    limit: Annotated[int, Query(description='点数上限')] = 2000,
) -> Response:
    result = await PayloadLvdsService.get_data(request.app.state.redis, signal, device_id, limit)
    return ResponseUtil.success(data=result)
