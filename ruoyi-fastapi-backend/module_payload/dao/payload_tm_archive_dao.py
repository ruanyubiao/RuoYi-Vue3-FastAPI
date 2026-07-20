from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module_payload.entity.do.payload_tm_field_num_do import PayloadTmFieldNum


class PayloadTmArchiveDao:
    @classmethod
    async def query_field_points(
        cls,
        db: AsyncSession,
        data_sub: str,
        field_id: str,
        start_t: int,
        end_t: int,
        limit: int = 50000,
        src_param: str | None = None,
    ) -> list[tuple[int, float]]:
        """按 data_sub+field 查历史点；src_param 为空时不按来源过滤（跨通道合并）。"""
        conditions = [
            PayloadTmFieldNum.data_sub == data_sub.upper(),
            PayloadTmFieldNum.field_id == field_id,
            PayloadTmFieldNum.ts_ms >= start_t,
            PayloadTmFieldNum.ts_ms <= end_t,
        ]
        if src_param:
            conditions.append(PayloadTmFieldNum.src_param == src_param)
        stmt = (
            select(PayloadTmFieldNum.ts_ms, PayloadTmFieldNum.value_num)
            .where(*conditions)
            .order_by(PayloadTmFieldNum.ts_ms.asc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [(int(ts), float(val)) for ts, val in rows]
