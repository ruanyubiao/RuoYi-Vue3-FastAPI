from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class TelemetryTableQueryModel(BaseModel):
    """遥测表查询：表类型。"""

    model_config = ConfigDict(alias_generator=to_camel)

    type: str


class TelemetryTableBatchItemModel(BaseModel):
    """批量遥测表：单项参数与单次 GET /table 一致。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: str
    # Redis/前端可能回传数字 dataId；与 GET query 字符串对齐，入库前统一成 str
    data_id: str | int | None = Field(default=None, alias='dataId')
    need_cfg: bool = Field(default=False, alias='needCfg')
    # live=实时 Redis；db=历史库；file=历史文件。非 live 不读 payload:tm 热层
    source: str = Field(default='live')

    def data_id_str(self) -> str | None:
        """把 dataId 统一成 str；空则 None。"""
        if self.data_id is None or self.data_id == '':
            return None
        return str(self.data_id)


class TelemetryTableBatchModel(BaseModel):
    """批量遥测表请求体。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    items: list[TelemetryTableBatchItemModel] = Field(default_factory=list)


class CurveDataQueryModel(BaseModel):
    """单条实时曲线查询。"""

    model_config = ConfigDict(alias_generator=to_camel)

    type: str
    field: str
    limit: int = 600


class CurveBatchItemModel(BaseModel):
    """批量实时曲线：单项（type/field/limit/sinceT）。"""

    model_config = ConfigDict(alias_generator=to_camel)

    type: str
    field: str
    limit: int = 500
    since_t: float | None = None


class CurveBatchQueryModel(BaseModel):
    """批量实时曲线请求体。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    items: list[CurveBatchItemModel]
    # 1=顺带读该表接收帧率；默认不读，避免曲线轮询多打 latest 热层
    fps: int | bool = 0

    def want_fps(self) -> bool:
        """请求 fps=1 / true 时才读帧率键。"""
        v = self.fps
        if v is True:
            return True
        try:
            return int(v) == 1
        except (TypeError, ValueError):
            return False


class HistoryCurveBatchItemModel(BaseModel):
    """批量归档曲线：单项时间范围。"""

    model_config = ConfigDict(alias_generator=to_camel)

    type: str
    field: str
    start_t: int = Field(description='起始时间戳(ms)')
    end_t: int = Field(description='结束时间戳(ms)')
    limit: int = 50000


class HistoryCurveBatchQueryModel(BaseModel):
    """批量归档曲线请求体。"""

    model_config = ConfigDict(alias_generator=to_camel)

    items: list[HistoryCurveBatchItemModel]


class CanYcInjectModel(BaseModel):
    """开发测试：注入已组帧的 CAN 遥测复合帧 HEX。"""

    model_config = ConfigDict(alias_generator=to_camel)

    hex: str = Field(description='完整 CAN 遥测复合帧 HEX（空格可选）')


class PipelineInjectModel(BaseModel):
    """通用数据发送模拟：HEX → 组装器 → 解析器。"""

    model_config = ConfigDict(alias_generator=to_camel)

    hex: str = Field(description='原始 HEX 文本（空格可选）；可为粘包多帧')
    assembler_id: str = Field(default='passthrough', description='组装器 ID')
    parser_id: str = Field(description='解析器 ID，如 tm_can_biu')


class TmCalcModel(BaseModel):
    """调试：单字段 Hex 解析计算。"""

    model_config = ConfigDict(alias_generator=to_camel)

    type: str = Field(description='遥测表 key，如 FF / RKDJ')
    field: str = Field(description='遥测量 id，如 JGB001')
    hex: str = Field(description='字段 Hex 文本（空格可选）')
    pad_tail: bool = Field(
        default=True,
        description='字节不足时：True 后面补 00，False 前面补 00',
    )


class FileParseModel(BaseModel):
    """历史文件：开始解析。type 为遥测表存储键（如 BIU:FF），path 为白名单内绝对/相对路径。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: str = Field(description='遥测表 key，如 BIU:FF / XL:D8')
    path: str = Field(description='文件路径，须在 upload_logs_data_raw 或 logs_data/raw 下')
    channel: str = Field(default='history', description='history=历史文件数据，curve=历史文件曲线')
    force: int | bool = Field(default=0, description='1=确认重新解析；仅弹窗确认后携带')


class FileSessionOpModel(BaseModel):
    """历史文件解析会话：关进程或清缓存。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    path_hash: str = Field(description='文件 pathHash')
    channel: str = Field(default='history', description='history=历史文件数据，curve=历史文件曲线')


class FileCurveItemModel(BaseModel):
    """历史文件曲线单项。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    field: str = Field(description='遥测量 id')
    type: str = Field(default='', description='遥测表 key，可空则用会话 meta.type')
    have_chunks: list[int] = Field(default_factory=list, description='客户端已有的块序号，服务端不再下发内容')


class FileCurveQueryModel(BaseModel):
    """历史文件曲线查询。start/end 为万点块半开区间 [start, end)。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    path: str = Field(default='', description='忽略：曲线查询只用 pathHash')
    path_hash: str = Field(default='', description='parse 返回的 pathHash')
    channel: str = Field(default='curve', description='固定走曲线频道，避免冲掉历史文件数据')
    items: list[FileCurveItemModel] = Field(default_factory=list, description='要上图的字段')
    start_index: int | None = Field(default=None, description='起始块序号（含），默认 0')
    end_index: int | None = Field(default=None, description='结束块序号（不含）')
    chunks: list[int] | None = Field(default=None, description='显式块序号列表，优先于 start/end')
    have_chunks: list[int] = Field(default_factory=list, description='已有块（各项未单独声明时的默认）')
    start_t: int | None = Field(default=None, description='预留：按时间窗，当前未用')
    end_t: int | None = Field(default=None, description='预留：按时间窗，当前未用')


class HistoryFramesOpenModel(BaseModel):
    """历史 CAN 表回放开会话。时间可毫秒戳或 ``YYYY-MM-DD HH:mm:ss``。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    type: str = Field(description='遥测表 key，如 BIU:FF')
    start: str | int = Field(description='起始时间')
    end: str | int = Field(description='结束时间')

