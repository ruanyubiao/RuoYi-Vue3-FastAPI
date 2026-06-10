import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.env import AppConfig
from exceptions.handle import handle_exception
from middlewares.handle import handle_middleware
from sub_applications.handle import handle_sub_applications
from utils.common_util import worship
from utils.log_util import logger
from utils.server_util import APIDocsUtil, IPUtil


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    应用生命周期管理（无数据库、无 Redis 版本）

    :param app: FastAPI 对象
    :return: None
    """
    # 启动阶段
    logger.info(f'⏰️ {AppConfig.app_name}开始启动')
    worship()
    logger.info(f'🚀 {AppConfig.app_name}启动成功')
    
    host = AppConfig.app_host
    port = AppConfig.app_port
    if host == '0.0.0.0':
        local_ip = IPUtil.get_local_ip()
        network_ips = IPUtil.get_network_ips()
    else:
        local_ip = host
        network_ips = [host]

    app_links = [f'🏠 Local:    <cyan>http://{local_ip}:{port}</cyan>']
    app_links.extend(f'📡 Network:  <cyan>http://{ip}:{port}</cyan>' for ip in network_ips)
    logger.opt(colors=True).info('💻 应用地址:\n' + '\n'.join(app_links))

    if not AppConfig.app_disable_swagger:
        swagger_links = [f'🏠 Local:    <cyan>http://{local_ip}:{port}{APIDocsUtil.docs_url()}</cyan>']
        swagger_links.extend(
            f'📡 Network:  <cyan>http://{ip}:{port}{APIDocsUtil.docs_url()}</cyan>' for ip in network_ips
        )
        logger.opt(colors=True).info('📄 Swagger 文档:\n' + '\n'.join(swagger_links))

    if not AppConfig.app_disable_redoc:
        redoc_links = [f'🏠 Local:    <cyan>http://{local_ip}:{port}{APIDocsUtil.redoc_url()}</cyan>']
        redoc_links.extend(
            f'📡 Network:  <cyan>http://{ip}:{port}{APIDocsUtil.redoc_url()}</cyan>' for ip in network_ips
        )
        logger.opt(colors=True).info('📚 ReDoc 文档:\n' + '\n'.join(redoc_links))
    
    yield
    
    # 关闭阶段
    logger.info(f'👋 {AppConfig.app_name}已关闭')


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用（轻量化版本）

    :return: FastAPI 对象
    """
    # 配置 API 文档静态资源
    APIDocsUtil.setup_docs_static_resources()
    # 初始化 FastAPI 对象
    app = FastAPI(
        title=AppConfig.app_name,
        description=f'{AppConfig.app_name}接口文档',
        version=AppConfig.app_version,
        lifespan=lifespan,
        openapi_url=APIDocsUtil.proxy_openapi_url(),
        docs_url=APIDocsUtil.proxy_docs_url(),
        redoc_url=APIDocsUtil.proxy_redoc_url(),
        swagger_ui_oauth2_redirect_url=APIDocsUtil.proxy_oauth2_redirect_url(),
    )

    # 自定义 API 文档路由
    APIDocsUtil.custom_api_docs_router(app)

    # 挂载子应用
    handle_sub_applications(app)
    # 加载中间件处理方法
    handle_middleware(app)
    # 加载全局异常处理方法
    handle_exception(app)
    # 自动注册路由（只保留业务模块）
    from common.router import auto_register_routers
    auto_register_routers(app, exclude_modules=['module_admin', 'module_ai', 'module_generator'])

    return app
