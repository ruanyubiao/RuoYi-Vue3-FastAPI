from typing import Any

from module_payload.cfg.payload_config_loader import PayloadConfigLoader


class PayloadConfigService:
    """
    遥控/遥测配置读取服务层。

    仅做配置文件的读取与结构整理，供前端构建指令树、遥测表头与菜单使用；
    不涉及硬件收发（硬件相关见采集进程与设备控制服务）。
    """

    @classmethod
    def get_telecontrol_config(cls, reload: bool = False) -> dict[str, Any]:
        """
        获取遥控配置：分类页(page) + 指令字典(order)。

        :param reload: 是否强制重新加载配置文件
        :return: {datetime, page: [...], order: {...}}
        """
        cfg = PayloadConfigLoader.get_telecontrol_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'page': cfg.get('page', []),
            'order': cfg.get('order', {}),
        }

    @classmethod
    def get_telemetry_pages(cls, reload: bool = False) -> dict[str, Any]:
        """
        获取遥测表列表（用于表切换下拉）。

        由 config 目录扫描 *-TeleMetryCfg.json 的 table 派生；
        同 key 以先扫描到的源为准。响应字段仍为 page，兼容前端。

        :param reload: 是否强制重新加载配置文件
        :return: {datetime, page: [{id, key, name}, ...]}
        """
        cfg = PayloadConfigLoader.get_telemetry_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'page': PayloadConfigLoader.merge_telemetry_pages(reload=reload),
        }

    @classmethod
    def get_telemetry_table_def(cls, table_type: str, reload: bool = False) -> dict[str, Any]:
        """
        获取某遥测表的定义（字段行），用于前端渲染表头/描述与曲线遥测量下拉。

        :param table_type: 遥测数据类型(HEX, 如 FF / D8 / ZK)
        :param reload: 是否强制重新加载配置文件
        :return: 该表定义 {id, name, row: [...]}；不存在返回空字典
        """
        return PayloadConfigLoader.find_telemetry_table(table_type, reload=reload)

    @classmethod
    def get_camera_telecontrol_config(cls, reload: bool = False) -> dict[str, Any]:
        cfg = PayloadConfigLoader.get_camera_telecontrol_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'protocol': cfg.get('protocol', ''),
            'page': cfg.get('page', []),
            'order': cfg.get('order', {}),
        }

    @classmethod
    def get_camera_telemetry_config(cls, reload: bool = False) -> dict[str, Any]:
        cfg = PayloadConfigLoader.get_camera_telemetry_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'protocol': cfg.get('protocol', ''),
            'page': PayloadConfigLoader.tables_to_page_list(cfg),
            'table': cfg.get('table', {}),
        }
