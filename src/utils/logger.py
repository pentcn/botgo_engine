import logging
import os
from datetime import datetime

# 创建logs目录（如果不存在）
logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(logs_dir, exist_ok=True)

# 配置日志格式
log_format = "%(asctime)s - %(levelname)s - %(message)s"
date_format = "%Y-%m-%d %H:%M:%S"


def get_logger():
    # 获取当前日期作为日志文件名
    current_date = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(logs_dir, f"{current_date}.log")

    # 创建logger
    logger = logging.getLogger("botgo")
    logger.setLevel(logging.INFO)

    # 如果logger已经有处理器，说明已经配置过，直接返回
    if logger.handlers:
        return logger

    # 创建文件处理器
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # 创建格式化器
    formatter = logging.Formatter(log_format, date_format)
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # 添加处理器到logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# 全局日志函数
def log(message, level="info"):
    logger = get_logger()
    level = level.lower()

    if level == "debug":
        logger.debug(message)
    elif level == "info":
        logger.info(message)
    elif level == "warning":
        logger.warning(message)
    elif level == "error":
        logger.error(message)
    elif level == "critical":
        logger.critical(message)
    else:
        logger.info(message)
