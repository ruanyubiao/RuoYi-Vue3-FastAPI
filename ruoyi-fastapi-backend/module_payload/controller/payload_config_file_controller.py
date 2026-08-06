from typing import Annotated

from fastapi import Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from common.aspect.interface_auth import UserInterfaceAuthDependency
from common.aspect.pre_auth import PreAuthDependency
from common.router import APIRouterPro
from common.vo import DataResponseModel
from module_payload.service.payload_config_file_service import PayloadConfigFileService
from utils.log_util import logger
from utils.response_util import ResponseUtil

payload_config_file_controller = APIRouterPro(
    prefix='/payload/config-files',
    order_num=36,
    tags=['地检平台-配置文件'],
    dependencies=[PreAuthDependency()],
)


class ConfigFileSaveModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    name: str = Field(description='配置文件名')
    content: str = Field(description='JSON 文本内容')


@payload_config_file_controller.get(
    '/list',
    summary='遥控/遥测配置文件列表',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:configfile:view')],
)
async def list_config_files(request: Request) -> Response:
    rows = PayloadConfigFileService.list_files()
    return ResponseUtil.success(data=rows)


@payload_config_file_controller.get(
    '/content',
    summary='读取配置文件原文',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:configfile:view')],
)
async def get_config_file_content(
    request: Request,
    name: Annotated[str, Query(description='文件名')],
) -> Response:
    try:
        data = PayloadConfigFileService.read_text(name)
    except FileNotFoundError as e:
        return ResponseUtil.failure(msg=str(e))
    except ValueError as e:
        return ResponseUtil.failure(msg=str(e))
    return ResponseUtil.success(data=data)


@payload_config_file_controller.put(
    '/content',
    summary='保存配置文件（校验 JSON）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:configfile:edit')],
)
async def save_config_file_content(request: Request, body: ConfigFileSaveModel) -> Response:
    try:
        data = PayloadConfigFileService.save_text(body.name, body.content)
    except FileNotFoundError as e:
        return ResponseUtil.failure(msg=str(e))
    except ValueError as e:
        return ResponseUtil.failure(msg=str(e))
    logger.info(f'配置文件已保存: {body.name}')
    return ResponseUtil.success(msg='保存成功', data=data)


@payload_config_file_controller.post(
    '/reload',
    summary='重新载入配置到运行时缓存（name 为空则全部，否则仅该文件）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:configfile:view')],
)
async def reload_config_files(
    request: Request,
    name: Annotated[str | None, Query(description='可选：仅重载该文件名')] = None,
) -> Response:
    try:
        if name and name.strip():
            data = PayloadConfigFileService.reload_one(name.strip())
            logger.info(f'配置已单文件重载: {data.get("name")}')
            return ResponseUtil.success(msg=f'已重载 {data.get("name")}', data=data)
        data = PayloadConfigFileService.reload_runtime()
        logger.info(f'配置已全部重载: {data.get("count")} 个文件')
        return ResponseUtil.success(msg='配置已全部重新载入', data=data)
    except FileNotFoundError as e:
        return ResponseUtil.failure(msg=str(e))
    except ValueError as e:
        return ResponseUtil.failure(msg=str(e))


@payload_config_file_controller.get(
    '/download',
    summary='下载配置文件',
    response_class=StreamingResponse,
    dependencies=[UserInterfaceAuthDependency('payload:configfile:view')],
)
async def download_config_file(
    request: Request,
    name: Annotated[str, Query(description='文件名')],
) -> Response:
    try:
        data = PayloadConfigFileService.read_text(name)
    except FileNotFoundError as e:
        return ResponseUtil.failure(msg=str(e))
    except ValueError as e:
        return ResponseUtil.failure(msg=str(e))
    content = data['content'].encode('utf-8')
    headers = {
        'Content-Disposition': f"attachment; filename*=UTF-8''{data['name']}",
        'download-filename': data['name'],
    }
    return ResponseUtil.streaming(data=iter([content]), headers=headers, media_type='application/json')


@payload_config_file_controller.get(
    '/export-orders',
    summary='导出遥控配置全部指令（默认参数组帧）',
    response_model=DataResponseModel,
    dependencies=[UserInterfaceAuthDependency('payload:configfile:view')],
)
async def export_config_orders(
    request: Request,
    name: Annotated[str, Query(description='遥控配置文件名')],
) -> Response:
    try:
        rows = PayloadConfigFileService.export_orders_defaults(name)
    except FileNotFoundError as e:
        return ResponseUtil.failure(msg=str(e))
    except ValueError as e:
        return ResponseUtil.failure(msg=str(e))
    logger.info(f'导出指令列表: {name} count={len(rows)}')
    return ResponseUtil.success(data=rows)
