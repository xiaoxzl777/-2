FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 用锁定版本装，和开发机的环境一致（requirements.lock 由 pip freeze 生成，里面没有只能在 Windows 上装的包）
COPY requirements.lock .
RUN pip install -r requirements.lock

COPY app ./app
COPY scripts ./scripts

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
