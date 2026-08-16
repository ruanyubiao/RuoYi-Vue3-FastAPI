import base64
import io
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config.paths import get_package_root


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
    async def create_captcha_image_service(cls) -> list[str, int]:
        # 创建空白图像
        image = Image.new('RGB', (160, 60), color='#EAEAEA')

        # 创建绘图对象
        draw = ImageDraw.Draw(image)

        font_file = _captcha_font_path()
        font = ImageFont.truetype(str(font_file), size=30) if font_file else ImageFont.load_default()

        # 生成两个0-9之间的随机整数
        num1 = random.randint(0, 9)
        num2 = random.randint(0, 9)
        # 从运算符列表中随机选择一个
        operational_character_list = ['+', '-', '*']
        operational_character = random.choice(operational_character_list)
        # 根据选择的运算符进行计算
        if operational_character == '+':
            result = num1 + num2
        elif operational_character == '-':
            result = num1 - num2
            # 非负数结果的验证码更友好一些
            if result < 0:
                num1, num2 = num2, num1
                result = num1 - num2
        else:
            result = num1 * num2
        # 绘制文本
        text = f'{num1} {operational_character} {num2} = ?'
        draw.text((25, 15), text, fill='blue', font=font)

        # 将图像数据保存到内存中
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')

        # 将图像数据转换为base64字符串
        base64_string = base64.b64encode(buffer.getvalue()).decode()

        return [base64_string, result]
