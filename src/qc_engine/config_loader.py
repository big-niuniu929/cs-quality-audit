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


def load_scoring_profiles(config_dir: Path) -> list[dict[str, Any]]:
    """扫描可选的评分标准：默认 scoring.yaml + scoring_profiles/*.yaml。"""
    items: list[dict[str, Any]] = []
    default = load_yaml(config_dir / "scoring.yaml")
    if default:
        items.append({
            "id": "", "file": "scoring.yaml",
            "title": default.get("title") or "现行标准",
            "version": default.get("version") or "",
            "description": default.get("description") or "",
            "config": default,
        })
    profile_dir = config_dir / "scoring_profiles"
    for path in sorted(profile_dir.glob("*.yaml")) if profile_dir.exists() else []:
        cfg = load_yaml(path)
        if not cfg:
            continue
        items.append({
            "id": path.name, "file": str(path),
            "title": cfg.get("title") or path.stem,
            "version": cfg.get("version") or "",
            "description": cfg.get("description") or "",
            "config": cfg,
        })
    return items
