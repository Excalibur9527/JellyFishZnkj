# ── Stage 1: build ────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# 国内 Debian 镜像源
RUN sed -i "s/deb.debian.org/mirrors.aliyun.com/g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i "s/deb.debian.org/mirrors.aliyun.com/g" /etc/apt/sources.list 2>/dev/null || true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# 国内 PyPI 镜像源
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# 先拷贝依赖声明，利用 Docker layer cache
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# 拷贝源码
COPY app/ app/
COPY init_db.py init_storage.py ./

# ── Stage 2: runtime ──────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# 国内 Debian 镜像源
RUN sed -i "s/deb.debian.org/mirrors.aliyun.com/g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i "s/deb.debian.org/mirrors.aliyun.com/g" /etc/apt/sources.list 2>/dev/null || true

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app/ app/
COPY init_db.py init_storage.py ./

ENV PYTHONUNBUFFERED=1

EXPOSE 8765

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "2"]
