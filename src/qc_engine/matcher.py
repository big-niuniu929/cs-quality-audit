from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from qc_engine.parser.log_parser import SessionRecord
from qc_engine.roles import RoleMapper


class Matcher:
    """LOG 会话与 Excel 会话标签的匹配诊断。

    主匹配键：客服（去前缀）+ 会话时间（容差内）。
    商品编号只作为「一致性校验」信息（log 里客户常不贴商品链接，不能当硬条件）。

    匹配不上保留独立记录，不强行合并。
    """

    def __init__(self, role_mapper: RoleMapper, time_tolerance_seconds: int = 600):
        self.role_mapper = role_mapper
        self.tolerance = timedelta(seconds=time_tolerance_seconds)

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.strptime(str(value).strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def _session_agent(self, session: SessionRecord) -> str | None:
        for m in session.messages:
            if m.sender_role == "agent":
                return self.role_mapper.display_name(m.sender_id)
        return None

    def diagnose(self, sessions: list[SessionRecord], records: list[dict[str, Any]]) -> dict[str, Any]:
        log_entries: list[dict[str, Any]] = []
        agent_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for idx, s in enumerate(sessions):
            products: set[str] = set()
            for m in s.messages:
                products.update(m.product_ids)
            entry = {
                "index": idx,
                "session": s,
                "agent": self._session_agent(s),
                "products": products,
                "first_time": s.first_message_at,
            }
            log_entries.append(entry)
            if entry["agent"]:
                agent_buckets[entry["agent"]].append(entry)

        matched: list[dict[str, Any]] = []
        unmatched_excel: list[dict[str, Any]] = []
        matched_log_idx: set[int] = set()

        for rec in records:
            agent = rec.get("_agent_display")
            consult = self._parse_time(rec.get("_consult_time"))
            product = rec.get("_product_id")

            best = None
            best_diff: float | None = None
            for entry in agent_buckets.get(agent, []):
                if entry["index"] in matched_log_idx:
                    continue
                first = entry["first_time"]
                if not first or not consult:
                    continue
                diff = abs((first - consult).total_seconds())
                if diff <= self.tolerance.total_seconds() and (best_diff is None or diff < best_diff):
                    best = entry
                    best_diff = diff

            if best is not None:
                if product is None:
                    product_state = "excel_missing_product"
                elif best["products"] and product not in best["products"]:
                    product_state = "product_mismatch"
                elif product in best["products"]:
                    product_state = "product_match"
                else:
                    product_state = "log_missing_product"
                matched.append({
                    "excel": rec,
                    "log": best,
                    "time_diff_seconds": best_diff,
                    "product_state": product_state,
                })
                matched_log_idx.add(best["index"])
            else:
                unmatched_excel.append({"excel": rec})

        unmatched_log = [entry for entry in log_entries if entry["index"] not in matched_log_idx]

        # 商品一致性分布
        product_dist: dict[str, int] = defaultdict(int)
        for item in matched:
            product_dist[item["product_state"]] += 1

        return {
            "log_session_count": len(sessions),
            "excel_record_count": len(records),
            "matched": len(matched),
            "unmatched_excel": len(unmatched_excel),
            "unmatched_log": len(unmatched_log),
            "product_distribution": dict(product_dist),
            "matched_records": matched,
            "unmatched_excel_records": unmatched_excel,
            "unmatched_log_entries": unmatched_log,
        }
