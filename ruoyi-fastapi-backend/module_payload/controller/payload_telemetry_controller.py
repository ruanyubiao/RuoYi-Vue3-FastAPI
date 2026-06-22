from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.service.payload_config_service import PayloadConfigService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_telemetry_controller = APIRouterPro(
    prefix='/payload/telemetry', order_num=32, tags=['地检平台-遥测'], dependencies=[PreAuthDependency()]
)


@payload_telemetry_controller.get(
    '/config',
    summary='获取遥测页配置接口',
    description='读取 TeleMetryCfg.json 的 page 列表，用于二级菜单与遥测表切换下拉',
    response_model=DataResponseModel,
)
async def get_telemetry_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
) -> Response:
    result = PayloadConfigService.get_telemetry_pages(reload=reload)
    logger.info('获取遥测页配置成功')

    return ResponseUtil.success(data=result)


@payload_telemetry_controller.get(
    '/def',
    summary='获取遥测表定义接口',
    description='按数据类型返回遥测表字段定义(row)，用于渲染表头/描述与曲线遥测量下拉',
    response_model=DataResponseModel,
)
async def get_telemetry_table_def(
    request: Request,
    type: Annotated[str, Query(description='遥测数据类型(HEX, 如 FF)')],
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
) -> Response:
    result = PayloadConfigService.get_telemetry_table_def(type, reload=reload)
    logger.info(f'获取遥测表[{type}]定义成功')

    return ResponseUtil.success(data=result)
