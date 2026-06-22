from typing import Annotated

from fastapi import Query, Request, Response

from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.service.payload_config_service import PayloadConfigService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_telecontrol_controller = APIRouterPro(
    prefix='/payload/telecontrol', order_num=31, tags=['地检平台-遥控'], dependencies=[PreAuthDependency()]
)


@payload_telecontrol_controller.get(
    '/config',
    summary='获取遥控配置接口',
    description='读取 TeleControlCfg.json，返回分类页与指令定义，用于构建遥控指令树与参数表单',
    response_model=DataResponseModel,
)
async def get_telecontrol_config(
    request: Request,
    reload: Annotated[bool, Query(description='是否强制重新加载配置文件')] = False,
) -> Response:
    result = PayloadConfigService.get_telecontrol_config(reload=reload)
    logger.info('获取遥控配置成功')

    return ResponseUtil.success(data=result)
