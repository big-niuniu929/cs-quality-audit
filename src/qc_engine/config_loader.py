from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    """读取单个 YAML 配置，缺失或空文件返回空字典。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data if isinstance(data, dict) else {}


def load_all_config(config_dir: Path) -> dict[str, dict[str, Any]]:
    """加载全部配置，返回按模块分组的字典。"""
    return {
        "app": load_yaml(config_dir / "config.yaml"),
        "rules": load_yaml(config_dir / "rules.yaml"),
        "scoring": load_yaml(config_dir / "scoring.yaml"),
        "roles": load_yaml(config_dir / "roles.yaml"),
        "products": load_yaml(config_dir / "products.yaml"),
    }
