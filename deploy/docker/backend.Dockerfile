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

# 使用清华 PyPI 镜像安装 uv
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple uv

# uv 也配国内镜像
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Leverage Docker layer caching
COPY backend/pyproject.toml backend/uv.lock ./
# Install only dependencies first (project sources/readme not copied yet)
RUN uv sync --frozen --no-dev --no-install-project

# App source
COPY backend/ ./

# Now install the project (and ensure entrypoints/imports work)
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
