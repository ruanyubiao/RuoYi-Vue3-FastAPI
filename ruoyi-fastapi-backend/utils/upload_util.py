import os
import random
from collections.abc import AsyncGenerator
from datetime import datetime

import aiofiles
from fastapi import UploadFile

from config.env import UploadConfig


class UploadUtil:
    """
    上传工具类
    """

    @classmethod
    def generate_random_number(cls) -> str:
        """
        生成3位数字构成的字符串

        :return: 3位数字构成的字符串
        """
        random_number = random.randint(1, 999)

        return f'{random_number:03}'

    @classmethod
    def check_file_exists(cls, filepath: str) -> bool:
        """
        检查文件是否存在

        :param filepath: 文件路径
        :return: 校验结果
        """
        return os.path.exists(filepath)

    @classmethod
    def check_file_extension(cls, file: UploadFile) -> bool:
        """
        检查文件后缀是否合法

        :param file: 文件对象
        :return: 校验结果
        """
        if not file.filename:
            # 没有文件名（部分客户端）时原逻辑会抛 AttributeError → 500；按非法后缀处理
            return False
        file_extension = file.filename.rsplit('.', 1)[-1]

        if file_extension in UploadConfig.DEFAULT_ALLOWED_EXTENSION:
            return True
        # 兼容：Windows 文件名大小写不敏感，'A.PNG' / 'b.Jpg' 也视为合法后缀
        return file_extension.lower() in UploadConfig.DEFAULT_ALLOWED_EXTENSION

    @classmethod
    def check_file_timestamp(cls, filename: str) -> bool:
        """
        校验文件时间戳是否合法

        :param filename: 文件名称
        :return: 校验结果
        """
        timestamp = (
            filename.rsplit('.', 1)[0].rsplit('_', maxsplit=1)[-1].split(UploadConfig.UPLOAD_MACHINE, maxsplit=1)[0]
        )
        try:
            datetime.strptime(timestamp, '%Y%m%d%H%M%S')
            return True
        except ValueError:
            return False

    @classmethod
    def check_file_machine(cls, filename: str) -> bool:
        """
        校验文件机器码是否合法

        :param filename: 文件名称
        :return: 校验结果
        """
        stem = filename.rsplit('.', 1)[0]
        if len(stem) < 4:
            # 过短的文件名原逻辑会 IndexError → 500；按不合法处理
            return False
        return filename.rsplit('.', 1)[0][-4] == UploadConfig.UPLOAD_MACHINE

    @classmethod
    def check_file_random_code(cls, filename: str) -> bool:
        """
        校验文件随机码是否合法

        :param filename: 文件名称
        :return: 校验结果
        """
        valid_code_list = [f'{i:03}' for i in range(1, 999)]
        # generate_random_number 使用 randint(1, 999)，可能生成 '999'；原列表漏掉了它，约 0.1% 的上传文件无法下载
        valid_code_list.append('999')

        return filename.rsplit('.', 1)[0][-3:] in valid_code_list

    @classmethod
    async def generate_file(cls, filepath: str) -> AsyncGenerator[bytes, None]:
        """
        根据文件生成二进制数据

        :param filepath: 文件路径
        :yield: 二进制数据
        """
        async with aiofiles.open(filepath, 'rb') as response_file:
            async for chunk in response_file:
                yield chunk

    @classmethod
    def delete_file(cls, filepath: str) -> None:
        """
        根据文件路径删除对应文件

        :param filepath: 文件路径
        """
        os.remove(filepath)
