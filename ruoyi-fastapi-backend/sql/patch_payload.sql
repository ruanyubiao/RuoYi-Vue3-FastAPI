-- ============================================================
-- 地检平台业务补丁 (SQLite)
-- 幂等脚本：可重复执行。应用到现网库 ruoyi-fastapi.db：
--   sqlite3 ruoyi-fastapi.db ".read sql/patch_payload.sql"
-- 同等内容已同步到 ruoyi-fastapi.sql / ruoyi-fastapi-pg.sql（语法略有差异）。
-- ============================================================

-- ---------- 指令序列表 ----------
CREATE TABLE IF NOT EXISTS payload_cmd_sequence (
  seq_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  seq_name    VARCHAR(100) NOT NULL,
  commands    TEXT         DEFAULT '[]',
  status      CHAR(1)      DEFAULT '0',
  create_by   VARCHAR(64)  DEFAULT '',
  create_time DATETIME,
  update_by   VARCHAR(64)  DEFAULT '',
  update_time DATETIME,
  remark      VARCHAR(500) DEFAULT ''
);

-- ---------- 业务菜单 ----------
-- 一级目录
INSERT OR IGNORE INTO sys_menu VALUES(2000, '遥控',   0, 5, 'telecontrol', NULL, '', '', 1, 0, 'M', '0', '0', '', 'cascader',  'admin', datetime('now'), '', NULL, '遥控目录');
INSERT OR IGNORE INTO sys_menu VALUES(2100, '遥测',   0, 6, 'telemetry',   NULL, '', '', 1, 0, 'M', '0', '0', '', 'chart',     'admin', datetime('now'), '', NULL, '遥测目录');
INSERT OR IGNORE INTO sys_menu VALUES(2200, '单板',   0, 7, 'board',       NULL, '', '', 1, 0, 'M', '0', '0', '', 'component', 'admin', datetime('now'), '', NULL, '单板目录');
INSERT OR IGNORE INTO sys_menu VALUES(2300, 'LVDS',   0, 8, 'lvds',        NULL, '', '', 1, 0, 'M', '0', '0', '', 'tab',       'admin', datetime('now'), '', NULL, 'LVDS目录');
INSERT OR IGNORE INTO sys_menu VALUES(2400, '重构',   0, 9, 'refactor', 'payload/refactor/index', '', '', 1, 0, 'C', '0', '0', 'payload:refactor:view', 'build', 'admin', datetime('now'), '', NULL, '重构页面');

-- 遥控 二级
INSERT OR IGNORE INTO sys_menu VALUES(2001, '控制开关', 2000, 1, 'control',  'payload/telecontrol/control/index',  '', '', 1, 0, 'C', '0', '0', 'payload:control:view',     'switch', 'admin', datetime('now'), '', NULL, '控制开关页');
INSERT OR IGNORE INTO sys_menu VALUES(2002, '遥控',     2000, 2, 'command',  'payload/telecontrol/command/index',  '', '', 1, 0, 'C', '0', '0', 'payload:telecontrol:send', 'guide',  'admin', datetime('now'), '', NULL, '遥控页面');
INSERT OR IGNORE INTO sys_menu VALUES(2003, '指令序列', 2000, 3, 'sequence', 'payload/telecontrol/sequence/index', '', '', 1, 0, 'C', '0', '0', 'payload:sequence:list',    'list',   'admin', datetime('now'), '', NULL, '指令序列页');
INSERT OR IGNORE INTO sys_menu VALUES(2004, '开发测试', 2000, 4, 'devtest',  'payload/telecontrol/devtest/index',  '', '', 1, 0, 'C', '0', '0', 'payload:devtest:view',     'bug',    'admin', datetime('now'), '', NULL, '开发测试页');
-- 指令序列 按钮权限
INSERT OR IGNORE INTO sys_menu VALUES(2031, '序列查询', 2003, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:sequence:query',  '#', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2032, '序列新增', 2003, 2, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:sequence:add',    '#', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2033, '序列修改', 2003, 3, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:sequence:edit',   '#', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2034, '序列删除', 2003, 4, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:sequence:remove', '#', 'admin', datetime('now'), '', NULL, '');

-- 遥测 二级（来源 TeleMetryCfg.json page[]）
INSERT OR IGNORE INTO sys_menu VALUES(2101, '0xFF：B-1主要包',         2100, 1, 'tmFF', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2102, '0xFD：B-2捕跟同轴标校包', 2100, 2, 'tmFD', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2103, '0xFB：B-3算轨包',         2100, 3, 'tmFB', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2104, '0xF9：B-4-1指向标校包',   2100, 4, 'tmF9', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2105, '0xF7：B-4-2星敏遥测包',   2100, 5, 'tmF7', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2106, '0xFE：算轨异步包1',       2100, 6, 'tmFE', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
INSERT OR IGNORE INTO sys_menu VALUES(2107, '0xFC：算轨异步包2',       2100, 7, 'tmFC', 'payload/telemetry/table/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:view', 'table', 'admin', datetime('now'), '', NULL, '');
-- 已存在菜单时清空冗余 query（类型由路径 tmXX 解析）
UPDATE sys_menu SET query = '' WHERE menu_id BETWEEN 2101 AND 2107;
-- 遥测曲线
INSERT OR IGNORE INTO sys_menu VALUES(2108, '遥测曲线', 2100, 8, 'curve', 'payload/telemetry/curve/index', '', '', 1, 0, 'C', '0', '0', 'payload:telemetry:curve', 'chart', 'admin', datetime('now'), '', NULL, '遥测曲线页');

-- 单板 二级
INSERT OR IGNORE INTO sys_menu VALUES(2201, '相机测试', 2200, 1, 'camera', 'payload/board/camera/index', '', '', 1, 0, 'C', '0', '0', 'payload:camera:view', 'eye', 'admin', datetime('now'), '', NULL, '相机测试页');

-- LVDS 二级
INSERT OR IGNORE INTO sys_menu VALUES(2301, '工程遥测', 2300, 1, 'engineering', 'payload/lvds/engineering/index', '', '', 1, 0, 'C', '0', '0', 'payload:lvds:view', 'monitor', 'admin', datetime('now'), '', NULL, '工程遥测页');

-- ---------- 角色授权（超级管理员 role_id=1 默认全量，无需授权；此处授予普通角色 role_id=2）----------
INSERT OR IGNORE INTO sys_role_menu(role_id, menu_id)
SELECT 2, menu_id FROM sys_menu WHERE menu_id BETWEEN 2000 AND 2400;
