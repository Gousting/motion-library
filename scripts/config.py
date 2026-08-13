"""配置加载：config.yaml → .env → 进程环境变量（优先级递增）。

密钥约定（与 image-gen 对称）：config.yaml 里 api_key 一律占位符，真实值放项目根目录
``.env``（已 .gitignore 排除，永不提交），用大写环境变量名覆盖。
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
ENV_PATH = PROJECT_ROOT / ".env"

# .env / 进程环境变量里的密钥键名
VLM_API_KEY_ENV = "MOTIONLIB_VLM_API_KEY"


def _load_env_file(path: Path) -> dict[str, str]:
    """解析 .env 的 ``KEY=VALUE`` 行（跳过空行/注释）。"""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def load_config() -> dict:
    """加载并合并配置，解析密钥（.env / 环境变量覆盖占位符）。"""
    cfg: dict = {}
    if CONFIG_PATH.exists():
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
        if not isinstance(cfg, dict):
            cfg = {}

    # 密钥解析：进程环境变量 > .env > config.yaml 占位符
    env_file = _load_env_file(ENV_PATH)
    key = os.environ.get(VLM_API_KEY_ENV) or env_file.get(VLM_API_KEY_ENV) or ""
    if key:
        cfg.setdefault("vlm", {})["api_key"] = key
    return cfg


def get_vlm_api_key(cfg: dict) -> str:
    """取 VLM 审查密钥（已由 load_config 解析）。"""
    return (cfg.get("vlm") or {}).get("api_key", "")
