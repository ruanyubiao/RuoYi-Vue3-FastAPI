"""兼容入口：实现已迁到 ``module_payload.store.error_store``。"""

from module_payload.store.error_store import normalize_error_type, push_pipeline_error

__all__ = ['normalize_error_type', 'push_pipeline_error']
