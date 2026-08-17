# 数据库
## sqlite
sqlite3 ruoyi-fastapi.db < sql\ruoyi-fastapi-sqlite.sql




# 环境安装

## 前端

```bash
# 进入前端目录
cd ruoyi-fastapi-frontend

# 安装依赖
npm install
# 或
# npm install --registry=https://registry.npmmirror.com

# 启动服务
npm run dev
```

## 后端

```bash
# 进入后端目录

cd ruoyi-fastapi-backend
python -m venv venv
venv\Scripts\activate.bat
pip install -r requirements.txt --find-links ../dist



# 配置环境
# 暂时跳过

# 运行sql文件
# 暂时跳过

# 运行后端
python app.py --env=dev
# ruoyi app run --env=dev
```

## 访问

```bash
# 默认账号密码
账号：admin
密码：admin123

# 浏览器访问
地址：http://localhost:80
```








# 关于
[基于 RuoYi-Vue3-FastAPI 二次开发](https://github.com/insistence/RuoYi-Vue3-FastAPI)
