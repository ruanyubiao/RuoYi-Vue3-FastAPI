"""MySQL 遥测归档表按月分区维护（SQLite/PostgreSQL 跳过）。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config.env import DataBaseConfig
from utils.log_util import logger

PARTITIONED_TABLES = ('payload_tm_frame', 'payload_tx_log')


def _month_start_ms(year: int, month: int) -> int:
    """该月 1 日 00:00 UTC 的毫秒时间戳，用作 RANGE 上界。"""
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _partition_name(year: int, month: int) -> str:
    """分区名 pYYYYMM。"""
    return f'p{year}{month:02d}'


def _next_month(year: int, month: int) -> tuple[int, int]:
    """返回下一个自然月的 (年, 月)。"""
    if month == 12:
        return year + 1, 1
    return year, month + 1


async def _table_is_partitioned(db: AsyncSession, table_name: str) -> bool:
    """当前库中该表是否已有命名分区。"""
    result = await db.execute(
        text(
            """
            SELECT COUNT(*) FROM information_schema.PARTITIONS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND PARTITION_NAME IS NOT NULL
            """
        ),
        {'table_name': table_name},
    )
    return int(result.scalar() or 0) > 0


async def _existing_partitions(db: AsyncSession, table_name: str) -> dict[str, int | None]:
    """已有分区名 → 上界毫秒；MAXVALUE 记为 None。"""
    result = await db.execute(
        text(
            """
            SELECT PARTITION_NAME, PARTITION_DESCRIPTION
            FROM information_schema.PARTITIONS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :table_name
              AND PARTITION_NAME IS NOT NULL
            ORDER BY PARTITION_ORDINAL_POSITION
            """
        ),
        {'table_name': table_name},
    )
    out: dict[str, int | None] = {}
    for name, desc in result.all():
        if not name:
            continue
        if str(desc).upper() == 'MAXVALUE':
            out[name] = None
        else:
            try:
                out[name] = int(str(desc).strip("'"))
            except ValueError:
                out[name] = None
    return out


async def ensure_month_partitions(db: AsyncSession, months_ahead: int = 2) -> list[str]:
    """
    为已启用 RANGE 分区的归档表创建未来月份分区。
    通过 REORGANIZE PARTITION pmax 拆分出新月分区。
    """
    if DataBaseConfig.db_type != 'mysql':
        return []

    actions: list[str] = []
    now = datetime.now()
    year, month = now.year, now.month

    # 本月起向后 months_ahead 个月，上界为次月 1 日
    targets: list[tuple[int, int, int]] = []
    y, m = year, month
    for _ in range(months_ahead + 1):
        ny, nm = _next_month(y, m)
        targets.append((y, m, _month_start_ms(ny, nm)))
        y, m = ny, nm

    for table_name in PARTITIONED_TABLES:
        if not await _table_is_partitioned(db, table_name):
            continue
        existing = await _existing_partitions(db, table_name)
        if 'pmax' not in existing:
            continue
        for y, m, boundary_ms in targets:
            pname = _partition_name(y, m)
            if pname in existing:
                continue
            # 从 pmax 拆出新月分区，尾部分区仍接 MAXVALUE
            sql = (
                f'ALTER TABLE {table_name} REORGANIZE PARTITION pmax INTO ('
                f"PARTITION {pname} VALUES LESS THAN ({boundary_ms}), "
                f'PARTITION pmax VALUES LESS THAN MAXVALUE)'
            )
            await db.execute(text(sql))
            await db.commit()
            actions.append(f'{table_name}:{pname}')
            logger.info('已创建分区 %s boundary<%s', f'{table_name}.{pname}', boundary_ms)

    return actions


async def run_partition_maintenance() -> None:
    """定时任务入口：为归档表补未来月份分区。"""
    from config.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            actions = await ensure_month_partitions(db)
            if actions:
                logger.info('遥测分区维护完成: %s', ', '.join(actions))
        except Exception:
            await db.rollback()
            logger.exception('遥测分区维护失败')
