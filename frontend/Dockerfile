# 前端：先用 Node 打包，再把 dist 交给 Nginx（Nginx 同时转发 /api 到后端，配置在 nginx/default.conf，由 compose 挂进来）
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
