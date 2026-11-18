# -*- coding: utf-8 -*-
"""爆单一铲 · 全量统计（Text-to-SQL）

思路（保证“全量 + 准确 + 安全”）：
1. 系统先用当前筛选条件拼出一个只读视图 v（筛选正确性由系统保证，模型改不了）；
2. 模型只允许写「外层 SELECT ... FROM v」，不能碰原始表；
3. SQL 经严格校验（单条、只读、表白名单、强制 LIMIT）后执行；
4. 查询结果回灌给模型，由它组织结论——数字全部来自 SQL，不靠模型估算。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import requests

from qc_engine.ai.client import AIClient, _net_err_cn

MAX_ROWS = 300
TABLE_ROWS = 60

FORBIDDEN_KEYWORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "attach", "detach", "pragma", "vacuum", "trigger", "into",
)

CN_HEADERS = {
    "id": "会话ID", "store": "店铺", "agent": "客服", "customer": "客户", "time": "时间",
    "messages": "消息数", "product": "产品", "stage": "阶段", "validity": "有效",
    "lead": "商机", "tele": "电销线索", "score": "分数", "final_status": "最终状态",
    "review_status": "复核状态", "ai_judgment": "智能判定",
}

STAGE_MAP = {"售前": "pre_sale", "售后": "after_sale", "待复核": "needs_review"}
VALID_MAP = {"有效": "valid", "无效": "invalid", "待复核": "needs_review"}


def build_view(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    """按当前筛选生成只读视图 SQL（视图名固定为 v）。"""
    where: list[str] = ["1=1"]
    params: list[Any] = []

    store = str(filters.get("store") or "").strip()
    if store and store != "全部":
        where.append("c.store_id = ?")
        params.append(store)

    agent = str(filters.get("agent") or "").strip()
    if agent and agent != "全部":
        where.append("c.agent_display = ?")
        params.append(agent)

    product = str(filters.get("product") or "").strip()
    if product and product != "全部":
        where.append("json_extract(c.excel_labels_json, '$.model') = ?")
        params.append(product)

    stage = STAGE_MAP.get(str(filters.get("stage") or "").strip())
    if stage:
        where.append("q.service_stage = ?")
        params.append(stage)

    validity = VALID_MAP.get(str(filters.get("validity") or "").strip())
    if validity:
        where.append("q.validity = ?")
        params.append(validity)

    lead = str(filters.get("lead") or "").strip()
    if lead in ("A", "B", "C"):
        where.append("q.lead_level = ?")
        params.append(lead)

    date_start = str(filters.get("date_start") or "").strip()
    date_end = str(filters.get("date_end") or "").strip()
    if date_start:
        where.append("c.first_message_at >= ?")
        params.append(f"{date_start} 00:00:00")
    if date_end:
        where.append("c.first_message_at <= ?")
        params.append(f"{date_end} 23:59:59")

    view_sql = f"""
SELECT c.id AS id,
       c.store_id AS store,
       c.agent_display AS agent,
       c.customer_id AS customer,
       c.first_message_at AS time,
       c.message_count AS messages,
       json_extract(c.excel_labels_json, '$.model') AS product,
       q.service_stage AS stage,
       q.validity AS validity,
       q.lead_level AS lead,
       q.tele_sales_lead AS tele,
       COALESCE(q.final_score, q.calculated_score) AS score,
       q.final_status AS final_status,
       q.review_status AS review_status,
       q.ai_judgment AS ai_judgment
FROM conversations c
LEFT JOIN quality_results q ON q.conversation_id = c.id
WHERE {" AND ".join(where)}
""".strip()
    return view_sql, params


SCHEMA_PROMPT = """你负责把运营的问题翻译成一条 SQLite 查询。

只能查询只读视图 v，字段（英文列名 → 含义）：
- customer 客户名称（引用客户时用这个，不要用 id；id 仅用于去重计数）
- store 店铺；agent 客服；time 时间(YYYY-MM-DD HH:MM:SS)
- messages 消息数；product 产品型号；stage 阶段(pre_sale=售前 / after_sale=售后 / needs_review=待复核)
- validity 有效性(valid / invalid / needs_review)；lead 商机(A / B / C / 空=无)
- tele 电销线索(1/0)；score 分数；final_status 最终状态；review_status 复核状态；ai_judgment 智能判定

硬性规则：
1. 只输出一条 SELECT，必须 FROM v；禁止引用 conversations / quality_results 等原始表；
2. 禁止 INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA 等任何写操作或元操作；
3. 数量用 COUNT(*) 或 COUNT(DISTINCT id)；占比用 ROUND(100.0*SUM(CASE WHEN <条件> THEN 1 ELSE 0 END)/COUNT(*),1)；
4. 时间趋势用 substr(time,1,10)（按天）或 substr(time,1,7)（按月）分组；
5. 结果列请起中文别名（如 AS 会话数、AS 客服），便于展示；
6. 不要输出 markdown 代码块，直接输出 JSON：{"sql": "SELECT ..."}。

