from typing import Any

from module_payload.cfg.payload_config_loader import PayloadConfigLoader


class PayloadConfigService:
    """
    遥控/遥测配置读取服务层。

    仅做配置文件的读取与结构整理，供前端构建指令树、遥测表头与菜单使用；
    不涉及硬件收发（硬件相关见采集进程与设备控制服务）。
    """

    @classmethod
    def get_telecontrol_config(cls, reload: bool = False, family: str | None = 'biu') -> dict[str, Any]:
        """
        获取遥控配置：分类页(page) + 指令字典(order)。

        :param reload: 是否强制重新加载配置文件
        :param family: biu | xl
        :return: {datetime, page: [...], order: {...}, family}
        """
        fam = PayloadConfigLoader.normalize_family(family)
        cfg = PayloadConfigLoader.get_telecontrol_cfg(fam, reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'page': cfg.get('page', []),
            'order': cfg.get('order', {}),
            'family': fam,
        }

    @classmethod
    def get_telemetry_pages(cls, reload: bool = False, family: str | None = None) -> dict[str, Any]:
        """
        获取遥测表列表（曲线/归档下拉）。

        XL 组含总线 + 单板(RKDJ/ZK) + 相机；BIU 组为总线。可按 family 过滤。

        :return: {datetime, page: [{id, key, localKey, name, family, source?}, ...], family?}
        """
        fam = PayloadConfigLoader.normalize_family(family) if family else None
        cfg = PayloadConfigLoader.get_telemetry_cfg(fam or 'biu', reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'page': PayloadConfigLoader.merge_telemetry_pages(reload=reload, family=family),
            'family': fam,
        }

    @classmethod
    def get_telemetry_table_def(
        cls, table_type: str, reload: bool = False, family: str | None = None
    ) -> dict[str, Any]:
        """
        获取某遥测表的定义（字段行），用于前端渲染表头/描述与曲线遥测量下拉。

        :param table_type: 遥测数据类型(HEX, 如 FF / D8 / ZK)
        :param reload: 是否强制重新加载配置文件
        :param family: 可选 biu | xl（同 key 时区分配置源）
        :return: 该表定义 {id, name, row: [...]}；不存在返回空字典
        """
        return PayloadConfigLoader.find_telemetry_table(table_type, reload=reload, family=family)

    @classmethod
    def get_camera_telecontrol_config(cls, reload: bool = False) -> dict[str, Any]:
        """获取相机遥控配置：protocol + page + order。"""
        cfg = PayloadConfigLoader.get_camera_telecontrol_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'protocol': cfg.get('protocol', ''),
            'page': cfg.get('page', []),
            'order': cfg.get('order', {}),
        }

    @classmethod
    def get_camera_telemetry_config(cls, reload: bool = False) -> dict[str, Any]:
        """获取相机遥测配置：table 派生 page 列表。"""
        cfg = PayloadConfigLoader.get_camera_telemetry_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'protocol': cfg.get('protocol', ''),
            'page': PayloadConfigLoader.tables_to_page_list(cfg, family='xl'),
            'table': cfg.get('table', {}),
        }

    @classmethod
    def get_xl_board_telecontrol_config(cls, board: str, reload: bool = False) -> dict[str, Any]:
        """获取 XL 单板遥控配置，并附带 board / tableKey。"""
        cfg = PayloadConfigLoader.get_xl_board_telecontrol_cfg(board, reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'protocol': cfg.get('protocol', ''),
            'page': cfg.get('page', []),
            'order': cfg.get('order', {}),
            'board': PayloadConfigLoader.normalize_xl_board(board),
            'tableKey': PayloadConfigLoader.xl_board_tm_table_key(board),
        }

    @classmethod
    def get_xl_board_telemetry_config(cls, board: str, reload: bool = False) -> dict[str, Any]:
        """获取 XL 单板遥测配置，并附带 board / tableKey。"""
        cfg = PayloadConfigLoader.get_xl_board_telemetry_cfg(board, reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'protocol': cfg.get('protocol', ''),
            'page': PayloadConfigLoader.tables_to_page_list(cfg, family='xl'),
            'table': cfg.get('table', {}),
            'board': PayloadConfigLoader.normalize_xl_board(board),
            'tableKey': PayloadConfigLoader.xl_board_tm_table_key(board),
        }
