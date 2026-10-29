-- 调试菜单增加「日志下载」。新库用 ruoyi-fastapi-my.sql 即可，不必再执行本文件。
-- 授给已经拥有调试菜单（2500–2507）的角色。

insert ignore into sys_menu values('2508', '日志下载', '2500', '8', 'logDownload', 'payload/debug/logDownload/index', '', '', 1, 0, 'C', '0', '0', 'payload:logdownload:view', 'download', 'admin', sysdate(), '', null, '上传与本地日志 ZIP 下载');

insert ignore into sys_role_menu (role_id, menu_id)
select distinct rm.role_id, 2508
from sys_role_menu rm
where rm.menu_id between 2500 and 2507;
