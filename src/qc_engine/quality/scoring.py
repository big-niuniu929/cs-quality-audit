from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from qc_engine.quality.contracts import BusinessDecision, ConversationView, ScoreResult
from qc_engine.rules.engine import PHONE_RE, RuleEngine, SignalSet, phone_hits


class ScoringEngine:
    """100 分向下扣分评分；只对售前生效，售后只记录不评分。"""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.base_score = int(self.config.get("base_score", 100))
        self.pass_score = int(self.config.get("pass_score", 60))
        # 致命项关键词从 scoring.yaml 读取（fatal_item.terms），不再写死在代码里
        self.fatal_terms = self.config.get("fatal_item", {}).get("terms", {}) or {}

    @staticmethod
    def _dt(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    def response_speed(self, conversation: ConversationView) -> tuple[str, int, dict[str, Any]]:
        first_customer = next(
            (self._dt(m.get("sent_at")) for m in conversation.messages if m.get("sender_role") == "customer"), None
        )
        first_reply = next(
            (
                self._dt(m.get("sent_at"))
                for m in conversation.messages
                if m.get("sender_role") in {"agent", "bot"} and first_customer
                and self._dt(m.get("sent_at")) and self._dt(m.get("sent_at")) >= first_customer
            ),
            None,
        )
        if not first_customer or not first_reply:
            return "needs_review", 0, {"seconds": None, "reason": "response_time_unavailable"}
        seconds = max(0.0, (first_reply - first_customer).total_seconds())
        dim = self.config.get("dimensions", {}).get("response_speed", {})
        thresholds = dim.get("thresholds", {})
        deductions = dim.get("deductions", {})
        if seconds <= float(thresholds.get("excellent_seconds", 20)):
            return "excellent", int(deductions.get("excellent", 0)), {"seconds": seconds}
        if seconds <= float(thresholds.get("good_seconds", 60)):
            return "good", int(deductions.get("good", 2)), {"seconds": seconds}
        if seconds <= float(thresholds.get("qualified_seconds", 180)):
            return "qualified", int(deductions.get("qualified", 5)), {"seconds": seconds}
        return "failed", int(deductions.get("failed", 10)), {"seconds": seconds}

    def required_questions(self, signals: SignalSet) -> tuple[str, int, dict[str, Any]]:
        dim = self.config.get("dimensions", {}).get("presale_required_questions", {})
        count = len(signals.required_questions)
        deductions = dim.get("covered_count_deductions", {})
        deduction = int(deductions.get(count, deductions.get(str(count), 20)))
        return f"covered_{count}", deduction, {"covered_count": count, "groups": signals.required_questions}

    def problem_resolution(self, conversation: ConversationView) -> tuple[str, int, dict[str, Any]]:
        customer_substantive = any(RuleEngine._is_substantive_customer(m) for m in conversation.customer_messages)
        if not customer_substantive:
            return "not_applicable", 0, {"reason": "no_substantive_customer_question"}
        if not conversation.staff_messages:
            return "unresolved", 20, {"reason": "no_agent_answer"}
        return "needs_review", 0, {"reason": "agent_answer_requires_semantic_review"}

    def lead_capture(self, conversation: ConversationView) -> tuple[str, int, dict[str, Any]]:
        dim = self.config.get("dimensions", {}).get("lead_capture", {})
        text = conversation.normalized_text
        if PHONE_RE.search(text) or phone_hits(text):
            return "contact_obtained", 0, {"phone_found": True}
        asked = any(term in text for term in ("留电话", "留个电话", "联系方式", "加微信", "方便联系", "手机号"))
        if asked:
            return "actively_asked_but_refused_or_unclear", 0, {"asked": True}
        return "no_attempt", int(dim.get("deductions", {}).get("no_attempt", 5)), {"asked": False}

    def fatal_candidates(self, conversation: ConversationView) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for index, message in enumerate(conversation.messages, start=1):
            body = str(message.get("body_text", ""))
            if not body or message.get("sender_role") not in {"agent", "bot"}:
                continue
            for code, terms in self.fatal_terms.items():
                hits = [term for term in terms if term in body]
                if hits:
                    found.append({"code": code, "message_ref": f"message:{index}", "hits": hits, "quote": body[:160]})
        return found

    def calculate(self, conversation: ConversationView, decision: BusinessDecision, signals: SignalSet) -> ScoreResult:
        if decision.service_stage != "pre_sale":
            return ScoreResult(
                service_stage=decision.service_stage,
                calculated_score=None,
                final_score=None,
                final_status="after_sale_record_only",
            )
        dimensions: dict[str, Any] = {}
        deductions: dict[str, int] = {}
        suspicious: list[str] = []

        name, value, detail = self.response_speed(conversation)
        dimensions["response_speed"] = {"status": name, **detail}
        deductions["response_speed"] = value
        if name == "needs_review":
            suspicious.append("response_speed_uncertain")

        name, value, detail = self.required_questions(signals)
        dimensions["presale_required_questions"] = {"status": name, **detail}
        deductions["presale_required_questions"] = value
        if detail["covered_count"] < 3:
            suspicious.append("missing_presale_required_question")

        name, value, detail = self.problem_resolution(conversation)
        dimensions["problem_resolution"] = {"status": name, **detail}
        deductions["problem_resolution"] = value
        if name in {"needs_review", "unresolved"}:
            suspicious.append("problem_resolution_requires_review")

        name, value, detail = self.lead_capture(conversation)
        dimensions["lead_capture"] = {"status": name, **detail}
        deductions["lead_capture"] = value

        fatal = self.fatal_candidates(conversation)
        if fatal:
            suspicious.append("fatal_candidate")

        calculated = max(0, min(self.base_score, self.base_score - sum(deductions.values())))
        final_status = "needs_review" if suspicious or decision.validity == "needs_review" else ("合格" if calculated >= self.pass_score else "不合格")
        return ScoreResult(
            service_stage=decision.service_stage,
            calculated_score=calculated,
            final_score=calculated,
            final_status=final_status,
            dimensions=dimensions,
            deductions=deductions,
            fatal_candidates=fatal,
            suspicious_reasons=list(dict.fromkeys(suspicious)),
        )
