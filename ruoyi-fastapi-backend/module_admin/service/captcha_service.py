import base64
import io
import os
import random
import uuid
from datetime import timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common.enums import RedisInitKeyConfig
from config.paths import get_package_root
from module_admin.entity.vo.login_vo import CaptchaCode
from utils.log_util import logger


def _captcha_font_path() -> Path | None:
    """包内字体优先，其次系统 Arial；都不存在则返回 None（调用方用默认字体）。"""
    candidates = [get_package_root() / 'assets' / 'font' / 'Arial.ttf']
    if os.name == 'nt':
        windir = Path(os.environ.get('WINDIR') or r'C:\Windows')
        candidates.append(windir / 'Fonts' / 'arial.ttf')
        candidates.append(windir / 'Fonts' / 'Arial.ttf')
    for path in candidates:
        if path.is_file():
            return path
    return None


class CaptchaService:
    """
    验证码模块服务层
    """

    @classmethod
    async def build_captcha_code(cls, redis) -> CaptchaCode:
        """
        组装登录页验证码响应。关闭验证码时不生成图片；生成失败时降级关闭，避免阻断登录。
        """
        captcha_enabled = (
            await redis.get(f'{RedisInitKeyConfig.SYS_CONFIG.key}:sys.account.captchaEnabled') == 'true'
        )
        register_enabled = (
            await redis.get(f'{RedisInitKeyConfig.SYS_CONFIG.key}:sys.account.registerUser') == 'true'
        )
        image = ''
        session_id = ''
        if captcha_enabled:
            try:
                captcha_result = await cls.create_captcha_image_service()
                image = captcha_result[0]
                computed_result = captcha_result[1]
                session_id = str(uuid.uuid4())
                await redis.set(
                    f'{RedisInitKeyConfig.CAPTCHA_CODES.key}:{session_id}',
                    computed_result,
                    ex=timedelta(minutes=2),
                )
                logger.info(f'编号为{session_id}的会话获取图片验证码成功')
            except Exception:
                logger.exception('生成验证码失败，降级为关闭验证码以免阻断登录')
                captcha_enabled = False
        return CaptchaCode(
            captchaEnabled=captcha_enabled, registerEnabled=register_enabled, img=image, uuid=session_id
        )

    @classmethod
    async def create_captcha_image_service(cls) -> list:
        image = Image.new('RGB', (160, 60), color='#EAEAEA')
        draw = ImageDraw.Draw(image)
        font_file = _captcha_font_path()
        try:
            font = ImageFont.truetype(str(font_file), size=30) if font_file else ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()

        num1 = random.randint(0, 9)
        num2 = random.randint(0, 9)
        operational_character_list = ['+', '-', '*']
        operational_character = random.choice(operational_character_list)
        if operational_character == '+':
            result = num1 + num2
        elif operational_character == '-':
            result = num1 - num2
            if result < 0:
                num1, num2 = num2, num1
                result = num1 - num2
        else:
            result = num1 * num2
        text = f'{num1} {operational_character} {num2} = ?'
        draw.text((25, 15), text, fill='blue', font=font)

        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        base64_string = base64.b64encode(buffer.getvalue()).decode()
        return [base64_string, result]
