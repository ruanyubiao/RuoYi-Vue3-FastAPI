"""遥测归档表按月分区维护定时任务（仅 MySQL 且表已启用分区时生效）。"""

from module_payload.service.payload_tm_partition_service import run_partition_maintenance


async def job(*args, **kwargs) -> None:
    await run_partition_maintenance()
