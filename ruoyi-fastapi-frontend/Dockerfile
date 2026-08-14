# 构建阶段
FROM node:20-slim AS builder
WORKDIR /app

# 1. 先只复制依赖描述文件（这两个文件很少变）
COPY package*.json ./

# 2. 设置镜像源并安装依赖（只要 package.json 不变，这层就永远用缓存）
RUN npm config set registry https://registry.npmmirror.com
RUN npm install

# 3. 最后再复制剩下的所有源代码（这层经常变，但它不影响上面的缓存）
COPY . .

# 4. 执行docker构建命令
RUN npm run build:docker

# 运行阶段
FROM nginx:1.25-alpine
WORKDIR /usr/share/nginx/html

# 复制构建产物
COPY --from=builder /app/dist .

# 暴露端口
EXPOSE 80

# 启动nginx
CMD ["nginx", "-g", "daemon off;"]