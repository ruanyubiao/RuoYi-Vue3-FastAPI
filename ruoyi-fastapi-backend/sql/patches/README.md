# 数据库补丁规则（MySQL）

本文件是数据库修改规则的唯一来源，开发人员和 AI 代理都按这里做。

## 什么时候加补丁
- 任何表结构或初始数据的改动，都新增一个补丁
- 只写 MySQL；pg、sqlite 版本除非明确要求，否则不改

## 命名
- `V<4位版本>__<说明>.sql`，例如 `V0002__add_device_alias.sql`
- 版本号 = 本目录当前最大版本 + 1，不重复
- 说明只用 `[A-Za-z0-9_]`
- 一个补丁只做一件事

## 已发布的补丁不能改
- 进过 build.bat 的补丁就算已发布
- 现场按 SHA-256 校验文件，改一个字节（包括空格、换行符）都会让更新报错停止
- 要修正就再加一个新补丁

## 同时改初始 SQL
- 同样的改动也合并进 `sql/ruoyi-fastapi-my.sql`
- 目标：新装的库 = 老库执行完所有补丁
- 新装时补丁不会执行（build.bat 把当时已有的补丁记为 BASELINE），漏合并的话新装的库就缺这次改动

## 补丁要能重复执行
- 执行失败会记为 success=0，下次整个文件从头再执行
- 补丁在 ruoyi-fastapi 库里执行，不写 `use <库名>`
- 常用写法：

```sql
-- 建表 / 删表
create table if not exists demo (...);
drop table if exists demo_old;

-- 插数据
insert ignore into sys_menu values (...);
insert into sys_config (...) values (...) on duplicate key update config_value = values(config_value);

-- 加列（MySQL 没有 add column if not exists）：先查 information_schema
set @s = (select if(count(*) = 0,
    'alter table sys_user add column alias varchar(64) null comment ''alias''',
    'select 1')
  from information_schema.columns
  where table_schema = database() and table_name = 'sys_user' and column_name = 'alias');
prepare st from @s; execute st; deallocate prepare st;

-- 加索引：同样先查 information_schema.statistics
```

## 不要手动改的文件
- `dist/db/`（`ruoyi-fastapi-my.sql`、`zz_schema_version.sql`、`patches/`）由 build.bat 生成
- `dist/deploy/PGT.zip` 里的 `PGT/mysql/sql/` 也由 build.bat 更新

## 生效
- 运行 `ruoyi-fastapi-backend\build.bat`：复制初始 SQL 和补丁到 `dist\db`，生成 `zz_schema_version.sql`，更新 PGT.zip
- 现场更新时 `db_patches_apply.bat` 只执行没成功执行过的补丁

## 代理检查清单
- [ ] 新建了 `V<下一个版本>__<说明>.sql`，没改已有补丁
- [ ] 只改了 MySQL
- [ ] 补丁可以重复执行
- [ ] 同样的改动已合并进 `sql/ruoyi-fastapi-my.sql`
- [ ] 没改 `dist/db`、`zz_schema_version.sql`
- [ ] 提醒用户运行 build.bat
