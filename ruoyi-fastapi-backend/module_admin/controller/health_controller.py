"""免登录健康检查接口。"""

from fastapi import Request
from fastapi.responses import JSONResponse

from common.router import APIRouterPro
from module_admin.service.health_service import HealthService

health_controller = APIRouterPro(order_num=0, tags=['健康检查'])


@health_controller.get(
    '/health',
    summary='服务健康检查',
    description='免登录。返回服务基本信息以及数据库、Redis 连通性。依赖异常时 HTTP 503。',
)
async def health(request: Request) -> JSONResponse:
    payload, status_code = await HealthService.check(getattr(request.app.state, 'redis', None))
    return JSONResponse(content=payload, status_code=status_code)
