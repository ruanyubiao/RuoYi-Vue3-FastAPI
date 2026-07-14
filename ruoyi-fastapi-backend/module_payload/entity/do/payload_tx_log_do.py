from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PayloadTxLog(Base):
    """遥控/指令发送记录（按月 RANGE 分区）。"""

    __tablename__ = 'payload_tx_log'
    __table_args__ = {'comment': '遥控发送记录'}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_ms: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    src_kind: Mapped[str] = mapped_column(String(16), nullable=False, comment='发送通道类型')
    src_param: Mapped[str] = mapped_column(String(128), nullable=False, comment='发送通道参数')
    cmd_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_hex: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True, default=datetime.now
    )
