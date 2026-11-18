from __future__ import annotations

import re
from typing import Any


class ModelMatcher:
    """从「商品名称」文本里识别型号。

    规则：
    1. 套餐型号（bundles）按完整子串匹配（如 "MC75GEE+MT71M i5"）。
    2. 独立型号（models）按「词边界」匹配，长型号优先，避免 ST33 误配进 ST33W。
    3. 别名（aliases）先做归一化（如 "WT17（会议电视）" → "WT17"）。
    4. 识别不出的返回空字符串（留空白），绝不抛错、绝不返回 None 以外的假值。

    多型号同时出现时返回第一个（商品名称通常只对应一个型号/套餐）。
    """

    def __init__(self, products_config: dict[str, Any]):
        cfg = products_config or {}
        self.models: list[str] = list(cfg.get("models", []))
        # 长型号优先，避免前缀误配
        self.models.sort(key=len, reverse=True)
        self.bundles: list[str] = list(cfg.get("bundles", []))
        self.bundles.sort(key=len, reverse=True)
        self.aliases: dict[str, str] = {str(k): str(v) for k, v in (cfg.get("aliases", {}) or {}).items()}
        # 兜底：商品名称末尾的型号代号，如 SH75CAB / EG65CAD / W98PNB / CH98ML / WT15 / UC-W20
        self.fallback_re = re.compile(
            r"(?<![A-Za-z0-9])[A-Z]{1,3}\d{2}[A-Z]{1,3}(?![A-Za-z0-9])"
        )

    def match(self, product_name: Any) -> str:
        """返回识别出的型号；识别不出返回空字符串。"""
        if product_name is None:
            return ""
        text = str(product_name).strip()
        if not text:
            return ""

        # 1) 别名归一化
        for src, dst in self.aliases.items():
            if src in text:
                return dst

        # 2) 套餐型号（完整子串）
        for b in self.bundles:
            if b in text:
                return b

        # 3) 独立型号：词边界匹配（型号前后不能紧跟字母数字，避免误配）
        for m in self.models:
            pattern = rf"(?<![A-Za-z0-9]){re.escape(m)}(?![A-Za-z0-9])"
            if re.search(pattern, text):
                return m

        # 4) 兜底：从商品名称末尾提取型号代号（字母+数字+字母）
        candidates = self.fallback_re.findall(text)
        if candidates:
            # 取最后一个（型号通常在商品名称末尾）
            return candidates[-1]

        return ""
