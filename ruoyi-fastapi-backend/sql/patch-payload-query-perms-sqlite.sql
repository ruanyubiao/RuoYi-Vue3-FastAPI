-- 已有库补查询和设备操作权限。新库用 ruoyi-fastapi-sqlite.sql 即可，不必再执行本文件。
-- 授给已经拥有地检菜单（2000–2609）的角色，避免现有页面失去开关设备的权限。

INSERT OR IGNORE INTO sys_menu VALUES(2610, '设备查询', 2502, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:device:query', '#', 'admin', datetime('now'), '', NULL, '只读查看设备会话与状态');
INSERT OR IGNORE INTO sys_menu VALUES(2611, '设备操作', 2502, 2, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:device:operate', '#', 'admin', datetime('now'), '', NULL, '打开或关闭设备连接');
INSERT OR IGNORE INTO sys_menu VALUES(2612, '遥控查询', 2012, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:telecontrol:query', '#', 'admin', datetime('now'), '', NULL, '查看遥控配置、指令定义和发送历史');
INSERT OR IGNORE INTO sys_menu VALUES(2613, '单板配置查询', 2200, 7, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:board:query', '#', 'admin', datetime('now'), '', NULL, '查看单板遥控与遥测配置');

INSERT OR IGNORE INTO sys_role_menu (role_id, menu_id)
SELECT DISTINCT rm.role_id, new_menu.menu_id
FROM sys_role_menu rm
JOIN sys_menu new_menu ON new_menu.menu_id BETWEEN 2610 AND 2613
WHERE rm.menu_id BETWEEN 2000 AND 2609;
