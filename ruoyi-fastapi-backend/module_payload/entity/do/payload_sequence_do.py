from datetime import datetime

from sqlalchemy import CHAR, BigInteger, Column, DateTime, String, Text

from config.database import Base


class PayloadCmdSequence(Base):
    """
    指令序列表
    """

    __tablename__ = 'payload_cmd_sequence'
    __table_args__ = {'comment': '指令序列表'}

    seq_id = Column(BigInteger, primary_key=True, nullable=False, autoincrement=True, comment='指令序列ID')
    seq_name = Column(String(100), nullable=False, comment='序列名称')
    commands = Column(Text, nullable=True, server_default="'[]'", comment='指令内容(JSON对象数组)')
    status = Column(CHAR(1), nullable=True, server_default='0', comment='状态(0正常 1停用)')
    create_by = Column(String(64), nullable=True, server_default="''", comment='创建者')
    create_time = Column(DateTime, nullable=True, default=datetime.now, comment='创建时间')
    update_by = Column(String(64), nullable=True, server_default="''", comment='更新者')
    update_time = Column(DateTime, nullable=True, default=datetime.now, comment='更新时间')
    remark = Column(String(500), nullable=True, server_default="''", comment='备注')
