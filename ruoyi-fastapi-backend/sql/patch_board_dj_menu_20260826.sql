-- 单板菜单新增「地检板」（UDP / 表格4工程遥测）。可重复执行。
-- 本地：mysql -u root -p123456 --default-character-set=utf8mb4 ruoyi-fastapi < sql/patch_board_dj_menu_20260826.sql

INSERT INTO sys_menu
VALUES ('2204', '地检板', '2200', '4', 'dj', 'payload/board/dj/index', '', '', 1, 0, 'C', '0', '0', 'payload:dj:view', 'monitor', 'admin', sysdate(), '', null, '地检板 UDP（表格4工程遥测）')
ON DUPLICATE KEY UPDATE
    menu_name = VALUES(menu_name),
    parent_id = VALUES(parent_id),
    order_num = VALUES(order_num),
    path = VALUES(path),
    component = VALUES(component),
    perms = VALUES(perms),
    icon = VALUES(icon),
    remark = VALUES(remark);

INSERT INTO sys_role_menu (role_id, menu_id)
SELECT 2, 2204 FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM sys_role_menu WHERE role_id = 2 AND menu_id = 2204
);
