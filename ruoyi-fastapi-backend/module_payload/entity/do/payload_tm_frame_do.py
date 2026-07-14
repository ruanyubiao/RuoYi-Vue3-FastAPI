from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PayloadTmFrame(Base):
    """遥测帧永久归档：原始 HEX + 解析 JSON。"""

    __tablename__ = 'payload_tm_frame'
    __table_args__ = {'comment': '遥测帧永久归档：原始+解析'}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False, comment='帧时间戳(ms)')
    data_kind: Mapped[str] = mapped_column(String(16), nullable=False, comment='数据大类 tm/...')
    data_sub: Mapped[str] = mapped_column(String(16), nullable=False, comment='子类型 FF/FC/...')
    src_kind: Mapped[str] = mapped_column(String(16), nullable=False, comment='来源 can/serial/udp/http')
    src_param: Mapped[str] = mapped_column(String(128), nullable=False, comment='来源参数')
    parser_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='解释器ID')
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False, comment='完整复合帧 HEX')
    parsed_json: Mapped[dict] = mapped_column(JSON, nullable=False, comment='解析结果')
    field_count: Mapped[int] = mapped_column(Integer, nullable=False, comment='字段个数')
    cfg_version: Mapped[str | None] = mapped_column(String(64), nullable=True, comment='配置版本')
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, default=datetime.now, comment='入库时间'
    )
