"""Generate CameraTeleControlCfg.json and CameraTeleMetryCfg.json once."""
import json
from datetime import datetime
from pathlib import Path

out_dir = Path(__file__).resolve().parents[1] / 'assets' / 'config'


def comp(title, ctype, data_type='', unit='', min_v='', max_v='', default='', options=None):
    return {
        'title': title,
        'componentType': ctype,
        'dataType': data_type,
        'unit': unit,
        'minVal': str(min_v) if min_v != '' else '',
        'maxVal': str(max_v) if max_v != '' else '',
        'defaultVal': default,
        'options': options or {},
    }


def order(oid, name, data_len, cmd, components, check='是', frame_type='D0', frame_id='00'):
    return {
        'id': oid,
        'name': name,
        'binfile': 0,
        'timer': 0,
        'check': check,
        'frameType': frame_type,
        'frameId': frame_id,
        'dataLen': data_len,
        'cmd': cmd,
        'component': components,
    }


orders = {}
orders['CAM_A0'] = order('CAM_A0', '遥测开关', 2, 'D7', [
    comp('开关', 'select', 'BYTE', default='0x01', options={'0x00': '关闭', '0x01': '开启'}),
], frame_type='D7')
orders['CAM_A1'] = order('CAM_A1', '恢复默认配置', 2, 'A1', [
    comp('恢复方式', 'select', 'BYTE', default='0x01', options={'0x01': '缺省参数(上电默认)', '0x02': 'Flash参数'}),
])
orders['CAM_A2'] = order('CAM_A2', '自动曝光设置', 3, 'A2', [
    comp('保留', 'fixed', default='0x00'),
    comp('曝光模式', 'select', 'BYTE', default='0x01', options={'0x00': '手动', '0x01': '自动'}),
])
orders['CAM_A3'] = order('CAM_A3', '形心/质心输出选择', 2, 'A3', [
    comp('输出选择', 'select', 'BYTE', default='0x01', options={'0x00': '形心', '0x01': '质心'}),
])
orders['CAM_A4'] = order('CAM_A4', '阈值设置', 6, 'A4', [
    comp('自动阈值开关', 'select', 'BYTE', default='0x01', options={'0x00': '关闭', '0x01': '开启'}),
    comp('高增益阈值', 'number', 'UINT16', min_v=1, max_v=6000, default='600'),
    comp('低增益阈值', 'number', 'UINT16', min_v=1, max_v=6000, default='300'),
])
orders['CAM_A5'] = order('CAM_A5', '疵点剔除设置', 6, 'A5', [
    comp('坏点索引(保留)', 'fixed', default='0x00'),
    comp('坏点X坐标', 'number', 'UINT16', min_v=0, max_v=399, default='0'),
    comp('坏点Y坐标', 'number', 'UINT16', min_v=0, max_v=399, default='0'),
])
orders['CAM_A6'] = order('CAM_A6', '校正参数复位', 2, 'A6', [
    comp('操作', 'select', 'BYTE', default='0x01', options={'0x01': '恢复出厂原始状态'}),
])
orders['CAM_A7'] = order('CAM_A7', '参数保存', 2, 'A7', [
    comp('操作', 'select', 'BYTE', default='0x01', options={'0x01': '开启参数保存'}),
])
orders['CAM_A8'] = order('CAM_A8', '疵点阈值', 5, 'A8', [
    comp('疵点阈值1', 'number', 'UINT16', min_v=1, max_v=6000, default='912'),
    comp('疵点阈值2', 'number', 'UINT16', min_v=1, max_v=6000, default='2666'),
])
orders['CAM_A9'] = order('CAM_A9', '自动校正', 2, 'A9', [
    comp('操作', 'select', 'BYTE', default='0x01', options={'0x01': '开启一次自动校正'}),
])
orders['CAM_A10'] = order('CAM_A10', '拍照', 4, 'AA', [
    comp('操作', 'select', 'BYTE', default='0x01', options={'0x01': '开始缓存'}),
    comp('缓存数量', 'number', 'BYTE', min_v=1, max_v=64, default='1'),
    comp('缓存间隔(帧)', 'number', 'BYTE', min_v=0, max_v=255, default='0'),
])
orders['CAM_A11'] = order('CAM_A11', '温控设定', 4, 'AB', [
    comp('TEC控温模式', 'select', 'BYTE', default='0x01', options={'0x00': '手动', '0x01': '自动'}),
    comp('TEC温控开关', 'select', 'BYTE', default='0x01', options={'0x00': '关闭', '0x01': '开启'}),
    comp('TEC目标温度', 'select', 'BYTE', default='0x02', options={'0x00': '-20℃', '0x01': '0℃', '0x02': '20℃', '0x03': '40℃'}),
])
orders['CAM_A12'] = order('CAM_A12', '数据处理控制', 2, 'AC', [
    comp('控制字节', 'select', 'BYTE', default='0x80', options={
        '0x00': '非均匀性校正关闭，CameraLink关闭',
        '0x02': '非均匀性校正关闭，CameraLink开启',
        '0x80': '非均匀性校正开启，CameraLink关闭（默认）',
        '0x82': '非均匀性校正开启，CameraLink开启',
    }),
])
orders['CAM_A13'] = order('CAM_A13', '开窗指令', 6, 'AD', [
    comp('开窗模式', 'select', 'BYTE', default='0x00', options={
        '0x00': '400×400全窗', '0x01': '256×256', '0x02': '128×128', '0x03': '64×64'
    }),
    comp('起始X', 'number', 'UINT16', min_v=0, max_v=399, default='0'),
    comp('起始Y', 'number', 'UINT16', min_v=0, max_v=399, default='0'),
])
orders['CAM_A14'] = order('CAM_A14', '曝光时间设置', 6, 'AE', [
    comp('保留', 'fixed', default='0x00'),
    comp('曝光时间', 'number', 'UINT32', min_v=1, max_v=100000000, default='1000', unit='us'),
])
orders['CAM_A15'] = order('CAM_A15', '增益设置', 3, 'AF', [
    comp('保留', 'fixed', default='0x00'),
    comp('增益', 'select', 'BYTE', default='0x00', options={'0x00': '低增益', '0x01': '高增益'}),
])
orders['CAM_A16'] = order('CAM_A16', '串口2图传波特率切换', 2, 'B1', [
    comp('波特率', 'select', 'BYTE', default='0x00', options={
        '0x00': '2000000波特率（默认）',
        '0x01': '11000000波特率',
    }),
])
orders['CAM_A17'] = order('CAM_A17', '空间滤波', 2, 'B2', [
    comp('滤波', 'select', 'BYTE', default='0x02', options={
        '0x00': '关闭', '0x01': '模式1', '0x02': '模式2（默认）',
    }),
])
orders['CAM_A18'] = order('CAM_A18', '有效光斑像素阈值', 2, 'B8', [
    comp('阈值', 'number', 'BYTE', min_v=1, max_v=120, default='3'),
])

