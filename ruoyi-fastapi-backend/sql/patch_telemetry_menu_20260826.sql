-- 遥测菜单重组：实时数据/曲线、历史 CAN、历史文件。可重复执行。
-- 本地：mysql -u root -p123456 < sql/patch_telemetry_menu_20260826.sql
-- 库名按现网（执行前 USE 目标库，或 mysql ... 库名 < 本文件）

UPDATE sys_menu
SET menu_name = '实时数据',
    path = 'live',
    order_num = 1,
    component = 'payload/telemetry/table/index',
    perms = 'payload:telemetry:view',
    remark = '实时遥测表（全量表）'
WHERE menu_id = 2110;

DELETE FROM sys_role_menu WHERE menu_id = 2111;
DELETE FROM sys_menu WHERE menu_id = 2111;

UPDATE sys_menu
SET menu_name = '实时曲线',
    path = 'curve',
    order_num = 2,
    component = 'payload/telemetry/curve/index',
    remark = '实时遥测曲线页'
WHERE menu_id = 2108;

UPDATE sys_menu
SET menu_name = '历史CAN曲线',
    path = 'archive',
    order_num = 4,
    component = 'payload/telemetry/archive/index',
    remark = '历史CAN归档曲线页'
WHERE menu_id = 2109;

INSERT INTO sys_menu
VALUES ('2112', '历史CAN数据', '2100', '3', 'canHistory', 'payload/telemetry/canHistory/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:canHistory', 'table', 'admin', sysdate(), '', null, '历史CAN遥测表回放')
ON DUPLICATE KEY UPDATE
    menu_name = VALUES(menu_name),
    parent_id = VALUES(parent_id),
    order_num = VALUES(order_num),
    path = VALUES(path),
    component = VALUES(component),
    perms = VALUES(perms),
    icon = VALUES(icon),
    remark = VALUES(remark);

INSERT INTO sys_menu
VALUES ('2113', '历史文件数据', '2100', '5', 'fileHistory', 'payload/telemetry/fileHistory/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:fileHistory', 'table', 'admin', sysdate(), '', null, '历史文件遥测表回放')
ON DUPLICATE KEY UPDATE
    menu_name = VALUES(menu_name),
    parent_id = VALUES(parent_id),
    order_num = VALUES(order_num),
    path = VALUES(path),
    component = VALUES(component),
    perms = VALUES(perms),
    icon = VALUES(icon),
    remark = VALUES(remark);

INSERT INTO sys_menu
VALUES ('2114', '历史文件曲线', '2100', '6', 'fileCurve', 'payload/telemetry/fileCurve/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:fileCurve', 'chart', 'admin', sysdate(), '', null, '历史文件遥测曲线')
ON DUPLICATE KEY UPDATE
    menu_name = VALUES(menu_name),
    parent_id = VALUES(parent_id),
    order_num = VALUES(order_num),
    path = VALUES(path),
    component = VALUES(component),
    perms = VALUES(perms),
    icon = VALUES(icon),
    remark = VALUES(remark);

INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (2, 2112);
INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (2, 2113);
INSERT IGNORE INTO sys_role_menu (role_id, menu_id) VALUES (2, 2114);
