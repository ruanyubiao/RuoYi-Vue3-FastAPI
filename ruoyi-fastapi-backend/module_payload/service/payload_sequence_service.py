from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from common.vo import CrudResponseModel, PageModel
from exceptions.exception import ServiceException
from module_payload.dao.payload_sequence_dao import PayloadSequenceDao
from module_payload.entity.vo.payload_sequence_vo import (
    DeletePayloadSequenceModel,
    PayloadSequenceModel,
    PayloadSequencePageQueryModel,
)
from utils.common_util import CamelCaseUtil


class PayloadSequenceService:
    """
    指令序列管理服务层
    """

    @classmethod
    async def get_sequence_list_services(
        cls, query_db: AsyncSession, query_object: PayloadSequencePageQueryModel, is_page: bool = False
    ) -> PageModel | list[dict[str, Any]]:
        """
        获取指令序列列表信息service

        :param query_db: orm对象
        :param query_object: 查询参数对象
        :param is_page: 是否开启分页
        :return: 指令序列列表信息对象
        """
        sequence_list_result = await PayloadSequenceDao.get_sequence_list(query_db, query_object, is_page)

        return sequence_list_result

    @classmethod
    async def add_sequence_services(
        cls, query_db: AsyncSession, page_object: PayloadSequenceModel
    ) -> CrudResponseModel:
        """
        新增指令序列信息service

        :param query_db: orm对象
        :param page_object: 新增指令序列对象
        :return: 新增指令序列校验结果
        """
        try:
            await PayloadSequenceDao.add_sequence_dao(query_db, page_object)
            await query_db.commit()
            return CrudResponseModel(is_success=True, message='新增成功')
        except Exception as e:
            await query_db.rollback()
            raise e

    @classmethod
    async def edit_sequence_services(
        cls, query_db: AsyncSession, page_object: PayloadSequenceModel
    ) -> CrudResponseModel:
        """
        编辑指令序列信息service

        :param query_db: orm对象
        :param page_object: 编辑指令序列对象
        :return: 编辑指令序列校验结果
        """
        edit_sequence = page_object.model_dump(exclude_unset=True)
        sequence_info = await cls.sequence_detail_services(query_db, page_object.seq_id)
        if sequence_info.seq_id:
            try:
                await PayloadSequenceDao.edit_sequence_dao(query_db, edit_sequence)
                await query_db.commit()
                return CrudResponseModel(is_success=True, message='修改成功')
            except Exception as e:
                await query_db.rollback()
                raise e
        else:
            raise ServiceException(message='指令序列不存在')

    @classmethod
    async def delete_sequence_services(
        cls, query_db: AsyncSession, page_object: DeletePayloadSequenceModel
    ) -> CrudResponseModel:
        """
        删除指令序列信息service

        :param query_db: orm对象
        :param page_object: 删除指令序列对象
        :return: 删除指令序列校验结果
        """
        if page_object.seq_ids:
            seq_id_list = page_object.seq_ids.split(',')
            try:
                for seq_id in seq_id_list:
                    await PayloadSequenceDao.delete_sequence_dao(query_db, PayloadSequenceModel(seqId=seq_id))
                await query_db.commit()
                return CrudResponseModel(is_success=True, message='删除成功')
            except Exception as e:
                await query_db.rollback()
                raise e
        else:
            raise ServiceException(message='传入指令序列id为空')

    @classmethod
    async def sequence_detail_services(cls, query_db: AsyncSession, seq_id: int) -> PayloadSequenceModel:
        """
        获取指令序列详细信息service

        :param query_db: orm对象
        :param seq_id: 指令序列id
        :return: 指令序列id对应的信息
        """
        sequence = await PayloadSequenceDao.get_sequence_detail_by_id(query_db, seq_id=seq_id)
        result = (
            PayloadSequenceModel(**CamelCaseUtil.transform_result(sequence)) if sequence else PayloadSequenceModel()
        )

        return result
