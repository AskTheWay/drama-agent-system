"""
配置文件 — API Key 等敏感信息从环境变量或 .env 文件读取
使用前复制 .env.example 为 .env 并填入真实 key
"""

import os
from pathlib import Path

# .env 文件路径
ENV_FILE = Path(__file__).parent / ".env"


def _load_env():
    """从 .env 文件加载环境变量"""
    if ENV_FILE.exists():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


_load_env()

# API Keys — 优先从环境变量读取
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "mimo-v2.5-pro")

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
