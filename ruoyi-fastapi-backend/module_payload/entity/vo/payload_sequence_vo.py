from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_validation_decorator import NotBlank, Size


class PayloadSequenceModel(BaseModel):
    """
    指令序列表对应pydantic模型

    commands 字段为 JSON 文本，结构为对象数组，单项形如：
    {"name": "K1502 驱动使能", "hex": "0A 91 00 04 00 04 AA AA", "interval": 2000}
    其中 interval 为发送该帧后到下一帧的间隔(毫秒，默认2000)。
    """

    model_config = ConfigDict(alias_generator=to_camel, from_attributes=True)

    seq_id: int | None = Field(default=None, description='指令序列ID')
    seq_name: str | None = Field(default=None, description='序列名称')
    commands: str | None = Field(default=None, description='指令内容(JSON对象数组文本)')
    status: Literal['0', '1'] | None = Field(default=None, description='状态(0正常 1停用)')
    create_by: str | None = Field(default=None, description='创建者')
    create_time: datetime | None = Field(default=None, description='创建时间')
    update_by: str | None = Field(default=None, description='更新者')
    update_time: datetime | None = Field(default=None, description='更新时间')
    remark: str | None = Field(default=None, description='备注')

    @NotBlank(field_name='seq_name', message='序列名称不能为空')
    @Size(field_name='seq_name', min_length=0, max_length=100, message='序列名称长度不能超过100个字符')
    def get_seq_name(self) -> str | None:
        return self.seq_name


class PayloadSequencePageQueryModel(PayloadSequenceModel):
    """指令序列管理分页查询模型"""

    page_num: int = Field(default=1, description='当前页码')
    page_size: int = Field(default=10, description='每页记录数')


class DeletePayloadSequenceModel(BaseModel):
    """删除指令序列模型"""

    model_config = ConfigDict(alias_generator=to_camel)

    seq_ids: str = Field(description='需要删除的指令序列ID')


class SequenceRunModel(BaseModel):
    """执行指令序列入参"""

    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str = Field(description='目标设备ID')
