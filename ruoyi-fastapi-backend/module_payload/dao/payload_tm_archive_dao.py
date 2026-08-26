from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module_payload.entity.do.payload_tm_frame_do import PayloadTmFrame


class PayloadTmArchiveDao:
    """遥测历史帧 MySQL 查询（曲线归档）。"""

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
        """从 payload_tm_frame.points_json 抽取指定字段历史点。"""
        conditions = [
            PayloadTmFrame.data_sub == data_sub.upper(),
            PayloadTmFrame.ts_ms >= start_t,
            PayloadTmFrame.ts_ms <= end_t,
        ]
        if src_param:
            conditions.append(PayloadTmFrame.src_param == src_param)
        stmt = (
            select(PayloadTmFrame.ts_ms, PayloadTmFrame.points_json)
            .where(*conditions)
            .order_by(PayloadTmFrame.ts_ms.asc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()
        out: list[tuple[int, float]] = []
        fid = str(field_id)
        for ts, points in rows:
            if not isinstance(points, dict):
                continue
            val = points.get(fid)
            if val is None:
                continue
            try:
                out.append((int(ts), float(val)))
            except (TypeError, ValueError):
                continue
        return out
