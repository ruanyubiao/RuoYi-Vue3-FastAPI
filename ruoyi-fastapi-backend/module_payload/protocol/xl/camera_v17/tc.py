"""XL 相机 V1.7 遥控。帧格式与 v16 相同，配置是 ``xl-camera-v17-tc``。"""

from module_payload.protocol.hooks import ProtocolBindings
from module_payload.protocol.xl.camera.tc import assemble

__all__ = ['assemble', 'assemble_by_id']


def assemble_by_id(
    order_id: str,
    values: list | None = None,
    *,
    seq: int = 0,
    reload: bool = False,
) -> dict:
    """按指令 id 组 V1.7 相机遥控帧。"""
    from module_payload.cfg.telecontrol_cfg import TeleControlCfgManager, board_cfg_id

    return TeleControlCfgManager.get(board_cfg_id('xl', 'camera-v17'), reload=reload).assemble(
        order_id, values, seq=seq
    )


BINDINGS = ProtocolBindings(assemble=assemble)
