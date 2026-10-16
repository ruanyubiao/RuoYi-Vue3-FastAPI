# 环境安装-software

## 安装docker软件
1. 安装 wsl.2.7.11.0.x64.msi，如果安装不成功，使用命令安装： wsl --install --no-distribution
2. 安装 Docker Desktop Installer.exe， 装给系统用户
3. 重启系统，重启登录系统后，运行docker软件，不需要注册登录，只需要等它初始化完成就行

## 安装其他软件，容器等
运行 install.bat

# 代码更新-dist
前端：
1. 双击执行 install_frontend.bat ，更新脚本会解压前端代码包到 D:\docker\nginx\html\
后端：
1. 停止服务，stop_py
2. 双击执行 install_backend.bat ，安装扩展包
3. 启动服务，start_py


## 启动停止

启动服务：start_py
停止服务：stop_py



# 其他

## 存在问题
docker部署python行不通，容器存在宿主机串口，pcie 读取问题。


## 分步骤说明

### 导入镜像
docker load -i .\docker\docker_image_nginx_redis_mysql.tar


### 导出镜像
docker save -o docker_image_nginx_redis_mysql.tar nginx:1.25-alpine mysql:8.0 redis:latest


### 创建容器 redis，mysql
解压 docker_compose.zip 到 D:\
打开终端，执行:
docker compose --project-directory D:\docker\mysql up -d
docker compose --project-directory D:\docker\redis up -d
docker compose --project-directory D:\docker\nginx up -d


### python安装
原版python，解压 Python313.zip 到 D:\tools\
带代码版本，解压 Python.zip 到 D:\tools\
设置环境变量, 执行D:\tools\00_env.bat


## 开机启动配置
资源管理器，%LOCALAPPDATA%\PGT
双击执行：create_task_startup.bat
