-- 调试菜单增加「数字转换」。新库用 ruoyi-fastapi-my.sql 即可，不必再执行本文件。
-- 授给已经拥有调试菜单（2500–2505）的角色。

insert ignore into sys_menu values('2506', '数字转换', '2500', '6', 'numconv', 'payload/debug/numconv/index', '', '', 1, 0, 'C', '0', '0', 'payload:numconv:view', 'edit', 'admin', sysdate(), '', null, '整数进制与数字 HEX 互转');

insert ignore into sys_role_menu (role_id, menu_id)
select distinct rm.role_id, 2506
from sys_role_menu rm
where rm.menu_id between 2500 and 2505;
