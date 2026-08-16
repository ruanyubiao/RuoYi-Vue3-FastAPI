from fastapi import Request, Response

from common.annotation.rate_limit_annotation import ApiRateLimit, ApiRateLimitPreset
from common.constant import ApiNamespace
from common.router import APIRouterPro
from common.vo import DynamicResponseModel
from module_admin.entity.vo.login_vo import CaptchaCode
from module_admin.service.captcha_service import CaptchaService
from utils.response_util import ResponseUtil

captcha_controller = APIRouterPro(order_num=2, tags=['验证码模块'])


@captcha_controller.get(
    '/captchaImage',
    summary='获取图片验证码接口',
    description='用于获取图片验证码',
    response_model=DynamicResponseModel[CaptchaCode],
)
@ApiRateLimit(namespace=ApiNamespace.CAPTCHA_IMAGE, preset=ApiRateLimitPreset.ANON_AUTH_CAPTCHA)
async def get_captcha_image(request: Request) -> Response:
    return ResponseUtil.success(
        model_content=await CaptchaService.build_captcha_code(request.app.state.redis)
    )
