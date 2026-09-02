-- 相机 v1.6 改名 + 新增相机 v1.7 菜单。可重复执行。
-- 本地：mysql -u root -p123456 --default-character-set=utf8mb4 ruoyi-fastapi < sql/patch_camera_v17_menu_20260902.sql

UPDATE sys_menu SET
    menu_name = '相机v1.6',
    remark = '相机 SC-LINK41EP V1.6'
WHERE menu_id = '2201';

UPDATE sys_menu SET order_num = '3' WHERE menu_id = '2202';
UPDATE sys_menu SET order_num = '4' WHERE menu_id = '2203';
UPDATE sys_menu SET order_num = '5' WHERE menu_id = '2204';

INSERT INTO sys_menu
VALUES ('2205', '相机v1.7', '2200', '2', 'camera_v17', 'payload/board/camera_v17/index', '', '', 1, 0, 'C', '0', '0', 'payload:camera_v17:view', 'eye', 'admin', sysdate(), '', null, '相机 SC-LINK41EP V1.7')
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
SELECT 2, 2205 FROM DUAL
WHERE NOT EXISTS (
    SELECT 1 FROM sys_role_menu WHERE role_id = 2 AND menu_id = 2205
);