tc = {
    'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'protocol': 'SC-LINK41EP V1.6',
    'order': orders,
    'page': [{'id': 'CAM', 'name': '相机控制', 'orderList': list(orders.keys())}],
}
(out_dir / 'CameraTeleControlCfg.json').write_text(
    json.dumps(tc, ensure_ascii=False, indent=4) + '\n', encoding='utf-8'
)


def row(no, rid, name, bytepos, bits, data_type, fmt='%d', formula='', unit='', value=None, show_type=0, bitpos=0):
    return {
        'no': no, 'id': rid, 'name': name, 'bytepos': bytepos, 'bits': bits, 'bitpos': bitpos,
        'showType': show_type, 'formula': formula, 'unit': unit, 'fmt': fmt,
        'value': value or {}, 'dataType': data_type, 'variableName': rid,
    }


PART_MAP = {'0000b': '1分区', '0001b': '2分区', '1111b': '加载失败'}
ON_OFF = {'0b': '关闭', '1b': '开启'}
FILTER_MODE = {'0b': '模式2', '1b': '模式1'}
YES_NO = {'0b': '否', '1b': '是'}
SPOT_YN = {'0b': '无光斑', '1b': '有光斑'}

rows_d8 = [
    row(1, 'CAM001', '最后一条指令码', 0, 8, 'BYTE', '%02X'),
    row(2, 'CAM002', '指令执行情况', 1, 8, 'BYTE', '%02X', value={
        '0xAA': '正确', '0xF1': '数据错误', '0xF2': '校验错误', '0xF3': '数据与校验错误',
    }),
    row(3, 'CAM003', '形心/质心', 2, 8, 'BYTE', '%d', value={'0x00': '形心', '0x01': '质心'}),
    row(4, 'CAM004', 'X坐标', 3, 16, 'UINT16'),
    row(5, 'CAM005', 'Y坐标', 5, 16, 'UINT16'),
    row(6, 'CAM006', '过阈值像元数', 7, 8, 'BYTE'),
    row(7, 'CAM007', '饱和像元数', 8, 8, 'BYTE'),
    row(8, 'CAM008', '平均灰度值', 9, 16, 'UINT16'),
    row(9, 'CAM009', '光斑能量', 11, 8, 'INT8'),
    row(10, 'CAM010', 'BOOT软件版本号', 12, 16, 'UINT16', '%04X'),
    row(11, 'CAM011', '模组编号', 14, 16, 'UINT16', '%04X'),
    # TeleMetryParser 终端比特序：bitpos=0 是字节 MSB(=协议 bit7)，不是协议 bit0
    # 协议 [7:4] FPGA → bitpos=0；协议 [3:0] APP → bitpos=4
    row(12, 'CAM012', 'FPGA分区', 16, 4, 'BYTE', '', value=PART_MAP, bitpos=0),
    row(13, 'CAM012A', 'APP分区', 16, 4, 'BYTE', '', value=PART_MAP, bitpos=4),
    row(14, 'CAM013', '曝光时间', 17, 32, 'UINT32', '%u', unit='us'),
    # 协议 bit7→bitpos0 … 协议 bit0→bitpos7
    row(15, 'CAM014', '非均匀性校正', 21, 1, 'BYTE', '', value=ON_OFF, bitpos=0),
    row(16, 'CAM014A', '自动阈值状态', 21, 1, 'BYTE', '', value=ON_OFF, bitpos=1),
    row(17, 'CAM014B', '空间滤波状态', 21, 1, 'BYTE', '', value=ON_OFF, bitpos=2),
    row(18, 'CAM014C', '滤波模式', 21, 1, 'BYTE', '', value=FILTER_MODE, bitpos=3),
    row(19, 'CAM014D', '保留(bit3)', 21, 1, 'BYTE', '%d', bitpos=4),
    row(20, 'CAM014E', '自动曝光状态', 21, 1, 'BYTE', '', value=ON_OFF, bitpos=5),
    row(21, 'CAM014F', 'CameraLink图像传输', 21, 1, 'BYTE', '', value=ON_OFF, bitpos=6),
    row(22, 'CAM014G', '非均匀性校正参数已加载', 21, 1, 'BYTE', '', value=YES_NO, bitpos=7),
    row(23, 'CAM015', '高增益阈值', 22, 16, 'UINT16'),
    row(24, 'CAM016', '低增益阈值', 24, 16, 'UINT16'),
    row(25, 'CAM017', '增益', 26, 8, 'BYTE', value={'0x00': '低增益', '0x01': '高增益'}),
    row(26, 'CAM018', 'TEC温控开关', 27, 8, 'BYTE', value={'0x00': '关闭', '0x01': '开启'}),
    row(27, 'CAM019', 'TEC温控模式', 28, 8, 'BYTE', value={'0x00': '手动', '0x01': '自动'}),
    row(28, 'CAM020', 'TEC目标温度', 29, 8, 'INT8', unit='℃'),
    row(29, 'CAM021', '探测器温度', 30, 16, 'INT16', '%.2f', formula='D*0.01', unit='℃'),
    row(30, 'CAM022', '模组内部温度', 32, 16, 'INT16', '%.2f', formula='D*0.01', unit='℃'),
    row(31, 'CAM023', '疵点阈值1', 34, 16, 'UINT16'),
    row(32, 'CAM024', '疵点阈值2', 36, 16, 'UINT16'),
    row(33, 'CAM025', '开窗起始点X', 38, 16, 'UINT16'),
    row(34, 'CAM026', '开窗起始点Y', 40, 16, 'UINT16'),
    row(35, 'CAM027', '开窗模式', 42, 8, 'BYTE', value={
        '0x00': '400×400', '0x01': '256×256', '0x02': '128×128', '0x03': '64×64',
    }),
    row(36, 'CAM028', '缓存图像个数', 43, 8, 'BYTE'),
    row(37, 'CAM029', '缓存图像大小', 44, 8, 'BYTE', value={
        '0x00': '400×400', '0x01': '256×256', '0x02': '128×128', '0x03': '64×64',
    }),
]

