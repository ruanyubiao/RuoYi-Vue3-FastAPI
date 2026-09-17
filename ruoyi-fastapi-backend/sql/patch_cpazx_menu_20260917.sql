-- CPA 指向菜单。可重复执行。
-- 本地：mysql -u root -p123456 --default-character-set=utf8mb4 ruoyi-fastapi < sql/patch_cpazx_menu_20260917.sql

INSERT INTO sys_menu
VALUES ('2206', 'CPA指向', '2200', '6', 'cpazx', 'payload/board/cpazx/index', '', '', 1, 0, 'C', '0', '0', 'payload:cpazx:view', 'monitor', 'admin', sysdate(), '', null, 'CPA指向单板（协议V1.0，RS422 921600 8N1）')
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
SELECT 2, 2206 FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM sys_role_menu WHERE role_id = 2 AND menu_id = 2206
);
