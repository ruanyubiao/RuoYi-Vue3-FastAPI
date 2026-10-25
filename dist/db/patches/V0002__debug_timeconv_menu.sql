-- 调试菜单增加「时间转换」。新库用 ruoyi-fastapi-my.sql 即可，不必再执行本文件。
-- 授给已经拥有调试菜单（2500–2506）的角色。

insert ignore into sys_menu values('2507', '时间转换', '2500', '7', 'timeconv', 'payload/debug/timeconv/index', '', '', 1, 0, 'C', '0', '0', 'payload:timeconv:view', 'time', 'admin', sysdate(), '', null, '协议纪元与日期时间格式转换');

insert ignore into sys_role_menu (role_id, menu_id)
select distinct rm.role_id, 2507
from sys_role_menu rm
where rm.menu_id between 2500 and 2506;
