from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ConversationView:
    """一段会话的完整视图：聊天正文 + Excel 标签 + 店铺/角色摘要。"""

    conversation_id: str
    batch_id: str
    store_id: str | None
    source_file: str
    source_session_index: int
    agent_id: str | None
    agent_display: str | None
    customer_id: str | None
    product_ids: list[str] = field(default_factory=list)
    excel_labels: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    first_message_at: str | None = None
    last_message_at: str | None = None
    match_state: str | None = None

    @property
    def normalized_text(self) -> str:
        return "\n".join(str(m.get("body_text", "")) for m in self.messages).strip()

    @property
    def customer_messages(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("sender_role") == "customer"]

    @property
    def staff_messages(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("sender_role") == "agent"]

    @property
    def bot_messages(self) -> list[dict[str, Any]]:
        return [m for m in self.messages if m.get("sender_role") == "bot"]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BusinessDecision:
    service_stage: str                    # pre_sale / after_sale / needs_review
    order_status: str                     # unknown / purchased / not_purchased
    validity: str                         # valid / invalid / needs_review
    lead_level: str | None                # A / B / C / None
    reason_codes: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    follow_up_advice: str = ""
    tele_sales_lead: bool = False
    special_reason: str | None = None     # 如「内部闲聊」
    suspicious: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreResult:
    service_stage: str
    calculated_score: int | None
    final_score: int | None
    final_status: str
    dimensions: dict[str, Any] = field(default_factory=dict)
    deductions: dict[str, int] = field(default_factory=dict)
    fatal_candidates: list[dict[str, Any]] = field(default_factory=list)
    suspicious_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
