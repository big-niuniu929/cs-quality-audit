# -*- coding: utf-8 -*-
"""客服质检评分引擎 v2.0.0（6 维 / 四档制）。

- 每个维度按配置档位给分（优秀/良好/合格/不合格，优惠触达为 2 档）；
- 规则维度直接出分；AI 维度在 AI 质检完成前标记 ai_pending，不参与总分；
- 总分 = 已出分维度之和；AI 维度全部完成后才是最终分；
- 两个角色看板共用同一结果。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from qc_engine.quality.contracts import BusinessDecision, ConversationView, ScoreResult
from qc_engine.rules.engine import PHONE_RE, RuleEngine, SignalSet, phone_hits

DIM_ORDER = [
    "response_speed",
    "presale_required_questions",
    "phrase_match",
    "problem_resolution",
    "lead_capture",
    "promotion_touch",
]
DIM_CN = {
    "response_speed": "响应速度",
    "presale_required_questions": "售前必问",
    "phrase_match": "话术匹配度",
    "problem_resolution": "问题解决",
    "lead_capture": "引导留资",
    "promotion_touch": "优惠触达",
}
TIER_ORDER = ["excellent", "good", "qualified", "fail"]


class ScoringEngine:
    """按维度档位给分的质检评分引擎。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.base_score = int(self.config.get("base_score", 100))
        self.pass_score = int(self.config.get("pass_score", 60))
        self.rating_bands = self.config.get("rating_bands") or [
            {"min": 90, "label": "优秀"}, {"min": 75, "label": "良好"},
            {"min": 60, "label": "合格"}, {"min": 0, "label": "不合格"},
        ]
        self.tier_labels = self.config.get("tier_labels") or {
            "excellent": "优秀", "good": "良好", "qualified": "合格", "fail": "不合格",
        }
        self.dimension_cfg: dict[str, Any] = self.config.get("dimensions", {}) or {}
        self.fatal_terms = self.config.get("fatal_item", {}).get("terms", {}) or {}

    # ---------------- 通用 ----------------
    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    def rating(self, score: int | float | None) -> str:
        if score is None:
            return "待AI质检"
        for band in self.rating_bands:
            try:
                if float(score) >= float(band.get("min", 0)):
                    return str(band.get("label", ""))
            except (TypeError, ValueError):
                continue
        return "不合格"

    def _first_response(self, conversation: ConversationView) -> tuple[float | None, str | None]:
        first_customer = next(
            (self._dt(m.get("sent_at")) for m in conversation.messages
             if m.get("sender_role") == "customer"), None)
        if not first_customer:
            return None, "无客户消息"
        first_reply = next(
            (self._dt(m.get("sent_at")) for m in conversation.messages
             if m.get("sender_role") in {"agent", "bot"} and self._dt(m.get("sent_at"))
             and self._dt(m.get("sent_at")) >= first_customer), None)
        if not first_reply:
            return None, "无客服回复"
        return max(0.0, (first_reply - first_customer).total_seconds()), None

    def _agent_text(self, conversation: ConversationView) -> str:
        return "\n".join(str(m.get("body_text", "")) for m in conversation.staff_messages)

    def _customer_text(self, conversation: ConversationView) -> str:
        return "\n".join(str(m.get("body_text", "")) for m in conversation.customer_messages)

    # ---------------- 规则维度 ----------------
    def _tier_response(self, conversation: ConversationView) -> tuple[str, dict[str, Any]]:
        levels = self.dimension_cfg.get("response_speed", {}).get("levels", {}) or {}
        seconds, reason = self._first_response(conversation)
        if seconds is None:
            return "fail", {"seconds": None, "reason": reason}
        for tier in ("excellent", "good", "qualified"):
            limit = levels.get(tier, {}).get("max_seconds")
            if limit is not None and seconds <= float(limit):
                return tier, {"seconds": round(seconds, 1)}
        return "fail", {"seconds": round(seconds, 1)}

    def _tier_required(self, conversation: ConversationView) -> tuple[str, dict[str, Any]]:
        cfg = self.dimension_cfg.get("presale_required_questions", {}) or {}
        groups = cfg.get("groups", {}) or {}
        agent_text = self._agent_text(conversation)
        covered = []
        for name, terms in groups.items():
            if any(str(t) in agent_text for t in (terms or [])):
                covered.append(name)
        levels = cfg.get("levels", {}) or {}
        count = len(covered)
        tier = "fail"
        for t in ("excellent", "good", "qualified"):
            need = levels.get(t, {}).get("min_groups")
            if need is not None and count >= int(need):
                tier = t
                break
        return tier, {"covered_groups": covered, "covered_count": count}

    def _tier_lead(self, conversation: ConversationView) -> tuple[str, dict[str, Any]]:
        cfg = self.dimension_cfg.get("lead_capture", {}) or {}
        customer_text = self._customer_text(conversation)
        agent_text = self._agent_text(conversation)
        # 客户留下电话/微信等联系方式 → 满分
        contact = bool(PHONE_RE.search(customer_text) or phone_hits(customer_text))
        if not contact:
            contact = bool(re.search(r"(微信|wechat|qq|邮箱)[:：]?\s*[A-Za-z0-9_\-]{3,}", customer_text, re.I))
        if contact:
            return "excellent", {"contact_obtained": True}
        guide_terms = [str(t) for t in (cfg.get("guide_terms") or [])]
        aware_terms = [str(t) for t in (cfg.get("aware_terms") or [])]
        if any(t in agent_text for t in guide_terms):
            return "good", {"contact_obtained": False, "guide": True}
        if any(t in agent_text for t in aware_terms):
            return "qualified", {"contact_obtained": False, "aware": True}
        return "fail", {"contact_obtained": False}

    def _tier_promo(self, conversation: ConversationView) -> tuple[str, dict[str, Any]]:
        cfg = self.dimension_cfg.get("promotion_touch", {}) or {}
        terms = [str(t) for t in (cfg.get("terms") or [])]
        text = self._agent_text(conversation)
        hits = [t for t in terms if t in text]
        return ("excellent" if hits else "fail"), {"hits": hits}

    def _rule_tier(self, code: str, conversation: ConversationView) -> tuple[str, dict[str, Any]]:
        if code == "response_speed":
            return self._tier_response(conversation)
        if code == "presale_required_questions":
            return self._tier_required(conversation)
        if code == "lead_capture":
            return self._tier_lead(conversation)
        if code == "promotion_touch":
            return self._tier_promo(conversation)
        return "fail", {"reason": "unknown_rule_dimension"}

    def fatal_candidates(self, conversation: ConversationView) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for index, message in enumerate(conversation.messages, start=1):
            body = str(message.get("body_text", ""))
            if not body or message.get("sender_role") not in {"agent", "bot"}:
                continue
            for code, terms in self.fatal_terms.items():
                hits = [term for term in terms if term in body]
                if hits:
                    found.append({"code": code, "message_ref": f"message:{index}",
                                  "hits": hits, "quote": body[:160]})
        return found

    # ---------------- 主计算 ----------------
    def calculate(self, conversation: ConversationView, decision: BusinessDecision,
                  signals: SignalSet, ai_judgment: str | None = None,
                  ai_status: str | None = None) -> ScoreResult:
        if decision.service_stage != "pre_sale":
            return ScoreResult(
                service_stage=decision.service_stage,
                calculated_score=None, final_score=None,
                final_status="after_sale_record_only",
            )

        dimensions: dict[str, Any] = {}
        deductions: dict[str, Any] = {}
        total_score = 0.0
        pending = False
        fatal = self.fatal_candidates(conversation)

        for code in DIM_ORDER:
            cfg = self.dimension_cfg.get(code) or {}
            total = float(cfg.get("total", 0) or 0)
            mode = str(cfg.get("mode", "rule"))
            levels = cfg.get("levels", {}) or {}
            label = cfg.get("label") or DIM_CN.get(code, code)
            entry: dict[str, Any] = {"mode": mode, "total": total, "label": label}
            tier: str | None = None
            detail: dict[str, Any] = {}
            if mode == "ai":
                mapped = (cfg.get("ai_map") or {}).get(str(ai_judgment or ""))
                if str(ai_status or "") == "done" and mapped:
                    tier = str(mapped)
                    detail = {"ai_judgment": ai_judgment, "ai_status": ai_status}
                else:
                    entry.update({"status": "ai_pending", "tier": None, "tier_label": "待AI",
                                  "points": None, "score": None, "score_ratio": None,
                                  "deduct": None, "detail": {}})
                    dimensions[code] = entry
                    pending = True
                    continue
            else:
                tier, detail = self._rule_tier(code, conversation)

            level = levels.get(tier) or {}
            points = float(level.get("points", 0) or 0)
            score_ratio = round(points / total, 3) if total else 0
            entry.update({
                "status": "scored",
                "tier": tier,
                "tier_label": self.tier_labels.get(tier, tier),
                "points": points,
                "score": points,
                "score_ratio": score_ratio,
                "deduct": round(total - points, 1),
                "detail": detail,
            })
            dimensions[code] = entry
            deductions[code] = round(total - points, 1)
            total_score += points

        total_score = round(total_score, 1)
        if pending:
            final_status = "ai_pending"
        else:
            final_status = "合格" if total_score >= self.pass_score else "不合格"
        return ScoreResult(
            service_stage=decision.service_stage,
            calculated_score=total_score,
            final_score=total_score,
            final_status=final_status,
            dimensions=dimensions,
            deductions=deductions,
            fatal_candidates=fatal,
            suspicious_reasons=(["fatal_candidate"] if fatal else []),
        )
