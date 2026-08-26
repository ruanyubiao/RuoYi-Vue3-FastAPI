"""流水线校验失败文案（模拟页 / Redis error 共用）。"""


def frame_len_mismatch(kind: str, data_len: int, parsed_total: int, actual: int) -> str:
    """帧长与声明不符时的统一提示。"""
    return f'{kind} 帧长不符: 数据长度：{data_len}， 解析总长度：{parsed_total}，实际总长度：{actual}'


def frame_len_over_limit(kind: str, data_len: int, parsed_total: int, limit: int) -> str:
    """声明帧长超过协议上限。"""
    return f'{kind} 帧长不符: 数据长度：{data_len}， 解析总长度：{parsed_total}，上限：{limit}'


def checksum_mismatch(kind: str, calc: int, actual: int, *, width: int = 2) -> str:
    """校验和不匹配；width 控制十六进制位数。"""
    return f'{kind} 校验和错误: 计算：{calc:0{width}X}， 帧内：{actual:0{width}X}'
