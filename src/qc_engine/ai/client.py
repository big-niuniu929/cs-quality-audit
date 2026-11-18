from __future__ import annotations

import hashlib
import json
from typing import Any

import requests

from qc_engine.storage.database import Database

API_TYPE_CN = {"chat_completions": "对话接口", "responses": "响应接口"}
NET_ERR_CN = {
    "ConnectionError": "无法连接服务器，请检查接口地址与网络",
    "ConnectTimeout": "连接超时，请检查接口地址与网络",
    "Timeout": "请求超时，请稍后重试",
    "HTTPError": "接口返回错误状态，请检查地址、模型与密钥",
    "JSONDecodeError": "接口返回内容不是有效数据",
    "SSLError": "证书校验失败",
    "MissingSchema": "接口地址缺少 http 或 https 前缀",
    "InvalidURL": "接口地址格式不正确",
    "InvalidSchema": "接口地址前缀不正确",
}


def _net_err_cn(exc: Exception) -> str:
    """把网络/接口异常翻译成中文，不把英文异常名直接抛给用户。"""
    node: Exception | None = exc
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        name = type(node).__name__
        if name in NET_ERR_CN:
            return NET_ERR_CN[name]
        nxt = node.__cause__ or node.__context__
        node = nxt if isinstance(nxt, Exception) else None
    return "调用失败，请检查接口配置后重试"