示例：
问：A 级商机有多少条？
{"sql": "SELECT COUNT(*) AS 会话数 FROM v WHERE lead = 'A'"}
问：各客服的会话数和平均分排名
{"sql": "SELECT agent AS 客服, COUNT(*) AS 会话数, ROUND(AVG(score),1) AS 平均分 FROM v GROUP BY agent ORDER BY 会话数 DESC"}
问：电销线索占比
{"sql": "SELECT ROUND(100.0*SUM(CASE WHEN tele=1 THEN 1 ELSE 0 END)/COUNT(*),1) AS 电销线索占比 FROM v"}
"""


def _headers(cfg: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {cfg.get('api_key', '')}", "Content-Type": "application/json"}


def _extract_json(text: str) -> dict | None:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(s[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def generate_sql(cfg: dict, question: str, filter_text: str, feedback: str = "") -> str:
    """让模型把问题翻译成 SQL；feedback 用于校验失败后的重试。"""
    user = f"当前筛选：{filter_text or '全部数据'}\n运营的问题：{question}"
    if feedback:
        user += f"\n\n上一次生成的 SQL 不合格（{feedback}），请重新生成，务必满足硬性规则。"
    api_type = str(cfg.get("api_type") or "chat_completions").strip().lower()
    base = str(cfg.get("base_url") or "").rstrip("/")
    model = str(cfg.get("model") or "")
    timeout = int(cfg.get("timeout_seconds") or 60)
    if api_type == "responses":
        url = f"{base}/responses"
        payload = {
            "model": model,
            "temperature": 0,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": SCHEMA_PROMPT}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        }
    else:
        url = f"{base}/chat/completions"
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SCHEMA_PROMPT},
                {"role": "user", "content": user},
            ],
        }
    resp = requests.post(url, headers=_headers(cfg), json=payload, timeout=timeout)
    resp.raise_for_status()
    try:
        text = AIClient._extract_content(resp.json())
    except Exception:
        text = ""
    data = _extract_json(text)
    sql = str((data or {}).get("sql") or "").strip()
    return sql


def validate_sql(sql: str) -> tuple[bool, str]:
    """只读 + 单条 + 只查视图 v + 禁止原始表。"""
    s = (sql or "").strip()
    if not s:
        return False, "未生成 SQL"
    s = re.sub(r"^```(?:sql)?", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    core = s.rstrip(";").strip()
    if ";" in core:
        return False, "只允许一条 SQL 语句"
    low = core.lower()
    if not low.startswith("select"):
        return False, "只允许 SELECT 查询"
    for kw in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{kw}\b", low):
            return False, f"SQL 中包含禁止关键字 {kw}"
    if not re.search(r"\bfrom\s+v\b|\bfrom\s+\(\s*select", low):
        return False, "必须查询视图 v"
    if re.search(r"\b(conversations|quality_results|batches|ai_cache|audit_log)\b", low):
        return False, "不能直接查询原始表"
    return True, ""


def run_sql(db_path: Path, view_sql: str, params: list[Any], sql: str) -> dict[str, Any]:
    core = sql.strip().rstrip(";")
    full = f"WITH v AS ({view_sql}) {core}"
    if "limit" not in core.lower():
        full += f" LIMIT {MAX_ROWS}"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON;")
        cur = conn.execute(full, params)
        columns = [d[0] for d in (cur.description or [])]
        rows = [dict(r) for r in cur.fetchmany(MAX_ROWS)]
    finally:
        conn.close()
    return {"columns": columns, "rows": rows, "count": len(rows)}


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace("|", "\\|").replace("\n", " ")[:60]


def format_table(result: dict[str, Any], max_rows: int = TABLE_ROWS) -> str:
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if not columns:
        return "（查询没有返回列）"
    if not rows:
        return "（查询结果为空）"
    header = "| " + " | ".join(CN_HEADERS.get(c, c) for c in columns) + " |"
    divider = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, divider]
    for row in rows[:max_rows]:
        lines.append("| " + " | ".join(_fmt_cell(row.get(c)) for c in columns) + " |")
    if len(rows) > max_rows:
        lines.append(f"\n（共 {len(rows)} 行，仅展示前 {max_rows} 行）")
    return "\n".join(lines)


def build_answer_messages(question: str, filter_text: str, sql: str, result: dict[str, Any]) -> list[dict[str, str]]:
    table = format_table(result)
    system = (
        "你是「爆单一铲」的数据分析助手。只能基于下面给出的查询结果回答，"
        "数字必须来自结果表，不得编造或估算；结果为空或不足时要明确说明。"
        "回答用中文，用 Markdown 分层：### 结论 / ### 依据 / ### 建议；"
        "引用客户时使用客户名称（不要用会话编号/ID）；"
        "只加粗关键结论、关键数字和动作词，不要整段加粗；每段不超过 3 行；涉及客户话术时用【话术建议】标注。"
    )
    user = (
        f"当前筛选：{filter_text or '全部数据'}\n"
        f"运营的问题：{question}\n\n"
        f"已执行的只读 SQL：\n{sql}\n\n"
        f"查询结果（{result.get('count', 0)} 行）：\n{table}\n\n"
        "请基于以上结果给出结论与建议。"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def net_error_text(exc: Exception) -> str:
    return _net_err_cn(exc)
