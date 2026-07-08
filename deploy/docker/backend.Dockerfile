FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_CACHE_DIR=/root/.cache/uv

WORKDIR /app

# 使用阿里云镜像源加速 apt
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources \
  && apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

# 使用阿里云 PyPI 镜像
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple uv

# uv 也配国内镜像（去掉 --frozen 让 uv 从镜像重新解析）
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --no-dev --no-install-project

COPY backend/ ./
RUN uv sync --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
