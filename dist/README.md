# 更新
1. 把 dist 拷到桌面（或直接在 U 盘里），双击 update.bat，点"是"，等窗口跑完（几分钟）
2. 看到 [OK]：更新完成
3. 看到 [ERROR]：原来的版本还在正常运行；把 D:\PGT\data\logs\install\ 里最新的日志和窗口截图发给开发人员


## 日志
安装目录 D:\PGT，没有 D 盘时为 C:\PGT
- 更新日志：D:\PGT\data\logs\install\backend_<时间>.log
- 后端服务：D:\PGT\data\logs\service\


## 注意
- 更新不需要先手动 stop_py，只需要执行update.bat
- 停止后端只用桌面 stop_py 或 net stop PGT，直接结束 python.exe 会被自动重启
- 后端服务开机后先等 90 秒，再等 Docker 启动完成才启动


# 说明（开发人员）

## 更新包内容
- update.bat
- html_*.zip（前端）
- pgt-*.whl（后端）
- pkg（后端依赖）
- db\patches\*.sql（数据库补丁）
- 不放 deploy、history

## 交给现场
- 把更新包文件夹压缩或直接拷给现场
- 按上面"更新"操作

## 首次安装
- 在联网机器运行 pkg\get_pkg_cache.bat，下载后端全部依赖到 dist\pkg\pkg_cache
- 拷整个 dist 到 目标机器
- 目标机器 用 dist\deploy\install.bat 装好基础环境
- 删除dist

## 数据库
- 只用 MySQL
- 初始 SQL：ruoyi-fastapi-backend\sql\ruoyi-fastapi-my.sql（最新完整库）
- 补丁源文件：ruoyi-fastapi-backend\sql\patches\V<4位版本>__<说明>.sql，如 V0001__payload_query_perms.sql
- 新增补丁：
  - 版本号 +1，新建补丁文件
  - 同样的改动也合并进 ruoyi-fastapi-my.sql
  - 运行后端 build.bat
- 已发布的补丁不能再改，要改就再加一个补丁
- 后端 build.bat 自动：
  - 复制 ruoyi-fastapi-my.sql 到 dist\db\，补丁到 dist\db\patches\
  - 生成 zz_schema_version.sql：建 schema_version 表，当时已有的补丁记为 BASELINE
  - 替换 dist\deploy\PGT.zip 里的 PGT/mysql/sql/
- 新装：mysql 在数据目录为空时执行 PGT/mysql/sql，其中已包含当时的全部补丁（记为 BASELINE）
- 更新：db_patches_apply.bat 只执行没成功执行过的补丁
  - 已执行的补丁校验 SHA-256，文件被改过就报错停止
  - 失败的补丁记为 success=0，下次重新执行

## 脚本
- 更新脚本在 <安装目录>\service（D:\PGT\service）
- 运行状态在 <安装目录>\releases（D:\PGT\releases）：各版本环境、current.txt、previous.txt、secrets.env
- install_frontend.bat：解压前端代码包到 D:\PGT\nginx\html\
- install_backend.bat：
  - 安装 pgt
  - 停止/启动服务 PGT
  - 执行数据库补丁
  - 健康检查失败自动回滚
- 后端环境：
  - 更新包里有 pkg\pkg_cache：新建环境，全部依赖离线安装
  - 没有 pkg\pkg_cache：复制当前版本的环境，只替换 pgt
  - 新增依赖从 pgt-*.whl 旁边的 whl 安装
- db_patches_apply.bat：后端更新会自动调用

## 单独执行
- 只更新前端：D:\PGT\service\install_frontend.bat "<更新包目录>"
- 只更新后端：D:\PGT\service\install_backend.bat "<更新包目录>"
- 只执行数据库补丁：D:\PGT\service\db_patches_apply.bat "<更新包目录>"
- 可加第二个参数 nopause：结束时不等待