class AIClient:
    """OpenAI 兼容协议客户端（公司入口 token.公司内网.com/v1）。

    - 逐会话质检：返回带 evidence 的严格 JSON，失败/证据缺失 → needs_review
    - 批量总结：自然语言结论
    - 结果按内容哈希缓存到 SQLite
    - API Key 只从 UI/配置文件读取，不写入代码与日志
    """

    def __init__(self, config: dict[str, Any], database: Database | None = None):
        self.base_url = str(config.get("base_url", "")).rstrip("/")
        self.model = str(config.get("model", ""))
        self.api_key = str(config.get("api_key", ""))
        self.timeout = int(config.get("timeout_seconds", 60))
        self.api_type = str(config.get("api_type", "chat_completions")).strip().lower()
        self.max_retries = int(config.get("max_retries", 2))
        self.database = database

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    @property
    def _endpoint(self) -> str:
        if self.api_type == "responses":
            return f"{self.base_url}/responses"
        return f"{self.base_url}/chat/completions"

    def _post_json(self, body: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
        """按 api_type 调用对应端点，带重试。返回解析后的响应 JSON。"""
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(self._endpoint, headers=self._headers(),
                                     json=body, timeout=timeout or self.timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
        raise last_exc if last_exc else RuntimeError("未知错误")

    def test_connection(self) -> tuple[bool, str]:
        if not self.configured:
            return False, "请先填写接口地址、模型和密钥"
        try:
            if self.api_type == "responses":
                body = {"model": self.model, "input": "回复OK", "max_output_tokens": 5}
            else:
                body = {"model": self.model, "messages": [{"role": "user", "content": "回复OK"}], "max_tokens": 5}
            self._post_json(body, timeout=15)
            return True, f"连接成功（模型 {self.model}，协议 {API_TYPE_CN.get(self.api_type, self.api_type)}）"
        except Exception as exc:
            return False, f"连接失败：{_net_err_cn(exc)}"

    @staticmethod
    def _extract_content(resp_json: dict[str, Any]) -> str:
        """从 Responses 或 Chat Completions 响应里提取文本内容。"""
        # Responses API
        output = resp_json.get("output")
        if isinstance(output, list):
            texts = []
            for item in output:
                if isinstance(item, dict):
                    for c in item.get("content", []):
                        if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                            texts.append(c.get("text", ""))
            if texts:
                return "\n".join(texts)
        # Chat Completions
        try:
            return resp_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            pass
        return ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    # ---- 逐会话质检 ----

    JUDGE_PROMPT = (
        "你是客服质检判定器。只能基于给出的聊天原文判断，返回 JSON（不要 Markdown）。\n"
        "字段：judgment(pass|fail|needs_review)、reason(简短中文说明)、\n"
        "suggestion(结合本段聊天上下文，给出客服服务/话术/产品推荐/成单推进等方面的具体改进建议，并附一句可以直接发给客户的口语化话术；不只写跟进动作，总长不超过 80 字，不要套模板)、\n"
        "evidence(数组，每项含 message_ref 如 'message:3' 与 quote 原文短引用)。\n"
        "stage_suggestion(pre_sale|after_sale|keep)：如果你认为规则判定的售前/售后阶段有误，给出建议值，否则 keep；\n"
        "validity_suggestion(valid|invalid|keep)：如果你认为规则判定的有效/无效有误，给出建议值，否则 keep；\n"
        "suggestion_reason：建议改判的简短依据（没有改判建议则留空）。只有证据明确时才建议改判，禁止猜测。\n"
        "无法确定就用 needs_review，禁止编造原文没有的内容。"
    )

    def judge_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        cache_key = self._cache_key(payload)
        if self.database:
            cached = self.database.get_ai_cache(cache_key)
            if cached:
                data = json.loads(cached)
                data["from_cache"] = True
                return data
        if not self.configured:
            return {"status": "not_configured", "judgment": "needs_review", "reason": "未配置 AI", "suggestion": "", "evidence": []}
        result = self._call_json(payload)
        if self.database and result.get("status") == "done":
            self.database.set_ai_cache(cache_key, payload.get("conversation_id", ""), json.dumps(result, ensure_ascii=False))
        return result

    def _call_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.api_type == "responses":
            body = {
                "model": self.model,
                "temperature": 0,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": self.JUDGE_PROMPT}]},
                    {"role": "user", "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}]},
                ],
            }
        else:
            body = {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": self.JUDGE_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
            }
        try:
            resp_json = self._post_json(body)
            content = self._extract_content(resp_json)
            if isinstance(content, str):
                content = json.loads(content)
            return self._validate(content)
        except Exception as exc:
            return {"status": "failed", "judgment": "needs_review",
                    "reason": "AI 调用失败，请稍后重试或检查接口配置", "suggestion": "转人工复核", "evidence": []}

    @staticmethod
    def _validate(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get("judgment") not in {"pass", "fail", "needs_review"}:
            raise ValueError("AI 返回结构不合法")
        evidence = value.get("evidence") or []
        if not isinstance(evidence, list):
            raise ValueError("evidence 不是数组")
        stage = str(value.get("stage_suggestion") or "keep").strip().lower()
        validity = str(value.get("validity_suggestion") or "keep").strip().lower()
        if stage not in {"pre_sale", "after_sale", "keep"}:
            stage = "keep"
        if validity not in {"valid", "invalid", "keep"}:
            validity = "keep"
        return {"status": "done", "judgment": value["judgment"], "reason": str(value.get("reason", "")),
                "suggestion": str(value.get("suggestion", "")), "evidence": evidence,
                "suggest_stage": stage, "suggest_validity": validity,
                "suggest_reason": str(value.get("suggestion_reason", ""))}

    def _cache_key(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ---- 批量总结 ----

    def summarize(self, text_blobs: list[str], scope_desc: str) -> str:
        if not self.configured:
            return "未配置 AI（请在 AI 设置页填写并保存），无法生成总结。"
        joined = "\n---\n".join(text_blobs[:40])
        if self.api_type == "responses":
            body = {
                "model": self.model,
                "temperature": 0.2,
                "input": [
                    {"role": "system", "content": [{"type": "input_text", "text": "你是客服质检分析助手，输出简明中文结论，分点说明共性问题与建议。"}]},
                    {"role": "user", "content": [{"type": "input_text", "text": f"以下是{scope_desc}的会话摘要，请总结整体服务质量、共性问题、商机情况与改进建议：\n\n{joined}"}]},
                ],
            }
        else:
            body = {
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": "你是客服质检分析助手，输出简明中文结论，分点说明共性问题与建议。"},
                    {"role": "user", "content": f"以下是{scope_desc}的会话摘要，请总结整体服务质量、共性问题、商机情况与改进建议：\n\n{joined}"},
                ],
            }
        try:
            resp_json = self._post_json(body)
            return self._extract_content(resp_json)
        except Exception as exc:
            return "AI 总结失败，不影响质检结果。"
