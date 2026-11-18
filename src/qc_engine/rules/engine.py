from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from qc_engine.quality.contracts import BusinessDecision, ConversationView


PHONE_RE = re.compile(r"(?<![0-9])1[3-9][0-9*xX＊×]{8}[0-9](?![0-9*xX＊×])")


def phone_hits(text: str) -> bool:
    """识别手机号（含掩码格式，如 159*******5 / 159******45 / 159****1234）。

    先按原文匹配，再把空格、短横线去掉后匹配，兼容「159 1234 5678」「159-1234-5678」。
    """
    t = str(text or "")
    if PHONE_RE.search(t):
        return True
    return PHONE_RE.search(re.sub(r"[\s\-–—]+", "", t)) is not None


@dataclass
class SignalSet:
    after_sale: list[str] = field(default_factory=list)
    presale: list[str] = field(default_factory=list)
    contact: list[str] = field(default_factory=list)
    # A 级信号
    purchase_explicit: list[str] = field(default_factory=list)
    discount: list[str] = field(default_factory=list)
    purchase_soon: list[str] = field(default_factory=list)
    # B 级信号
    comparison: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    # 必问覆盖
    required_questions: dict[str, list[str]] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)

    @property
    def has_contact(self) -> bool:
        return bool(self.contact)


class RuleEngine:
    """确定性业务初筛：售前/售后分流、有效性、A/B/C 商机分级、电销线索、跟进建议。

    所有关键词均来自 rules.yaml，改配置即改规则，代码内不写死关键词。
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

        # 售后关键词
        self.AFTER_SALE = tuple(self.config.get("after_sale_keywords", []))

        # 联系方式
        contact_cfg = self.config.get("contact", {})
        self.CONTACT = tuple(contact_cfg.get("keywords", []))
        phone_regex = contact_cfg.get("phone_regex", r"1[3-9]\d{9}")
        try:
            self.PHONE_RE = re.compile(phone_regex)
        except re.error:
            self.PHONE_RE = PHONE_RE

        # 商机信号（A/B/C 级）
        sig = self.config.get("signals", {})
        sig_a = sig.get("A", {})
        sig_b = sig.get("B", {})
        sig_c = sig.get("C", {})
        self.PURCHASE_EXPLICIT = tuple(sig_a.get("purchase_explicit", []))
        self.DISCOUNT = tuple(sig_a.get("discount", []))
        self.PURCHASE_SOON = tuple(sig_a.get("purchase_time", []))
        self.COMPARISON = tuple(sig_b.get("comparison", []))
        self.PLAN = tuple(sig_b.get("plan", []))
        self.C_CROSS_DAY_ENABLED = bool(sig_c.get("cross_day_enabled", True))
        self.C_MIN_CUSTOMER_MESSAGES = int(sig_c.get("min_customer_messages", 5))

        # 售前必问三组
        self.REQUIRED_QUESTIONS: dict[str, tuple[str, ...]] = {}
        for name, keywords in (self.config.get("required_questions", {}) or {}).items():
            self.REQUIRED_QUESTIONS[name] = tuple(keywords)

        # 售后解决信号
        self.RESOLUTION = tuple(self.config.get("after_sale_resolution_keywords", []))

        # 短会话阈值
        self.short_limit = int(
            self.config.get("conversation", {}).get("invalid_short_conversation", {}).get("max_messages", 5)
        )

    @staticmethod
    def _body(message: dict[str, Any]) -> str:
        return str(message.get("body_text", "")).strip()

    @staticmethod
    def _hits(text: str, keywords: Iterable[str]) -> list[str]:
        return [k for k in keywords if k.lower() in text.lower()]

    def extract_signals(self, conversation: ConversationView) -> SignalSet:
        customer_text = "\n".join(self._body(m) for m in conversation.customer_messages)
        all_text = conversation.normalized_text
        signals = SignalSet()
        signals.after_sale = self._hits(customer_text, self.AFTER_SALE)
        # 联系方式只认客户消息：客服发的售后/服务电话不属于客户留资
        signals.contact = self._hits(customer_text, self.CONTACT)
        if self.PHONE_RE.search(customer_text) or phone_hits(customer_text):
            signals.contact.append("phone_number")
        signals.purchase_explicit = self._hits(customer_text, self.PURCHASE_EXPLICIT)
        signals.discount = self._hits(customer_text, self.DISCOUNT)
        signals.purchase_soon = self._hits(customer_text, self.PURCHASE_SOON)
        signals.comparison = self._hits(customer_text, self.COMPARISON)
        signals.plan = self._hits(customer_text, self.PLAN)
        signals.presale = list(dict.fromkeys([
            *signals.purchase_explicit, *signals.discount, *signals.purchase_soon,
            *signals.comparison, *signals.plan,
        ]))
        for name, keywords in self.REQUIRED_QUESTIONS.items():
            hits = self._hits(customer_text, keywords)
            if hits:
                signals.required_questions[name] = hits
        all_keywords = (self.AFTER_SALE + self.CONTACT + self.PURCHASE_EXPLICIT + self.DISCOUNT
                        + self.PURCHASE_SOON + self.COMPARISON + self.PLAN)
        signals.evidence_refs = [
            f"message:{i + 1}"
            for i, m in enumerate(conversation.messages)
            if self._body(m) and (self._hits(self._body(m), all_keywords) or phone_hits(self._body(m)))
        ]
        return signals

    def route_stage(self, conversation: ConversationView, signals: SignalSet) -> tuple[str, str]:
        if signals.after_sale and not signals.presale:
            return "after_sale", "after_sale_signal"
        if signals.after_sale and signals.presale:
            return "pre_sale", "mixed_stage_first_business_stage"
        if signals.presale:
            return "pre_sale", "presale_signal"
        if conversation.customer_messages:
            return "pre_sale", "default_presale_pending"
        return "needs_review", "no_customer_message"

    def rank_lead(self, signals: SignalSet, conversation: ConversationView, stage: str, validity: str) -> tuple[str | None, list[str]]:
        if stage != "pre_sale":
            return None, []
        reasons: list[str] = []
        if signals.has_contact:
            reasons.append("contact_information")
        if signals.purchase_explicit:
            reasons.append("explicit_purchase_of_our_product")
        if signals.discount:
            reasons.append("discount_or_promotion_intent")
        if signals.purchase_soon:
            reasons.append("purchase_time_soon")
        if reasons:
            return "A", reasons
        if signals.comparison:
            reasons.append("product_comparison")
        if signals.plan:
            reasons.append("purchase_plan_or_repeat_purchase")
        if reasons:
            return "B", reasons
        # C 级：跨天咨询 或 客户消息 ≥ 阈值（围绕参数的长咨询）
        if self.C_CROSS_DAY_ENABLED and self._is_cross_day(conversation):
            return "C", ["cross_day_consultation"]
        if len(conversation.customer_messages) >= self.C_MIN_CUSTOMER_MESSAGES:
            return "C", ["repeated_parameter_questions"]
        return None, []

    def judge_validity(self, conversation: ConversationView, signals: SignalSet, stage: str) -> tuple[str, list[str], list[str]]:
        staff_count = len(conversation.staff_messages)
        evidence = signals.evidence_refs
        if stage == "after_sale":
            if staff_count == 0:
                return "needs_review", ["customer_left_before_after_sale_answer"], evidence
            staff_text = " ".join(self._body(m) for m in conversation.staff_messages)
            if len(conversation.messages) <= 2 and not self._hits(staff_text, self.RESOLUTION):
                return "invalid", ["single_after_sale_question_answered_without_follow_up"], evidence
            if self._hits(staff_text, self.RESOLUTION) or len(staff_text) >= 12:
                return "valid", ["after_sale_resolved_or_transferred"], evidence
            return "needs_review", ["after_sale_resolution_unclear"], evidence

        substantive = any(self._is_substantive_customer(m) for m in conversation.customer_messages)
        explicit = bool(signals.presale or signals.contact)
        if not substantive and not explicit:
            return "invalid", ["no_substantive_customer_consultation"], evidence
        if len(conversation.messages) <= self.short_limit and not explicit:
            return "invalid", ["short_conversation_without_explicit_business_signal"], evidence
        if staff_count == 0 and explicit:
            return "needs_review", ["customer_left_before_agent_answer"], evidence
        reasons = ["substantive_customer_need_answered_or_engaged" if staff_count > 0 else "substantive_customer_need"]
        return "valid", reasons, evidence

    def screen(self, conversation: ConversationView) -> tuple[BusinessDecision, SignalSet]:
        signals = self.extract_signals(conversation)
        stage, stage_reason = self.route_stage(conversation, signals)

        validity, validity_reasons, evidence = self.judge_validity(conversation, signals, stage)

        lead_level, lead_reasons = self.rank_lead(signals, conversation, stage, validity)
        reasons = list(dict.fromkeys([stage_reason, *validity_reasons, *lead_reasons]))

        if stage == "needs_review" or validity == "needs_review":
            suspicious = True
        else:
            # 必问缺失属于确定性扣分项，不再把所有售前会话都放进人工复核队列
            suspicious = False

        advice = self.follow_up_advice(lead_level, signals, validity)
        decision = BusinessDecision(
            service_stage=stage,
            order_status="unknown",
            validity=validity,
            lead_level=lead_level,
            reason_codes=reasons,
            evidence_refs=evidence,
            follow_up_advice=advice,
            tele_sales_lead=signals.has_contact,
            suspicious=suspicious,
        )
        return decision, signals

    @staticmethod
    def _is_cross_day(conversation: ConversationView) -> bool:
        first = conversation.first_message_at
        last = conversation.last_message_at
        if not first or not last:
            return False
        return str(first)[:10] != str(last)[:10]

    @staticmethod
    def _is_substantive_customer(message: dict[str, Any]) -> bool:
        body = str(message.get("body_text", "")).strip()
        if not body or body.startswith("http"):
            return False
        return len(re.sub(r"[\s，。！？,.!?]", "", body)) >= 4

    @staticmethod
    def follow_up_advice(level: str | None, signals: SignalSet, validity: str) -> str:
        if level == "A":
            if signals.has_contact:
                return "标记电销线索，尽快联系客户，确认购买时间、型号和优惠承接。"
            return "尽快主动跟进，确认购买时间、需求与优惠。"
        if level == "B":
            return "建议主动跟进，询问购买时间、对比重点，尝试留下联系方式。"
        if level == "C":
            return "作为培育线索记录，后续结合再次咨询和购买信号适度跟进。"
        if validity == "needs_review":
            return "先由人工确认客户需求和客服是否完成回答。"
        return "暂无明确商机，保留会话记录。"
