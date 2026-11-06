# hai 数据看板服务端
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
# 生产可用 gunicorn（单 worker 保证采集线程唯一）：
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8080", "app:app", "--threads", "8", "--timeout", "120"]
