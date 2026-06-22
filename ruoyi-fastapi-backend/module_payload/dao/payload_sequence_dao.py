from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import PageModel
from module_payload.entity.do.payload_sequence_do import PayloadCmdSequence
from module_payload.entity.vo.payload_sequence_vo import PayloadSequenceModel, PayloadSequencePageQueryModel
from utils.page_util import PageUtil


class PayloadSequenceDao:
    """
    指令序列管理数据库操作层
    """

    @classmethod
    async def get_sequence_detail_by_id(cls, db: AsyncSession, seq_id: int) -> PayloadCmdSequence | None:
        """
        根据指令序列id获取详细信息

        :param db: orm对象
        :param seq_id: 指令序列id
        :return: 指令序列信息对象
        """
        sequence_info = (
            (await db.execute(select(PayloadCmdSequence).where(PayloadCmdSequence.seq_id == seq_id))).scalars().first()
        )

        return sequence_info

    @classmethod
    async def get_sequence_list(
        cls, db: AsyncSession, query_object: PayloadSequencePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """
        根据查询参数获取指令序列列表信息

        :param db: orm对象
        :param query_object: 查询参数对象
        :param is_page: 是否开启分页
        :return: 指令序列列表信息对象
        """
        query = (
            select(PayloadCmdSequence)
            .where(
                PayloadCmdSequence.seq_name.like(f'%{query_object.seq_name}%') if query_object.seq_name else True,
                PayloadCmdSequence.status == query_object.status if query_object.status else True,
            )
            .order_by(PayloadCmdSequence.seq_id.desc())
        )
        sequence_list: PageModel | list[dict[str, Any]] = await PageUtil.paginate(
            db, query, query_object.page_num, query_object.page_size, is_page
        )

        return sequence_list

    @classmethod
    async def add_sequence_dao(cls, db: AsyncSession, sequence: PayloadSequenceModel) -> PayloadCmdSequence:
        """
        新增指令序列数据库操作

        :param db: orm对象
        :param sequence: 指令序列对象
        :return: 指令序列信息对象
        """
        db_sequence = PayloadCmdSequence(**sequence.model_dump(exclude_unset=True, exclude={'seq_id'}))
        db.add(db_sequence)
        await db.flush()

        return db_sequence

    @classmethod
    async def edit_sequence_dao(cls, db: AsyncSession, sequence: dict) -> None:
        """
        编辑指令序列数据库操作

        :param db: orm对象
        :param sequence: 需要更新的指令序列字典
        :return:
        """
        await db.execute(update(PayloadCmdSequence), [sequence])

    @classmethod
    async def delete_sequence_dao(cls, db: AsyncSession, sequence: PayloadSequenceModel) -> None:
        """
        删除指令序列数据库操作

        :param db: orm对象
        :param sequence: 指令序列对象
        :return:
        """
        await db.execute(delete(PayloadCmdSequence).where(PayloadCmdSequence.seq_id.in_([sequence.seq_id])))
