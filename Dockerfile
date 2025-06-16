FROM docker.1ms.run/library/python:3.12-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装调试工具
RUN pip install debugpy

# 复制requirements文件并安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt

# 复制源代码
COPY src/ ./src/

# 创建数据目录（如果需要）
RUN mkdir -p /app/data /app/logs

# 暴露调试端口
EXPOSE 5678

# 设置环境变量
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# 默认启动命令（带调试）
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "src/main.py"] 