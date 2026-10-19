# 安装
1. 双击执行 install.bat，会自动请求管理员权限。
2. 如果提示 "Please restart the system"：重启电脑，登录后打开 Docker Desktop，等它初始化完成，再双击 install.bat
3. 完成后双击更新包里的 update.bat
- 重跑 install.bat 会先停止运行中的后端服务 PGT，结束后再启动


## 清理
部署完成后 deploy 目录可以删除


## 日志
安装目录 D:\PGT，没有 D 盘时为 C:\PGT
- 后端服务： D:\PGT\data\logs\service\
- nginx：  D:\PGT\nginx\logs\
- mysql8： docker logs mysql8
- redis：  docker logs redis


# 说明（开发人员）

## 脚本步骤

1. 脚本（docker\docker_env_install.bat）先检查 WSL、VC++ 运行库、Docker Desktop，没装的会自动安装（装给系统用户）；WSL 安装失败时会自动改用 wsl --install --no-distribution
2. 如果提示 "Please restart the system"：重启系统，登录后运行 Docker Desktop，不需要注册登录，等它初始化完成，再双击 install.bat
3. Docker 已就绪时，脚本继续：解压到 D:\PGT（没有 D 盘时为 C:\PGT）、导入镜像 docker\docker_image_nginx_redis_mysql.tar.gz（也支持 .tar）、启动 mysql/redis/nginx 容器、重新注册后端服务 PGT（开机自启；之前改成手动或禁用的保持不变），最后生成桌面 PGT 文件夹和快捷方式（以后可再次运行 <安装目录>\service\init\desktop_shortcut.bat 重建）
4. 完成后运行更新包里的 update.bat 安装前端和后端


## 注意
- 后端服务开机后先等 90 秒，再一直等到 Docker 启动完成才启动；Docker 要登录系统后才启动，没人登录时服务会一直等待
- 停止后端只用桌面 stop_py 或 net stop PGT，直接结束 python.exe 会被自动重启
- 开机自启：<安装目录>\service\init\disable_backend_autostart.bat 关闭，enable_backend_autostart.bat 打开；两种情况下 stop_py/start_py 都可用
- 没有 releases\current.txt（后端未安装）时，服务启动后直接退出
- MySQL/Redis 只绑定 127.0.0.1，不要改


## 导入镜像
双击 docker\docker_images_import.bat


## 导出镜像（联网机器）
1. 双击 docker\docker_images_export.bat
2. 生成 docker\docker_image_nginx_redis_mysql.tar.gz
3. 需要 gzip.exe

