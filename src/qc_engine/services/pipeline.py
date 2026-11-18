from __future__ import annotations

import hashlib
from typing import Any

from qc_engine.parser.log_parser import SessionRecord
from qc_engine.quality.contracts import ConversationView
from qc_engine.roles import RoleMapper
from qc_engine.model_matcher import ModelMatcher


def build_conversation(
    session: SessionRecord,
    excel_rec: dict[str, Any] | None,
    store_id: str | None,
    batch_id: str,
    role_mapper: RoleMapper,
    source_sha: str,
    model_matcher: ModelMatcher | None = None,
) -> ConversationView:
    messages: list[dict[str, Any]] = []
    agent_id = None
    agent_display = None
    customer_id = None
    product_ids: set[str] = set()
    log_model = ""  # 聊天记录文本里提到的型号（优先于 Excel 标签型号）
    for i, m in enumerate(session.messages, start=1):
        messages.append({
            "index": i,
            "sender_id": m.sender_id,
            "sender_role": m.sender_role,
            "sent_at": m.sent_at.strftime("%Y-%m-%d %H:%M:%S"),
            "body_text": m.body_text,
            "source_line_start": m.source_line_start,
            "source_line_end": m.source_line_end,
            "message_type": m.message_type,
        })
        if m.sender_role == "agent" and agent_id is None:
            agent_id = m.sender_id
            agent_display = role_mapper.display_name(m.sender_id)
        if m.sender_role == "customer" and customer_id is None:
            customer_id = m.sender_id
        product_ids.update(m.product_ids)
        if not log_model and model_matcher:
            log_model = model_matcher.match(m.body_text)

    conv_id = hashlib.sha256(f"{source_sha}:{session.session_index}".encode("utf-8")).hexdigest()[:24]

    excel_labels: dict[str, Any] = {}
    if excel_rec:
        product_name = excel_rec.get("商品名称")
        excel_model = model_matcher.match(product_name) if model_matcher else ""
        # 型号以聊天记录里提到的为准，聊天没提则用 Excel 标签识别的型号
        final_model = log_model or excel_model
        excel_labels = {
            "product_id": excel_rec.get("_product_id"),
            "product_name": product_name,
            "model": final_model,
            "log_model": log_model,
            "excel_model": excel_model,
            "cid": excel_rec.get("_cid"),
            "consult_type": str(excel_rec.get("咨询类型", "")).strip() if excel_rec.get("咨询类型") else None,
            "skill_group": str(excel_rec.get("技能组", "")).strip() if excel_rec.get("技能组") else None,
            "satisfaction": excel_rec.get("满意度"),
            "resolved": excel_rec.get("是否解决"),
            "customer_name": excel_rec.get("顾客"),
            "intent1": excel_rec.get("意图1"),
            "intent2": excel_rec.get("意图2"),
            "scene": excel_rec.get("场景"),
            "duration": excel_rec.get("会话时长(M)"),
            "customer_msg_count": excel_rec.get("客户消息数"),
            "staff_msg_count": excel_rec.get("客服消息数"),
        }
    elif log_model:
        # 未匹配到 Excel 标签，但聊天里提到了型号，也保留型号
        excel_labels = {"model": log_model, "log_model": log_model, "excel_model": ""}

    return ConversationView(
        conversation_id=conv_id,
        batch_id=batch_id,
        store_id=store_id,
        source_file=session.source_file,
        source_session_index=session.session_index,
        agent_id=agent_id,
        agent_display=agent_display,
        customer_id=customer_id,
        product_ids=sorted(product_ids),
        excel_labels=excel_labels,
        messages=messages,
        first_message_at=session.first_message_at.strftime("%Y-%m-%d %H:%M:%S") if session.first_message_at else None,
        last_message_at=session.last_message_at.strftime("%Y-%m-%d %H:%M:%S") if session.last_message_at else None,
    )
