from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module_payload.entity.do.payload_tm_field_num_do import PayloadTmFieldNum


class PayloadTmArchiveDao:
    @classmethod
    async def query_field_points(
        cls,
        db: AsyncSession,
        src_param: str,
        data_sub: str,
        field_id: str,
        start_t: int,
        end_t: int,
        limit: int = 50000,
    ) -> list[tuple[int, float]]:
        stmt = (
            select(PayloadTmFieldNum.ts_ms, PayloadTmFieldNum.value_num)
            .where(
                PayloadTmFieldNum.src_param == src_param,
                PayloadTmFieldNum.data_sub == data_sub.upper(),
                PayloadTmFieldNum.field_id == field_id,
                PayloadTmFieldNum.ts_ms >= start_t,
                PayloadTmFieldNum.ts_ms <= end_t,
            )
            .order_by(PayloadTmFieldNum.ts_ms.asc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        return [(int(ts), float(val)) for ts, val in rows]
