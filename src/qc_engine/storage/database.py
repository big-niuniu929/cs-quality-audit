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
    ai_suggest_stage TEXT,
    ai_suggest_validity TEXT,
    ai_suggest_reason TEXT,
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
        for column in ("ai_suggest_stage", "ai_suggest_validity", "ai_suggest_reason"):
            if column not in cols:
                conn.execute(f"ALTER TABLE quality_results ADD COLUMN {column} TEXT")

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

    def _insert_batch_conn(self, conn: sqlite3.Connection, rec: dict[str, Any]) -> None:
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

    def insert_batch(self, rec: dict[str, Any]) -> None:
        with self.session() as conn:
            self._insert_batch_conn(conn, rec)

    def count_conversations(self, batch_id: str) -> int:
        row = self.fetch_one("SELECT COUNT(*) AS c FROM conversations WHERE batch_id = ?", (batch_id,))
        return int(row["c"]) if row else 0

    def import_batch(self, batch: dict[str, Any], conversations: list[dict[str, Any]],
                     results: list[dict[str, Any]]) -> None:
        """批次 + 会话 + 质检结果一次性事务写入：任何一步失败都不会留下空批次。"""
        with self.session() as conn:
            self._insert_batch_conn(conn, batch)
            for rec in conversations:
                self._upsert_conversation_conn(conn, rec)
            for rec in results:
                self._upsert_quality_result_conn(conn, rec)

    def repair_batches(self) -> dict[str, int]:
        """清理未完成导入留下的空批次；重复 SHA 只提示不自动删数据。返回统计。"""
        removed = 0
        duplicates = 0
        seen_sha: set[str] = set()
        for batch in self.list_batches():
            try:
                count = self.count_conversations(batch["id"])
            except Exception:
                count = 0
            if count == 0:
                self.delete_batch(batch["id"])
                removed += 1
                continue
            sha = str(batch["log_sha256"] or "")
            if sha and sha in seen_sha:
                duplicates += 1
            elif sha:
                seen_sha.add(sha)
        return {"removed_empty": removed, "duplicate_sha": duplicates}

    def list_batches(self) -> list[sqlite3.Row]:
        return self.fetch_all("SELECT * FROM batches ORDER BY imported_at DESC")

    def update_batch(self, batch_id: str, store_id: str | None = None, note: str | None = None) -> int:
        """编辑导入批次的店铺标记/备注；店铺变更同步到该批次会话，返回会话数。"""
        with self.session() as conn:
            exists = conn.execute("SELECT 1 FROM batches WHERE id = ?", (batch_id,)).fetchone()
            if not exists:
                return 0
            fields, args = [], []
            if store_id is not None:
                fields.append("store_id = ?"); args.append(store_id)
            if note is not None:
                fields.append("note = ?"); args.append(note)
            if fields:
                args.append(batch_id)
                conn.execute(f"UPDATE batches SET {', '.join(fields)} WHERE id = ?", args)
            count = 0
            if store_id is not None:
                count = conn.execute(
                    "UPDATE conversations SET store_id = ? WHERE batch_id = ?", (store_id, batch_id)).rowcount
            return count

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
               q.ai_suggest_stage, q.ai_suggest_validity, q.ai_suggest_reason,
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

    def bulk_confirm_reviews(self, rows: list[dict[str, Any]], reviewer: str = "质检员") -> dict[str, int]:
        """一键复核：确认当前最终状态/分数。跳过待AI质检、售后记录等无法确认的行。"""
        confirmed = 0
        skipped = 0
        with self.session() as conn:
            for row in rows:
                status = str(row.get("final_status") or "")
                if status not in ("合格", "不合格"):
                    skipped += 1
                    continue
                score = row.get("final_score")
                if score is None:
                    score = row.get("calculated_score")
                conn.execute(
                    """UPDATE quality_results SET review_status='completed', final_status=?, final_score=?,
                    review_note=CASE WHEN review_note IS NULL OR review_note='' THEN ? ELSE review_note END,
                    reviewed_by=?, reviewed_at=?
                    WHERE conversation_id=? AND review_status != 'completed'""",
                    (status, score, "一键复核：确认当前判断", reviewer, _now(), row["id"]),
                )
                confirmed += 1
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                ("quality_result", "bulk", "bulk_confirm_reviews", "{}",
                 self.js({"confirmed": confirmed, "skipped": skipped}), reviewer, _now()),
            )
        return {"confirmed": confirmed, "skipped": skipped}

    def insert_audit(self, entity_type: str, entity_id: str, action: str, before: Any, after: Any, actor: str = "system") -> None:
        with self.session() as conn:
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json, actor, created_at) VALUES (?,?,?,?,?,?,?)",
                (entity_type, entity_id, action, self.js(before), self.js(after), actor, _now()),
            )

    def update_scoring_result(self, conversation_id: str, rec: dict[str, Any]) -> None:
        """按最新规则/评分重算后更新结果；保留 AI 判定与人工复核记录。"""
        with self.session() as conn:
            conn.execute(
                """UPDATE quality_results SET rule_version=?, scoring_version=?, service_stage=?, validity=?,
                lead_level=?, tele_sales_lead=?, follow_up_advice=?, reason_codes_json=?, evidence_refs_json=?,
                dimensions_json=?, deductions_json=?, fatal_candidates_json=?, calculated_score=?,
                final_status=CASE WHEN review_status='completed' THEN final_status ELSE ? END,
                final_score=CASE WHEN review_status='completed' THEN final_score ELSE ? END,
                review_status=CASE WHEN review_status='completed' THEN review_status ELSE ? END,
                computed_at=?
                WHERE conversation_id=?""",
                (
                    rec.get("rule_version"), rec.get("scoring_version"), rec.get("service_stage"),
                    rec.get("validity"), rec.get("lead_level"), int(bool(rec.get("tele_sales_lead"))),
                    rec.get("follow_up_advice", ""), self.js(rec.get("reason_codes", [])),
                    self.js(rec.get("evidence_refs", [])), self.js(rec.get("dimensions", {})),
                    self.js(rec.get("deductions", {})), self.js(rec.get("fatal_candidates", [])),
                    rec.get("calculated_score"), rec.get("final_status"), rec.get("final_score"),
                    rec.get("review_status", "not_required"), _now(), conversation_id,
                ),
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

    def update_ai_judgment(self, conversation_id: str, status: str, judgment: str | None, reason: str | None,
                           suggestion: str | None, evidence: Any = None, suggest_stage: str | None = None,
                           suggest_validity: str | None = None, suggest_reason: str | None = None) -> None:
        with self.session() as conn:
            conn.execute(
                "UPDATE quality_results SET ai_status=?, ai_judgment=?, ai_reason=?, ai_suggestion=?, "
                "ai_evidence_json=?, ai_suggest_stage=?, ai_suggest_validity=?, ai_suggest_reason=? "
                "WHERE conversation_id=?",
                (status, judgment, reason, suggestion, self.js(evidence if evidence is not None else []),
                 suggest_stage, suggest_validity, suggest_reason, conversation_id),
            )

    def apply_ai_suggestion(self, conversation_id: str, service_stage: str | None,
                            validity: str | None, note: str, actor: str = "质检员") -> None:
        """人工采纳 AI 建议：改判阶段/有效性，并写审计日志。"""
        with self.session() as conn:
            before_row = conn.execute(
                "SELECT service_stage, validity, review_status FROM quality_results WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if before_row is None:
                return
            before = dict(before_row)
            conn.execute(
                """UPDATE quality_results SET service_stage=?, validity=?,
                review_status='completed', review_note=?, reviewed_by=?, reviewed_at=?
                WHERE conversation_id=?""",
                (service_stage or before["service_stage"], validity or before["validity"],
                 note, actor, _now(), conversation_id),
            )
            after = {"service_stage": service_stage or before["service_stage"],
                     "validity": validity or before["validity"],
                     "review_note": note, "review_status": "completed"}
            conn.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, before_json, after_json, actor, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                ("quality_result", conversation_id, "ai_suggestion_adopted",
                 self.js(before), self.js(after), actor, _now()),
            )
