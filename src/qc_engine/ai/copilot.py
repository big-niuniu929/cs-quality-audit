# -*- coding: utf-8 -*-
"""「爆单一铲」AI 质检副驾：会话摘要上下文 + 流式回答。

设计要点（与产品约定一致）：
- 不把全量原文塞给模型：本模块只负责把「当前筛选范围内的会话」压成结构化摘要卡片；
- 单次请求有上限（默认 200 条，按 A 级优先 + 时间倒序截断），并在系统提示词中明示；
- 全量统计类问题交给后续的 SQL 工具（第三步），这里不承担。
"""
from __future__ import annotations

import html
import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import requests

from qc_engine.ai.client import API_TYPE_CN, _net_err_cn

DEFAULT_MAX_ITEMS = 200
MAX_QUOTE_CHARS = 60


# ---------------- 摘要构建 ----------------

def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _clean(text: Any) -> str:
    s = str(text or "")
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]*>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _short(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    s = text.strip().replace('"', "“")
    return s if len(s) <= limit else s[:limit] + "…"


def _first_response_seconds(messages: Iterable[dict]) -> str:
    first_customer = None
    for m in messages:
        if m.get("sender_role") == "customer":
            first_customer = _parse_dt(m.get("sent_at"))
            if first_customer:
                break
    if not first_customer:
        return "-"
    for m in messages:
        if m.get("sender_role") in ("agent", "bot"):
            t = _parse_dt(m.get("sent_at"))
            if t and t >= first_customer:
                return f"{int(max(0.0, (t - first_customer).total_seconds()))}s"
    return "-"


def _customer_key_sentence(messages: list[dict]) -> str:
    candidates = [_clean(m.get("body_text")) for m in messages if m.get("sender_role") == "customer"]
    candidates = [c for c in candidates if c and not c.startswith("http")]
    if not candidates:
        return "-"
    return _short(max(candidates, key=len))


def _agent_last_sentence(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("sender_role") in ("agent", "bot"):
            text = _clean(m.get("body_text"))
            if text:
                return _short(text)
    return "-"


def _product_label(row: dict) -> str:
    labels = row.get("excel_labels") or {}
    model = str(labels.get("model") or "").strip()
    if model:
        return model
    name = str(labels.get("product_name") or "").strip()
    return _short(name, 24) if name else "-"


def customer_label(row: dict) -> str:
    """客户显示名：优先 Excel「顾客」昵称，其次客户账号，最后「客户」。"""
    name = str((row.get("excel_labels") or {}).get("customer_name") or "").strip()
    if name:
        return name
    cid = str(row.get("customer") or "").strip()
    return cid or "客户"


def summary_line(row: dict) -> str:
    messages = row.get("messages") or []
    stage = {"pre_sale": "售前", "after_sale": "售后", "needs_review": "待复核"}.get(str(row.get("service_stage")), "-")
    validity = {"valid": "有效", "invalid": "无效", "needs_review": "待复核"}.get(str(row.get("validity")), "-")
    return (
        f"客户:{customer_label(row)} | 客服:{row.get('agent') or '-'} | 产品:{_product_label(row)} | 阶段:{stage} | "
        f"商机:{row.get('lead_level') or '-'} | 有效性:{validity} | "
        f"首响:{_first_response_seconds(messages)} | 消息数:{len(messages)} | "
        f"客户关键句:\"{_customer_key_sentence(messages)}\" | 客服末句:\"{_agent_last_sentence(messages)}\""
    )


def build_context(rows: list[dict], max_items: int = DEFAULT_MAX_ITEMS) -> dict[str, Any]:
    """把筛选后的会话压成摘要文本。

    排序：A 级优先，其次按首次消息时间倒序；超出上限的记录只计数不注入。
    """
    def rank(row: dict):
        lead = str(row.get("lead_level") or "")
        return (0 if lead == "A" else 1, -(_parse_dt(row.get("first_message_at")) or datetime.min).timestamp())

    ordered = sorted(rows, key=rank)
    selected = ordered[:max_items]
    lines = [summary_line(r) for r in selected]
    return {
        "text": "\n".join(lines),
        "included": len(selected),
        "total": len(rows),
        "truncated": max(0, len(rows) - len(selected)),
    }


def build_system_prompt(context: dict[str, Any], filter_text: str) -> str:
    included = context["included"]
    total = context["total"]
    truncated = context["truncated"]
    note = (
        f"仅展示筛选范围内的前 {included} 条会话摘要（筛选结果共 {total} 条）"
        + (f"，另有 {truncated} 条未注入，如需更多请缩小筛选范围" if truncated else "")
        + "；请基于这些摘要回答，不要假装看过未注入的会话。"
    )
    return (
        "你是「爆单一铲」——品牌A 资深电商销售导师与客服质检副驾。\n"
        "严格基于注入的会话摘要作答，不得编造未出现的客户信息；需要输出话术时，请标注【话术建议】。\n\n"
        f"当前筛选：{filter_text or '未筛选（全部数据）'}\n"
        f"【上下文说明】{note}\n\n"
        f"【会话摘要】\n{context['text'] or '（当前筛选没有会话）'}\n\n"
        "【回答要求】\n"
        "1. 先给结论，再给依据；依据请引用客户名称（如「王女士」）或客服名，不要使用 conv0001 这类会话编号；\n"
        "2. 若问题涉及数量/占比/排名等统计，请说明需要统计口径（系统可用 SQL 精确统计），不要凭摘要估算；\n"
        "3. 话术必须可直接发给客户，口语化、不套路、不超过 80 字；\n"
        "4. 摘要不足以回答时，明确说明还缺什么信息，不要编造；\n"
        "5. 排版：用 Markdown 分层——先「### 结论」再「### 依据」再「### 建议」；"
        "只加粗关键结论、关键数字和动作词（每段最多 1~2 处），不要整段加粗；每段不超过 3 行，多用短列表。"
    )


# ---------------- 历史对话持久化 ----------------

def load_history(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(path: Path, items: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items[-60:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------- 流式请求 ----------------

STREAM_TIMEOUT = 120


class CopilotAgent:
    """复用公司 OpenAI 兼容接口；对话接口走 SSE 流式，响应接口退化为一次性返回。"""

    def __init__(self, cfg: dict[str, Any]):
        self.base_url = str(cfg.get("base_url") or "").rstrip("/")
        self.model = str(cfg.get("model") or "")
        self.api_key = str(cfg.get("api_key") or "")
        self.api_type = str(cfg.get("api_type") or "chat_completions").strip().lower()
        self.timeout = int(cfg.get("timeout_seconds") or STREAM_TIMEOUT)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def complete(self, messages: list[dict[str, str]]) -> str:
        """非流式一次性返回，用于分批提炼（map 阶段）。"""
        if self.api_type == "responses":
            return self._call_responses(messages)
        return self._call_chat_once(messages)

    def stream(
        self,
        messages: list[dict[str, str]],
        on_delta: Callable[[str], None],
        should_stop: Callable[[], bool],
    ) -> str:
        if self.api_type == "responses":
            text = self._call_responses(messages)
            if text:
                on_delta(text)
            return text
        return self._stream_chat(messages, on_delta, should_stop)

    def _stream_chat(
        self,
        messages: list[dict[str, str]],
        on_delta: Callable[[str], None],
        should_stop: Callable[[], bool],
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.3,
            "stream": True,
        }
        chunks: list[str] = []
        with requests.post(url, headers=self._headers(), json=payload, stream=True, timeout=self.timeout) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines(decode_unicode=False):
                if should_stop():
                    break
                if not raw:
                    continue
                line = raw.decode("utf-8", "ignore").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = obj["choices"][0]["delta"].get("content") or ""
                except (KeyError, IndexError, TypeError):
                    delta = ""
                if delta:
                    chunks.append(delta)
                    on_delta(delta)
        if not chunks:
            # 网关不支持 SSE（或返回了非流式 JSON）时回退为一次性请求
            text = self._call_chat_once(messages)
            if text:
                on_delta(text)
            return text
        return "".join(chunks)

    def _call_chat_once(self, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = {"model": self.model, "messages": messages, "temperature": 0.3, "stream": False}
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        try:
            return resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""

    def _call_responses(self, messages: list[dict[str, str]]) -> str:
        """响应接口暂不支持 SSE：一次性取回后整体输出。"""
        url = f"{self.base_url}/responses"
        system_text = "\n".join(m["content"] for m in messages if m.get("role") == "system")
        user_text = "\n\n".join(m["content"] for m in messages if m.get("role") == "user")
        payload = {
            "model": self.model,
            "temperature": 0.3,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_text}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_text}]},
            ],
        }
        resp = requests.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        texts = []
        for item in data.get("output", []) or []:
            if isinstance(item, dict):
                for c in item.get("content", []) or []:
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        texts.append(c.get("text", ""))
        return "\n".join(texts)


def net_error_text(exc: Exception) -> str:
    """把网络异常翻译成中文，避免界面出现英文异常名。"""
    return _net_err_cn(exc)


# ---------------- 全量分批分析（map-reduce） ----------------

BATCH_CARDS = 120

MAP_SYSTEM = (
    "你是「爆单一铲」的会话分析助手。下面给你的是本批会话摘要卡片。"
    "只基于这些卡片作答，严禁编造未出现的客户信息；引用时请用客户名称（如「王女士」），不要使用会话编号。"
    "输出本批的关键发现：共性问题、典型案例、客服做得好的点；"
    "与本批无关或没有内容时输出「本批无」。不超过 320 字，不要输出标题以外的客套话。"
)

REDUCE_SYSTEM = (
    "你是「爆单一铲」——品牌A 资深电商销售导师。下面是全部批次的发现汇总，"
    "请合并去重、归纳成一份最终报告。只基于这些发现作答，不得编造；"
    "结论要引用具体客户名称（不要用会话编号）；需要给话术时标注【话术建议】；"
    "排版用 Markdown 分层：### 结论 / ### 依据 / ### 建议，只加粗关键结论、数字和动作词，每段不超过 3 行；"
    "最后说明本次覆盖了多少条会话、分了几批，以及还有哪些信息不足。"
)


def build_map_messages(question: str, payload: str, batch_index: int, batch_total: int,
                       mode: str = "card") -> list[dict[str, str]]:
    system = MAP_SYSTEM_FULL if mode == "full" else MAP_SYSTEM
    label = "完整会话记录" if mode == "full" else "会话摘要卡片"
    user = (
        f"运营的问题：{question}\n\n"
        f"这是第 {batch_index}/{batch_total} 批{label}：\n{payload}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_reduce_messages(question: str, filter_text: str, findings_text: str,
                          covered: int, batches: int) -> list[dict[str, str]]:
    user = (
        f"当前数据范围：{filter_text or '全部数据'}\n"
        f"运营的问题：{question}\n\n"
        f"本次已分析 {covered} 条会话，分 {batches} 批，以下是各批发现：\n\n"
        f"{findings_text}\n\n"
        "请输出最终报告。"
    )
    return [{"role": "system", "content": REDUCE_SYSTEM}, {"role": "user", "content": user}]



# ---------------- 全文精读（full 模式） ----------------

ROLE_LABELS = {"customer": "客户", "agent": "客服", "system": "系统", "staff": "客服"}

MAP_SYSTEM_FULL = (
    "你是「爆单一铲」的会话分析助手。下面给你的是若干条**完整会话记录**（客户与客服的全部消息）。"
    "只基于这些原文作答，严禁编造；引用时使用客户名称（如「王女士」），不要使用会话编号。"
    "重点找出与问题直接相关的证据：把关键原句用引号摘出来（例如客户说「加我微信 130*******8」）；"
    "若本批没有相关内容，输出「本批无」。不超过 400 字。"
)


def conversation_text(row: dict, max_chars: int = 6000) -> str:
    """把一条会话渲染成全文（含全部消息），用于全文精读模式。"""
    header = (
        f"客户:{customer_label(row)} | 客服:{row.get('agent') or '-'} | "
        f"阶段:{row.get('service_stage') or '-'} | 商机:{row.get('lead_level') or '-'} | "
        f"有效性:{row.get('validity') or '-'} | 首条时间:{row.get('first_message_at') or ''}"
    )
    lines = [header]
    for message in row.get("messages") or []:
        who = ROLE_LABELS.get(str(message.get("sender_role") or ""), "客户")
        body = str(message.get("body_text") or "").replace("\n", " ").strip()
        if body:
            lines.append(f"{who}: {body}")
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[:max_chars] + "…（后略）"
    return text


def batch_texts(texts: list[str], max_chars: int = 22000) -> list[str]:
    """按字符上限把多条会话全文切成若干批，保证单批不会过大。"""
    batches: list[str] = []
    current: list[str] = []
    size = 0
    for text in texts:
        if current and size + len(text) + 2 > max_chars:
            batches.append("\n\n".join(current))
            current, size = [], 0
        current.append(text)
        size += len(text) + 2
    if current:
        batches.append("\n\n".join(current))
    return batches
