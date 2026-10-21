# 安装
1. 双击执行 install.bat，会自动请求管理员权限，选择安装模式：
   - 1 采集端：只装采集，不装 Docker；输入采集机标识（字母、数字、_、-）和服务端地址
   - 2 服务端：Docker 里运行 mysql、redis、nginx 和后端容器 backend
   - 3 合成模式：后端在本机运行并拉起采集，mysql、redis、nginx 在 Docker 里
2. 如果提示 "Please restart the system"：重启电脑，登录后打开 Docker Desktop，等它初始化完成，再双击 install.bat
3. 完成后双击更新包里的 update.bat
- 也可以带参数：install.bat 1 <采集机标识> <服务端地址>、install.bat 2、install.bat 3
- 选 1 和 2 是在已装的分离模式上追加，一台电脑可以都装
- 合成模式和分离模式之间切换，会先要求确认
- 重跑 install.bat 会先停止运行中的服务 PGT，结束后再启动


## 清理
部署完成后 deploy 目录可以删除


## 日志
安装目录 D:\PGT，没有 D 盘时为 C:\PGT
- 服务 PGT（后端或采集）： D:\PGT\data\logs\service\
- 后端容器：docker logs backend
- nginx：  D:\PGT\nginx\logs\
- mysql8： docker logs mysql8
- redis：  docker logs redis


# 说明（开发人员）

## 脚本步骤

1. 采集端跳过 Docker：脚本（docker\docker_env_install.bat）先检查 WSL、VC++ 运行库、Docker Desktop，没装的会自动安装（装给系统用户）；WSL 安装失败时会自动改用 wsl --install --no-distribution
2. 如果提示 "Please restart the system"：重启系统，登录后运行 Docker Desktop，不需要注册登录，等它初始化完成，再双击 install.bat
3. 解压到 D:\PGT（没有 D 盘时为 C:\PGT），安装模式写入 D:\PGT\releases\role.env
4. 合成模式：导入镜像 docker\docker_image_pgt.tar.gz（也支持 .tar）、启动 mysql/redis/nginx 容器、重新注册服务 PGT（开机自启；之前改成手动或禁用的保持不变）
5. 服务端：
   - backend\env\pgt.env 不存在时由 pgt.env.example 生成，并写入 JWT 密钥（有 releases\secrets.env 就用它的）
   - 防火墙开放 80、12580（所有地址）和 6379（本地子网），采集端通过 6379 连接 Redis
   - 导入镜像，启动 mysql/redis/nginx 和 backend 容器；backend 在 update.bat 放入 whl 后才运行
   - 不使用服务 PGT（本机也装了采集端时才注册）
6. 采集端：注册服务 PGT，服务只运行采集
7. 最后生成桌面 PGT 文件夹和快捷方式（以后可再次运行 <安装目录>\service\init\desktop_shortcut.bat 重建）
8. 完成后运行更新包里的 update.bat


## 注意
- 服务 PGT 运行 service\run_pgt.bat：按 role.env 运行 run_backend.bat（合成模式）或 run_collector.bat（采集端）
- 服务开机后先等 90 秒；合成模式再一直等到 Docker 启动完成，采集端等服务端 Redis 能连上
- Docker 要登录系统后才启动，没人登录时服务会一直等待
- 停止服务只用桌面 stop_py 或 net stop PGT，直接结束 python.exe 会被自动重启
- 开机自启：<安装目录>\service\init\disable_backend_autostart.bat 关闭，enable_backend_autostart.bat 打开；两种情况下 stop_py/start_py 都可用
- 卸载：<安装目录>\service\init\uninstall.bat 删除服务 PGT 和 Docker 容器，镜像、数据和安装目录保留
- 没有 releases\current.txt（还没运行 update.bat）时，服务启动后直接退出
- MySQL 只绑定 127.0.0.1；Redis 绑定 0.0.0.0，只有服务端的防火墙开放 6379（Redis 没有密码，只在可信局域网使用）


## 导入镜像
双击 docker\docker_images_import.bat


## 导出镜像（联网机器）
1. 双击 docker\docker_images_export.bat
2. 生成 docker\docker_image_pgt.tar.gz
3. 需要 gzip.exe
4. 修改 docker\backend\entrypoint.sh 后要重新导出，镜像里才是新的