# A.3.2 快遥 D9：数据区 16 字节（帧格式 EB|D9|seq|data16|chk）
XY_FORMULA = 'floor(D/128)+(D%128)/128'
rows_d9 = [
    row(1, 'CAMF001', '最后一条指令码', 0, 8, 'BYTE', '%02X'),
    row(2, 'CAMF002', '指令执行情况', 1, 8, 'BYTE', '%02X', value={
        '0xAA': '正确', '0xF1': '数据错误', '0xF2': '校验错误', '0xF3': '数据与校验错误',
    }),
    row(3, 'CAMF003', '形心/质心', 2, 8, 'BYTE', '%d', value={'0x00': '形心', '0x01': '质心'}),
    row(4, 'CAMF004', 'X坐标', 3, 16, 'UINT16', '%.4f', formula=XY_FORMULA),
    row(5, 'CAMF005', 'Y坐标', 5, 16, 'UINT16', '%.4f', formula=XY_FORMULA),
    row(6, 'CAMF006', '过阈值像元数', 7, 8, 'BYTE'),
    row(7, 'CAMF007', '饱和像元数', 8, 8, 'BYTE'),
    row(8, 'CAMF008', '平均灰度值', 9, 16, 'UINT16'),
    row(9, 'CAMF009', '光斑有无', 11, 1, 'BYTE', '', value=SPOT_YN, bitpos=0),
    row(10, 'CAMF010', '光斑能量', 11, 7, 'BYTE', '%d', formula='-D', unit='dBm', bitpos=1),
    row(11, 'CAMF011', '模组工作状态反馈', 12, 32, 'UINT32', '%08X'),
]

tm = {
    'datetime': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'protocol': 'SC-LINK41EP V1.6',
    'table': {
        'D8': {'id': 'D8', 'name': '慢遥测(全窗)', 'row': rows_d8},
        'D9': {'id': 'D9', 'name': '快遥测(开窗)', 'row': rows_d9},
    },
    'page': [
        {'id': 'D8', 'key': 'D8', 'name': '慢遥测(全窗)'},
        {'id': 'D9', 'key': 'D9', 'name': '快遥测(开窗)'},
    ],
}
(out_dir / 'CameraTeleMetryCfg.json').write_text(
    json.dumps(tm, ensure_ascii=False, indent=4) + '\n', encoding='utf-8'
)
print('wrote', out_dir / 'CameraTeleControlCfg.json', 'orders', len(orders))
print('wrote', out_dir / 'CameraTeleMetryCfg.json', 'D8', len(rows_d8), 'D9', len(rows_d9))
