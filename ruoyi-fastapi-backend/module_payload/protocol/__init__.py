"""帧协议：收包拼帧、遥测校验与解释、遥控组帧。

每条总线族一个子包（``biu`` / ``xl`` / ``yj216``），子包之间互不 import。
总线族、插件与遥控配置登记在 ``protocol_catalog``；框架只经 ``protocol.registry`` 按其中的模块路径查找各协议的 ``BINDINGS``。
"""
