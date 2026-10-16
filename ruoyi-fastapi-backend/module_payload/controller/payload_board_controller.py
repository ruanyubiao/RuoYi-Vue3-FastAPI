"""单板遥控遥测 API：路径 ``/payload/board/{family}/{board}/...``，cfgId 为 ``{family}-{board}-tc``。"""

from typing import Annotated, Any

from fastapi import Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from exceptions.exception import ServiceException
from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, board_cfg_id
from module_payload.entity.vo.payload_telecontrol_vo import TelecontrolSendModel
from module_payload.perms import board_operate, board_query
from module_payload.service.payload_config_service import PayloadConfigService
from module_payload.service.payload_telecontrol_service import PayloadTelecontrolService
from utils.response_util import ResponseUtil

payload_board_controller = APIRouterPro(
    prefix='/payload/board', order_num=34, tags=['地检平台-单板'], dependencies=[PreAuthDependency()]
)

FamilyPath = Annotated[str, Path(description='总线族，如 xl')]
BoardPath = Annotated[str, Path(description='单板名，如 rkdj | zk | dj | cpazx')]


class BoardAssembleModel(BaseModel):
    """单板遥控组帧请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str
    values: list[Any] = Field(default_factory=list)


class BoardSendModel(BaseModel):
    """单板遥控下发请求。"""

    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    order_id: str
    values: list[Any] = Field(default_factory=list)
    name: str | None = None
    wait: bool = Field(default=True, description='False 只入队不等待执行结果')


@payload_board_controller.get(
    '/{family}/{board}/telecontrol/config',
    summary='获取单板遥控配置',
    response_model=DataResponseModel,
    dependencies=[board_query()],
)
async def get_board_telecontrol_config(
    request: Request,
    family: FamilyPath,
    board: BoardPath,
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    """获取单板遥控配置。"""
    try:
        data = PayloadConfigService.get_board_telecontrol_config(family, board, reload=reload)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=data)


@payload_board_controller.get(
    '/{family}/{board}/telemetry/config',
    summary='获取单板遥测配置',
    response_model=DataResponseModel,
    dependencies=[board_query()],
)
async def get_board_telemetry_config(
    request: Request,
    family: FamilyPath,
    board: BoardPath,
    reload: Annotated[bool, Query(description='是否强制重新加载')] = False,
) -> Response:
    """获取单板遥测配置。"""
    try:
        data = PayloadConfigService.get_board_telemetry_config(family, board, reload=reload)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=data)


@payload_board_controller.post(
    '/{family}/{board}/telecontrol/assemble',
    summary='组装单板遥控帧',
    response_model=DataResponseModel,
    dependencies=[board_operate()],
)
async def assemble_board_telecontrol(
    request: Request,
    family: FamilyPath,
    board: BoardPath,
    body: BoardAssembleModel,
) -> Response:
    """组装单板遥控帧。"""
    try:
        result = TeleControlCfgManager.assemble(board_cfg_id(family, board), body.order_id, body.values)
    except ValueError as e:
        raise ServiceException(message=str(e)) from e
    return ResponseUtil.success(data=result)


@payload_board_controller.post(
    '/{family}/{board}/telecontrol/send',
    summary='下发单板遥控帧',
    response_model=DataResponseModel,
    dependencies=[board_operate()],
)
async def send_board_telecontrol(
    request: Request,
    family: FamilyPath,
    board: BoardPath,
    body: BoardSendModel,
) -> Response:
    """下发单板遥控帧。"""
    try:
        cfg_id = board_cfg_id(family, board)
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
    result = await PayloadTelecontrolService.send(request.app.state.redis, send_body, wait=body.wait)
    table_key = assembled.get('tableKey')
    if table_key:
        from module_payload.protocol.yj216.rs422.tm import remember_last_table

        await remember_last_table(request.app.state.redis, body.device_id, str(table_key))
    result['hex'] = assembled['hex']
    result['length'] = assembled.get('length')
    if assembled.get('tip'):
        result['tip'] = assembled['tip']
        result['lengthCorrected'] = assembled.get('lengthCorrected')
    return ResponseUtil.success(data=result)
