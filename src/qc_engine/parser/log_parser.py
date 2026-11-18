from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from qc_engine.roles import RoleMapper


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
SESSION_START_RE = re.compile(r"^/\*+以下为一通会话")
SESSION_END_RE = re.compile(r"^/\*+会话结束(?:_时间:(?P<end>[^*]+))?\*+/?$")
MESSAGE_HEADER_RE = re.compile(
    r"^\s*(?P<speaker>\S+)\s+(?P<time>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*$"
)
PRODUCT_URL_RE = re.compile(r"https?://item\.jd\.com/(?P<product>\d+)", re.I)
ANY_URL_RE = re.compile(r"https?://\S+", re.I)
IMAGE_URL_RE = re.compile(r"\.(?:png|jpe?g|gif|webp)(?:\?\S*)?$", re.I)
TEMPLATE_MARKER = "【此消息为欢迎卡片或富文本模板答案，聊天记录中暂不支持展示】"


@dataclass
class MessageRecord:
    sender_id: str
    sender_role: str
    sent_at: datetime
    body_text: str
    source_line_start: int
    source_line_end: int
    message_type: str = "text"
    product_ids: list[str] = field(default_factory=list)
    raw_text: str = ""


@dataclass
class SessionRecord:
    session_index: int
    first_message_at: datetime | None
    last_message_at: datetime | None
    source_end_time: datetime | None
    messages: list[MessageRecord] = field(default_factory=list)
    source_file: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def normalized_text(self) -> str:
        return "\n".join(m.body_text for m in self.messages if m.body_text)


class LogParser:
    """确定性解析电商平台客服 .log / .txt。角色识别走 RoleMapper（明确账号集合）。"""

    def __init__(self, role_mapper: RoleMapper, encoding: str = "utf-8-sig"):
        self.role_mapper = role_mapper
        self.encoding = encoding

    def role_for_sender(self, sender_id: str) -> str:
        return self.role_mapper.role_for(sender_id)

    def parse(self, path: Path) -> list[SessionRecord]:
        text = path.read_text(encoding=self.encoding)
        lines = text.splitlines()
        sessions: list[SessionRecord] = []
        current: SessionRecord | None = None
        current_message: MessageRecord | None = None
        body_lines: list[str] = []
        raw_message_lines: list[str] = []

        def finalize_message() -> None:
            nonlocal current_message, body_lines, raw_message_lines
            if current is None or current_message is None:
                return
            current_message.body_text = "\n".join(body_lines).strip()
            current_message.message_type = self._classify_message(current_message.body_text)
            current_message.product_ids = sorted(set(PRODUCT_URL_RE.findall(current_message.body_text)))
            current_message.raw_text = "\n".join(raw_message_lines).strip()
            current.messages.append(current_message)
            current_message = None
            body_lines = []
            raw_message_lines = []

        def finalize_session(end_time: datetime | None, line_number: int) -> None:
            nonlocal current
            if current is None:
                return
            finalize_message()
            current.source_end_time = end_time
            current.last_message_at = max((m.sent_at for m in current.messages), default=None)
            if not current.messages:
                current.warnings.append("session_without_messages")
            if current.source_end_time is None:
                current.warnings.append("missing_source_end_time")
            elif current.last_message_at and current.source_end_time != current.last_message_at:
                current.warnings.append("source_end_time_differs_from_last_message")
            current.warnings.append(f"source_end_line:{line_number}")
            sessions.append(current)
            current = None

        for line_number, raw_line in enumerate(lines, start=1):
            line = raw_line.rstrip("\t")
            if SESSION_START_RE.search(line):
                if current is not None:
                    finalize_session(None, line_number)
                    sessions[-1].warnings.append("implicit_session_close")
                current = SessionRecord(
                    session_index=len(sessions) + 1,
                    first_message_at=None,
                    last_message_at=None,
                    source_end_time=None,
                    source_file=str(path),
                )
                current.warnings.append(f"source_start_line:{line_number}")
                continue

            if current is None:
                continue

            end_match = SESSION_END_RE.search(line)
            if end_match:
                end_time = self._parse_time(end_match.group("end"))
                if end_match.group("end") and end_time is None:
                    current.warnings.append("invalid_source_end_time")
                finalize_session(end_time, line_number)
                continue

            header_match = MESSAGE_HEADER_RE.match(line)
            if header_match:
                finalize_message()
                sent_at = self._parse_time(header_match.group("time"))
                if sent_at is None:
                    continue
                sender_id = header_match.group("speaker")
                current_message = MessageRecord(
                    sender_id=sender_id,
                    sender_role=self.role_for_sender(sender_id),
                    sent_at=sent_at,
                    body_text="",
                    source_line_start=line_number,
                    source_line_end=line_number,
                )
                raw_message_lines = [line]
                body_lines = []
                if current.first_message_at is None:
                    current.first_message_at = sent_at
                continue

            if current_message is not None:
                body_lines.append(line)
                raw_message_lines.append(line)
                current_message.source_line_end = line_number

        if current is not None:
            finalize_session(None, len(lines))
            sessions[-1].warnings.append("file_ended_without_session_marker")
        return sessions

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), TIMESTAMP_FORMAT)
        except ValueError:
            return None

    @staticmethod
    def _classify_message(body_text: str) -> str:
        if TEMPLATE_MARKER in body_text:
            return "bot_template"
        if "引用：" in body_text:
            return "quote"
        urls = ANY_URL_RE.findall(body_text)
        has_product = bool(PRODUCT_URL_RE.search(body_text))
        has_image = any(IMAGE_URL_RE.search(url) for url in urls)
        has_html = "<br" in body_text.lower() or "<span" in body_text.lower()
        if has_product and PRODUCT_URL_RE.sub("", body_text).strip():
            return "mixed"
        if has_product:
            return "product_link"
        if has_image and len(urls) == 1 and body_text.strip() == urls[0]:
            return "image_link"
        if has_html:
            return "html"
        if urls and body_text.strip() == urls[0]:
            return "url"
        return "text"

    def probe(self, path: Path) -> dict:
        sessions = self.parse(path)
        return {
            "path": str(path),
            "encoding": self.encoding,
            "status": "ok",
            "session_count": len(sessions),
            "message_count": sum(s.message_count for s in sessions),
            "warning_count": sum(len(s.warnings) for s in sessions),
        }
