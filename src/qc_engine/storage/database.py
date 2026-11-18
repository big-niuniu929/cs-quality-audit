from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS batches (
    id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL DEFAULT 'log_plus_excel',
    log_file TEXT NOT NULL,
    excel_file TEXT,
    log_sha256 TEXT NOT NULL,
    excel_sha256 TEXT,
    store_id TEXT,
    note TEXT,
    imported_at TEXT NOT NULL,
    data_start_at TEXT,
    data_end_at TEXT,
    session_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'completed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    store_id TEXT,
    source_file TEXT NOT NULL,
    source_session_index INTEGER NOT NULL,
    agent_id TEXT,
    agent_display TEXT,
    customer_id TEXT,
    product_ids_json TEXT NOT NULL DEFAULT '[]',
    excel_labels_json TEXT NOT NULL DEFAULT '{}',
    messages_json TEXT NOT NULL DEFAULT '[]',
    first_message_at TEXT,
    last_message_at TEXT,
    message_count INTEGER NOT NULL DEFAULT 0,
    match_state TEXT NOT NULL DEFAULT 'unmatched',
    parse_warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);

CREATE TABLE IF NOT EXISTS quality_results (
    conversation_id TEXT PRIMARY KEY,
    rule_version TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    service_stage TEXT,
    validity TEXT,
    lead_level TEXT,
    tele_sales_lead INTEGER NOT NULL DEFAULT 0,
    follow_up_advice TEXT NOT NULL DEFAULT '',
    reason_codes_json TEXT NOT NULL DEFAULT '[]',
    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
    dimensions_json TEXT NOT NULL DEFAULT '{}',
    deductions_json TEXT NOT NULL DEFAULT '{}',
    fatal_candidates_json TEXT NOT NULL DEFAULT '[]',
    calculated_score INTEGER,
    final_status TEXT,
    final_score INTEGER,
    ai_status TEXT NOT NULL DEFAULT 'not_run',
    ai_judgment TEXT,
    ai_reason TEXT,
    ai_suggestion TEXT,
    ai_evidence_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL DEFAULT 'not_required',
    review_note TEXT,
    reviewed_by TEXT,
    reviewed_at TEXT,
    fatal_confirmed INTEGER NOT NULL DEFAULT 0,
    computed_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY,
    conversation_id TEXT,
    response_json TEXT,
    status TEXT NOT NULL DEFAULT 'done',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    actor TEXT,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


class Database:
    """轻量 SQLite 边界：全部质检数据持久化、多店铺累积、审计。"""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """轻量迁移：给已存在的表补充新增列（幂等，缺列才加）。"""
        cols = {r[1] for r in conn.execute("PRAGMA table_info(quality_results)").fetchall()}
        if "ai_evidence_json" not in cols:
            conn.execute("ALTER TABLE quality_results ADD COLUMN ai_evidence_json TEXT NOT NULL DEFAULT '[]'")

    @staticmethod
    def js(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.session() as conn:
            return list(conn.execute(sql, params).fetchall())

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self.session() as conn:
            return conn.execute(sql, params).fetchone()

    # ---- 批次 ----

    def find_batch_by_sha(self, sha: str) -> sqlite3.Row | None:
        return self.fetch_one("SELECT * FROM batches WHERE log_sha256 = ?", (sha,))

    def insert_batch(self, rec: dict[str, Any]) -> None:
        with self.session() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO batches
                (id, log_file, excel_file, log_sha256, excel_sha256, store_id, note,
                 imported_at, data_start_at, data_end_at, session_count, matched_count, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec["id"], rec["log_file"], rec.get("excel_file"), rec["log_sha256"], rec.get("excel_sha256"),
                    rec.get("store_id"), rec.get("note"), rec.get("imported_at", _now()),
                    rec.get("data_start_at"), rec.get("data_end_at"), rec.get("session_count", 0),
                    rec.get("matched_count", 0), rec.get("status", "completed"), _now(),
                ),
            )

    def list_batches(self) -> list[sqlite3.Row]:
        return self.fetch_all("SELECT * FROM batches ORDER BY imported_at DESC")

    def delete_batch(self, batch_id: str) -> int:
        """删除某次导入的批次及其关联会话、质检结果、AI 缓存。返回删除的会话数。"""
        with self.session() as conn:
            # 先取会话 id 列表，用于删 AI 缓存和质检结果
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM conversations WHERE batch_id = ?", (batch_id,)).fetchall()]
            count = 0
            if ids:
                qs = ",".join("?" * len(ids))
                conn.execute(f"DELETE FROM ai_cache WHERE conversation_id IN ({qs})", ids)
                conn.execute(f"DELETE FROM quality_results WHERE conversation_id IN ({qs})", ids)
                count = conn.execute(f"DELETE FROM conversations WHERE batch_id = ?", (batch_id,)).rowcount
            conn.execute("DELETE FROM batches WHERE id = ?", (batch_id,))
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                ("batch", batch_id, "delete_batch", self.js({"batch_id": batch_id, "removed_conversations": count}),
                 "{}", "质检员", _now()),
            )
            return count

    # ---- 会话与质检结果 ----

    def upsert_conversation(self, rec: dict[str, Any]) -> None:
        with self.session() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO conversations
                (id, batch_id, store_id, source_file, source_session_index, agent_id, agent_display,
                 customer_id, product_ids_json, excel_labels_json, messages_json,
                 first_message_at, last_message_at, message_count, match_state, parse_warnings_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec["id"], rec["batch_id"], rec.get("store_id"), rec.get("source_file"),
                    rec.get("source_session_index"), rec.get("agent_id"), rec.get("agent_display"),
                    rec.get("customer_id"), self.js(rec.get("product_ids", [])), self.js(rec.get("excel_labels", {})),
                    self.js(rec.get("messages", [])), rec.get("first_message_at"), rec.get("last_message_at"),
                    rec.get("message_count", 0), rec.get("match_state", "unmatched"), self.js(rec.get("parse_warnings", [])),
                    _now(),
                ),
            )

    def upsert_quality_result(self, rec: dict[str, Any]) -> None:
        with self.session() as conn:
            self._upsert_quality_result_conn(conn, rec)

    def bulk_import(self, conversations: list[dict[str, Any]], results: list[dict[str, Any]]) -> None:
        """单连接批量写入（导入性能关键：避免数千次连接开关）。"""
        with self.session() as conn:
            for rec in conversations:
                self._upsert_conversation_conn(conn, rec)
            for rec in results:
                self._upsert_quality_result_conn(conn, rec)

    def _upsert_conversation_conn(self, conn: sqlite3.Connection, rec: dict[str, Any]) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO conversations
            (id, batch_id, store_id, source_file, source_session_index, agent_id, agent_display,
             customer_id, product_ids_json, excel_labels_json, messages_json,
             first_message_at, last_message_at, message_count, match_state, parse_warnings_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec["id"], rec["batch_id"], rec.get("store_id"), rec.get("source_file"),
                rec.get("source_session_index"), rec.get("agent_id"), rec.get("agent_display"),
                rec.get("customer_id"), self.js(rec.get("product_ids", [])), self.js(rec.get("excel_labels", {})),
                self.js(rec.get("messages", [])), rec.get("first_message_at"), rec.get("last_message_at"),
                rec.get("message_count", 0), rec.get("match_state", "unmatched"), self.js(rec.get("parse_warnings", [])),
                _now(),
            ),
        )

    def _upsert_quality_result_conn(self, conn: sqlite3.Connection, rec: dict[str, Any]) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO quality_results
            (conversation_id, rule_version, scoring_version, service_stage, validity, lead_level,
             tele_sales_lead, follow_up_advice, reason_codes_json, evidence_refs_json,
             dimensions_json, deductions_json, fatal_candidates_json, calculated_score,
             final_status, final_score, ai_status, ai_judgment, ai_reason, ai_suggestion,
             review_status, computed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rec["conversation_id"], rec.get("rule_version", ""), rec.get("scoring_version", ""),
                rec.get("service_stage"), rec.get("validity"), rec.get("lead_level"),
                int(rec.get("tele_sales_lead", False)), rec.get("follow_up_advice", ""),
                self.js(rec.get("reason_codes", [])), self.js(rec.get("evidence_refs", [])),
                self.js(rec.get("dimensions", {})), self.js(rec.get("deductions", {})),
                self.js(rec.get("fatal_candidates", [])), rec.get("calculated_score"),
                rec.get("final_status"), rec.get("final_score"), rec.get("ai_status", "not_run"),
                rec.get("ai_judgment"), rec.get("ai_reason"), rec.get("ai_suggestion"),
                rec.get("review_status", "not_required"), _now(),
            ),
        )

    def load_all_conversations(self) -> list[dict[str, Any]]:
        """载入全部历史会话（跨店铺累积），联表质检结果。"""
        rows = self.fetch_all(
            """SELECT c.*, q.service_stage, q.validity, q.lead_level, q.tele_sales_lead,
               q.follow_up_advice, q.reason_codes_json, q.dimensions_json, q.deductions_json,
               q.fatal_candidates_json, q.calculated_score, q.final_status, q.final_score,
               q.ai_status, q.ai_judgment, q.ai_reason, q.ai_suggestion, q.ai_evidence_json,
               q.review_status, q.review_note, q.fatal_confirmed
               FROM conversations c LEFT JOIN quality_results q ON q.conversation_id = c.id
               ORDER BY c.first_message_at"""
        )
        return [dict(r) for r in rows]

    # ---- 复核 ----

    def save_review(
        self, conversation_id: str, final_status: str, final_score: int | None,
        note: str, reviewer: str, fatal_confirmed: bool, before: dict[str, Any],
    ) -> None:
        with self.session() as conn:
            conn.execute(
                """UPDATE quality_results SET review_status='completed', final_status=?,
                final_score=?, review_note=?, reviewed_by=?, reviewed_at=?, fatal_confirmed=?
                WHERE conversation_id=?""",
                (final_status, final_score, note, reviewer, _now(), int(fatal_confirmed), conversation_id),
            )
            after = {"final_status": final_status, "final_score": final_score,
                     "review_note": note, "fatal_confirmed": int(fatal_confirmed)}
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                ("quality_result", conversation_id, "human_review", self.js(before), self.js(after), reviewer, _now()),
            )

    def insert_audit(self, entity_type: str, entity_id: str, action: str, before: Any, after: Any, actor: str = "system") -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                (entity_type, entity_id, action, self.js(before), self.js(after), actor, _now()),
            )

    # ---- AI 缓存 ----

    def get_ai_cache(self, cache_key: str) -> str | None:
        row = self.fetch_one("SELECT response_json FROM ai_cache WHERE cache_key = ? AND status='done'", (cache_key,))
        return row["response_json"] if row else None

    def set_ai_cache(self, cache_key: str, conversation_id: str, response_json: str, status: str = "done") -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ai_cache (cache_key, conversation_id, response_json, status, created_at) VALUES (?,?,?,?,?)",
                (cache_key, conversation_id, response_json, status, _now()),
            )

    def update_ai_judgment(self, conversation_id: str, status: str, judgment: str | None, reason: str | None, suggestion: str | None, evidence: Any = None) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE quality_results SET ai_status=?, ai_judgment=?, ai_reason=?, ai_suggestion=?, ai_evidence_json=? WHERE conversation_id=?",
                (status, judgment, reason, suggestion, self.js(evidence if evidence is not None else []), conversation_id),
            )
