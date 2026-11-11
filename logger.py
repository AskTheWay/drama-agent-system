"""
统一日志配置 — Python logging 标准库
所有模块通过 get_logger(__name__) 获取 logger 实例
"""

import logging
import os

LOG_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(LOG_DIR, "app.log"),
            encoding="utf-8",
        ),
    ],
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# 数据流转专用 logger — 记录节点间完整数据，写入 flow.log
flow_logger = logging.getLogger("flow")
flow_logger.setLevel(logging.DEBUG)
flow_logger.propagate = False  # 防止 DEBUG 级完整 state 冒泡到 root logger 重复输出
_flow_handler = logging.FileHandler(
    os.path.join(LOG_DIR, "flow.log"), encoding="utf-8"
)
_flow_handler.setFormatter(logging.Formatter(
    "%(asctime)s %(message)s", datefmt="%H:%M:%S"
))
flow_logger.addHandler(_flow_handler)
