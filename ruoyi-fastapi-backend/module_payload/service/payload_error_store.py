"""兼容旧路径：错误写入在 store.error_store。"""

from module_payload.store.error_store import push_pipeline_error

__all__ = ['push_pipeline_error']
