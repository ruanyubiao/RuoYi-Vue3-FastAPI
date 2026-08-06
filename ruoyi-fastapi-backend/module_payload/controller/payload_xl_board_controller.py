"""XL 单板（热控电机 / CPA-ZK）遥控遥测 API。"""

from typing import Annotated, Any

from fastapi import Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from exceptions.exception import ServiceException
from module_payload.cfg.payload_config_loader import PayloadConfigLoader
from module_payload.cfg.xl_board_telecontrol_assembler import (
    assemble_xl_board_order,
    assemble_xl_board_order_by_id,
)
from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from module_payload.service.payload_telemetry_service import PayloadTelemetryService
from utils.response_util import ResponseUtil

payload_xl_board_controller = APIRouterPro(
    prefix='/payload/board', order_num=34, tags=['地检平台-XL单板'], dependencies=[PreAuthDependency()]
)


class XlBoardAssembleModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str
    values: list[Any] = Field(default_factory=list)


class XlBoardSendModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    order_id: str
    values: list[Any] = Field(default_factory=list)
    name: str | None = None


@payload_xl_board_controller.get(
    '/{board}/telecontrol/config',
    summary='获取 XL 单板遥控配置',
    response_model=DataResponseModel,
)
async def get_xl_board_telecontrol_config(
    request: Request,
    board: Annotated[str, Path(description='rkdj | zk')],
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    try:
        data = PayloadConfigService.get_xl_board_telecontrol_config(board, reload=reload)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=data)


@payload_xl_board_controller.get(
    '/{board}/telemetry/config',
    summary='获取 XL 单板遥测配置',
    response_model=DataResponseModel,
)
async def get_xl_board_telemetry_config(
    request: Request,
    board: Annotated[str, Path(description='rkdj | zk')],
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    try:
        data = PayloadConfigService.get_xl_board_telemetry_config(board, reload=reload)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=data)


@payload_xl_board_controller.get(
    '/{board}/telemetry/table',
    summary='获取 XL 单板遥测最新值',
    response_model=DataResponseModel,
)
async def get_xl_board_telemetry_table(
    request: Request,
    board: Annotated[str, Path(description='rkdj | zk')],
    data_id: Annotated[str | None, Query(alias='dataId')] = None,
    need_cfg: Annotated[bool, Query(alias='needCfg')] = False,
) -> Response:
    try:
        b = PayloadConfigLoader.normalize_xl_board(board)
        table_key = PayloadConfigLoader.xl_board_tm_table_key(b)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e

    # 权限按板卡区分；依赖在路由级不便动态绑定，此处二次校验由前端菜单控制，后端用统一 token
    result = await PayloadTelemetryService.get_table(request.app.state.redis, table_key, data_id, need_cfg=False)
    cfg = PayloadConfigLoader.get_xl_board_telemetry_cfg(b)
    table_cfg = (cfg.get('table') or {}).get(table_key) or {}
    if need_cfg:
        result['cfg'] = table_cfg
        result['pages'] = PayloadConfigLoader.tables_to_page_list(cfg)
    if not result.get('name'):
        result['name'] = table_cfg.get('name', table_key)
    result['tableKey'] = table_key
    result['board'] = b
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


@payload_xl_board_controller.post(
    '/{board}/telecontrol/assemble',
    summary='组装 XL 单板遥控帧',
    response_model=DataResponseModel,
)
async def assemble_xl_board_telecontrol(
    request: Request,
    board: Annotated[str, Path(description='rkdj | zk')],
    body: XlBoardAssembleModel,
) -> Response:
    try:
        result = assemble_xl_board_order_by_id(board, body.order_id, body.values)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=result)


@payload_xl_board_controller.post(
    '/{board}/telecontrol/send',
    summary='下发 XL 单板遥控帧',
    response_model=DataResponseModel,
)
async def send_xl_board_telecontrol(
    request: Request,
    board: Annotated[str, Path(description='rkdj | zk')],
    body: XlBoardSendModel,
) -> Response:
    try:
        cfg = PayloadConfigLoader.get_xl_board_telecontrol_cfg(board)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    order = (cfg.get('order') or {}).get(body.order_id) or {}
    assembled = assemble_xl_board_order(order, body.values)
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
    result['length'] = assembled.get('length')
    if assembled.get('tip'):
        result['tip'] = assembled['tip']
        result['lengthCorrected'] = assembled.get('lengthCorrected')
    return ResponseUtil.success(data=result)
