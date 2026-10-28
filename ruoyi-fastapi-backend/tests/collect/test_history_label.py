"""遥控历史展示名 + 定时状态最近发送字段。"""

from __future__ import annotations

from module_payload.collectors.history_label import history_display_name


def test_protocol_build_methods_map_to_cn():
    assert history_display_name(
        {'name': 'yj216.protocolBuild', 'protocol_build': {'method': 'build_telemetry_request'}}
    ) == '遥测请求'
    assert history_display_name(
        {'name': 'biu.protocolBuild', 'protocol_build': {'method': 'build_time_sync'}}
    ) == '时间同步'
    assert history_display_name(
        {'name': 'xl.protocolBuild', 'protocol_build': {'method': 'build_telecommand'}}
    ) == '遥控指令'
    assert history_display_name(
        {'name': 'xl.protocolBuild', 'protocol_build': {'method': 'build_broadcast'}}
    ) == '广播'
    assert history_display_name(
        {'name': 'biu.protocolBuild', 'protocol_build': {'method': 'build_system'}}
    ) == '系统指令'


def test_op_names_map_across_families():
    assert history_display_name({'name': 'yj216.timedTm.enable'}) == '定时遥测'
    assert history_display_name({'name': 'biu.timeSync.broadcast'}) == '定时同步广播'
    assert history_display_name({'name': 'xl.tm.request'}) == '遥测请求'
    assert history_display_name({'name': 'biu.timeSync.setPayload'}) == '时间同步'


def test_human_order_name_kept():
    assert history_display_name({'name': '开关机指令'}) == '开关机指令'
    assert history_display_name({'name': 'B1 实时遥测'}) == 'B1 实时遥测'


def test_empty_cmd():
    assert history_display_name({}) == ''
    assert history_display_name(None) == ''
