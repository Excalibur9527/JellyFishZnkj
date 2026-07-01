# ── Stage 1: build ────────────────────────────────────────────────
FROM node:20-slim AS builder

# 国内镜像源
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate && \
    pnpm config set registry https://registry.npmmirror.com

WORKDIR /app

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# 构建时注入后端地址（可通过 docker build --build-arg 覆盖）
ARG VITE_API_BASE_URL=http://localhost:8765
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_BACKEND_URL=$VITE_API_BASE_URL

RUN pnpm build

# ── Stage 2: serve ────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# 国内镜像源（可选，加速 apk 安装）
RUN sed -i "s/dl-cdn.alpinelinux.org/mirrors.aliyun.com/g" /etc/apk/repositories 2>/dev/null || true

# 内联最简 nginx 配置：SPA fallback + 静态资源缓存
RUN printf 'server {\n\
    listen 80;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    gzip on;\n\
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
    location /assets/ {\n\
        try_files $uri $uri/ /index.html;\n\
        expires 1y;\n\
        add_header Cache-Control "public, immutable";\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
