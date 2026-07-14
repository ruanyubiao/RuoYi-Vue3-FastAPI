from sqlalchemy import BigInteger, Double, String
from sqlalchemy.orm import Mapped, mapped_column

from config.database import Base


class PayloadTmFieldNum(Base):
    """遥测数值字段时序（曲线/导出加速）。"""

    __tablename__ = 'payload_tm_field_num'
    __table_args__ = {'comment': '遥测数值字段时序（曲线/导出）'}

    src_param: Mapped[str] = mapped_column(String(128), primary_key=True, nullable=False, comment='来源参数')
    data_sub: Mapped[str] = mapped_column(String(16), primary_key=True, nullable=False, comment='子类型')
    field_id: Mapped[str] = mapped_column(String(32), primary_key=True, nullable=False, comment='如 JGB001')
    ts_ms: Mapped[int] = mapped_column(BigInteger, primary_key=True, nullable=False)
    value_num: Mapped[float] = mapped_column(Double, nullable=False)
    frame_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment='关联 payload_tm_frame.id')
