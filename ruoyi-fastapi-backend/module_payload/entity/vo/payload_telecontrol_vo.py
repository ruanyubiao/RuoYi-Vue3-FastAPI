from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TelecontrolAssembleModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    order_id: str | None = None
    components: list[dict[str, Any]] = Field(default_factory=list)
    values: list[Any] = Field(default_factory=list)


class TelecontrolSendModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    device_id: str
    order_id: str | None = None
    name: str | None = None
    hex: str | None = None
    components: list[dict[str, Any]] | None = None
    values: list[Any] | None = None
    broadcast: bool = False
    append_checksum: bool = False


class ControlOpModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel)

    op: str
    device_id: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
