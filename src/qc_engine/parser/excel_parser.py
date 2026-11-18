from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from qc_engine.roles import RoleMapper


# 会话记录 .xlsx 的 31 列表头（按实际文件固定顺序）
EXCEL_COLUMNS = [
    "咨询时间", "咨询类型", "转接后客服", "客服", "顾客", "技能组", "商品编号", "商品名称",
    "新平均响应时间(S)", "首次响应时间", "会话时长(M)", "客户消息数", "客服消息数", "满意度",
    "是否解决", "评价来源", "评价时间", "不满意原因", "非自主率首意图", "非自主率场景",
    "客户二次咨询电商平台的在线标识", "客户二次咨询电商平台的电话标识", "cid", "转接cid",
    "意图1", "意图2", "场景", "是否首次解决", "二次咨询会话ID", "场景化问题", "场景化答案",
]


def normalize_product_id(value: Any) -> str | None:
    """商品编号去掉 Excel 数字格式带来的 .0 尾巴，按字符串返回。"""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "-", "None"):
        return None
    if s.endswith(".0"):
        s = s[:-2]
    return s


class ExcelParser:
    """解析客服魔方导出的「会话记录 .xlsx」（一行一条会话标签，不含聊天正文）。"""

    def __init__(self, role_mapper: RoleMapper, sheet_name: str = "咨询会话查询"):
        self.role_mapper = role_mapper
        self.sheet_name = sheet_name

    def parse(self, path: Path) -> list[dict[str, Any]]:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        if self.sheet_name not in wb.sheetnames:
            raise ValueError(f"工作表 {self.sheet_name} 不存在，实际为 {wb.sheetnames}")
        ws = wb[self.sheet_name]
        rows = ws.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return []
        records: list[dict[str, Any]] = []
        for row in rows:
            record: dict[str, Any] = {}
            for idx, key in enumerate(header):
                value = row[idx] if idx < len(row) else None
                record[str(key).strip()] = value
            # 标准化字段
            record["_product_id"] = normalize_product_id(record.get("商品编号"))
            staff = str(record.get("客服", "")).strip() if record.get("客服") else ""
            record["_agent_id"] = staff
            record["_agent_display"] = self.role_mapper.display_name(staff)
            record["_agent_role"] = self.role_mapper.role_for(staff)
            record["_cid"] = str(record.get("cid", "")).strip() if record.get("cid") else None
            record["_consult_time"] = self._normalize_time(record.get("咨询时间"))
            records.append(record)
        return records

    @staticmethod
    def _normalize_time(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s not in ("", "-", "None") else None
