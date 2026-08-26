"""XL 单板（热控电机 / CPA-ZK / 地检）遥控遥测 API。"""

from typing import Annotated, Any

from fastapi import Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, cfg_id_for_board
from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from utils.response_util import ResponseUtil

payload_xl_board_controller = APIRouterPro(
    prefix='/payload/board', order_num=34, tags=['地检平台-XL单板'], dependencies=[PreAuthDependency()]
)


class XlBoardAssembleModel(BaseModel):
    """XL 单板遥控组帧请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str
    values: list[Any] = Field(default_factory=list)


class XlBoardSendModel(BaseModel):
    """XL 单板遥控下发请求。"""

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
    board: Annotated[str, Path(description='rkdj | zk | dj')],
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    """获取 XL 单板遥控配置。"""
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
    board: Annotated[str, Path(description='rkdj | zk | dj')],
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    """获取 XL 单板遥测配置。"""
    try:
        data = PayloadConfigService.get_xl_board_telemetry_config(board, reload=reload)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=data)


@payload_xl_board_controller.post(
    '/{board}/telecontrol/assemble',
    summary='组装 XL 单板遥控帧',
    response_model=DataResponseModel,
)
async def assemble_xl_board_telecontrol(
    request: Request,
    board: Annotated[str, Path(description='rkdj | zk | dj')],
    body: XlBoardAssembleModel,
) -> Response:
    """组装 XL 单板遥控帧。"""
    try:
        result = TeleControlCfgManager.assemble(cfg_id_for_board(board), body.order_id, body.values)
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
    board: Annotated[str, Path(description='rkdj | zk | dj')],
    body: XlBoardSendModel,
) -> Response:
    """下发 XL 单板遥控帧。"""
    try:
        cfg_id = cfg_id_for_board(board)
        tc = TeleControlCfgManager.get(cfg_id)
        order = tc.get_order(body.order_id)
        assembled = TeleControlCfgManager.assemble(cfg_id, body.order_id, body.values)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
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
