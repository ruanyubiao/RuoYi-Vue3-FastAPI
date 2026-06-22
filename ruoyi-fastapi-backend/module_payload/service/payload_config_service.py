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
        获取遥测页列表（用于二级菜单与表切换下拉）。

        :param reload: 是否强制重新加载配置文件
        :return: {datetime, page: [{id, key, name}, ...]}
        """
        cfg = PayloadConfigLoader.get_telemetry_cfg(reload=reload)
        return {
            'datetime': cfg.get('datetime', ''),
            'page': cfg.get('page', []),
        }

    @classmethod
    def get_telemetry_table_def(cls, table_type: str, reload: bool = False) -> dict[str, Any]:
        """
        获取某遥测表的定义（字段行），用于前端渲染表头/描述与曲线遥测量下拉。

        :param table_type: 遥测数据类型(HEX, 如 FF)
        :param reload: 是否强制重新加载配置文件
        :return: 该表定义 {id, name, row: [...]}；不存在返回空字典
        """
        cfg = PayloadConfigLoader.get_telemetry_cfg(reload=reload)
        table = cfg.get('table', {})
        key = (table_type or '').upper()
        return table.get(key, {})
