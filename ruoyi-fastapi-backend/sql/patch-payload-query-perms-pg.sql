-- 已有库补查询和设备操作权限。新库用 ruoyi-fastapi-pg.sql 即可，不必再执行本文件。
-- 授给已经拥有地检菜单（2000–2609）的角色，避免现有页面失去开关设备的权限。

insert into sys_menu (menu_id, menu_name, parent_id, order_num, path, component, query, route_name, is_frame, is_cache, menu_type, visible, status, perms, icon, create_by, create_time, remark)
select 2610, '设备查询', 2502, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:device:query', '#', 'admin', current_timestamp, '只读查看设备会话与状态'
where not exists (select 1 from sys_menu where menu_id = 2610);

insert into sys_menu (menu_id, menu_name, parent_id, order_num, path, component, query, route_name, is_frame, is_cache, menu_type, visible, status, perms, icon, create_by, create_time, remark)
select 2611, '设备操作', 2502, 2, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:device:operate', '#', 'admin', current_timestamp, '打开或关闭设备连接'
where not exists (select 1 from sys_menu where menu_id = 2611);

insert into sys_menu (menu_id, menu_name, parent_id, order_num, path, component, query, route_name, is_frame, is_cache, menu_type, visible, status, perms, icon, create_by, create_time, remark)
select 2612, '遥控查询', 2012, 1, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:telecontrol:query', '#', 'admin', current_timestamp, '查看遥控配置、指令定义和发送历史'
where not exists (select 1 from sys_menu where menu_id = 2612);

insert into sys_menu (menu_id, menu_name, parent_id, order_num, path, component, query, route_name, is_frame, is_cache, menu_type, visible, status, perms, icon, create_by, create_time, remark)
select 2613, '单板配置查询', 2200, 7, '', '', '', '', 1, 0, 'F', '0', '0', 'payload:board:query', '#', 'admin', current_timestamp, '查看单板遥控与遥测配置'
where not exists (select 1 from sys_menu where menu_id = 2613);

insert into sys_role_menu (role_id, menu_id)
select distinct rm.role_id, new_menu.menu_id
from sys_role_menu rm
join sys_menu new_menu on new_menu.menu_id between 2610 and 2613
where rm.menu_id between 2000 and 2609
  and not exists (
    select 1 from sys_role_menu owned
    where owned.role_id = rm.role_id and owned.menu_id = new_menu.menu_id
  );

select setval('sys_menu_menu_id_seq', (select max(menu_id) from sys_menu));
