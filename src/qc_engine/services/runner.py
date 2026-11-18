from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from qc_engine.config_loader import load_all_config
from qc_engine.roles import RoleMapper
from qc_engine.parser.log_parser import LogParser
from qc_engine.parser.excel_parser import ExcelParser
from qc_engine.matcher import Matcher
from qc_engine.services.pipeline import build_conversation
from qc_engine.rules.engine import PHONE_RE, RuleEngine, phone_hits
from qc_engine.quality.scoring import ScoringEngine
from qc_engine.storage.database import Database
from qc_engine.ai.client import AIClient
from qc_engine.model_matcher import ModelMatcher

RULE_VERSION = "rules-v0.2.0"
SCORING_VERSION = "scoring-v0.2.0"
AI_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "ai_config.json"


def load_ai_config() -> dict[str, Any]:
    if AI_CONFIG_PATH.exists():
        try:
            return json.loads(AI_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_ai_config(cfg: dict[str, Any]) -> None:
    AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    AI_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def load_records(db: Database) -> list[dict[str, Any]]:
    """从库载入全部历史会话（跨店铺累积），转成 UI 行结构。"""
    rows = db.load_all_conversations()
    out: list[dict[str, Any]] = []
    for r in rows:
        messages = json.loads(r["messages_json"] or "[]")
        has_phone = any(phone_hits(str(m.get("body_text", ""))) for m in messages)
        out.append({
            "id": r["id"],
            "batch_id": r["batch_id"],
            "store_id": r["store_id"] or "",
            "agent": r["agent_display"] or "",
            "customer": r["customer_id"] or "",
            "first_message_at": r["first_message_at"] or "",
            "product_ids": json.loads(r["product_ids_json"] or "[]"),
            "excel_labels": json.loads(r["excel_labels_json"] or "{}"),
            "messages": messages,
            "service_stage": r["service_stage"] or "needs_review",
            "validity": r["validity"] or "needs_review",
            "lead_level": r["lead_level"] or ("A" if has_phone else None),
            "tele_sales_lead": bool(r["tele_sales_lead"]) or has_phone,
            "follow_up_advice": r["follow_up_advice"] or "",
            "reason_codes": json.loads(r["reason_codes_json"] or "[]"),
            "dimensions": json.loads(r["dimensions_json"] or "{}"),
            "deductions": json.loads(r["deductions_json"] or "{}"),
            "fatal_candidates": json.loads(r["fatal_candidates_json"] or "[]"),
            "calculated_score": r["calculated_score"],
            "final_status": r["final_status"],
            "final_score": r["final_score"],
            "ai_status": r["ai_status"],
            "ai_judgment": r["ai_judgment"],
            "ai_reason": r["ai_reason"],
            "ai_evidence": json.loads(r["ai_evidence_json"] or "[]"),
            "review_status": r["review_status"],
            "review_note": r["review_note"],
            "fatal_confirmed": bool(r["fatal_confirmed"]),
        })
    return out


class QCRunner:
    """完整质检流程：解析→匹配→规则→评分→SQLite 持久化（多店铺累积、批次去重）。"""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.cfg = load_all_config(config_dir)
        self.rm = RoleMapper(self.cfg["roles"])
        self.engine = RuleEngine(self.cfg["rules"])
        self.scoring = ScoringEngine(self.cfg["scoring"])
        self.model_matcher = ModelMatcher(self.cfg.get("products", {}))
        self.import_cfg = self.cfg["app"].get("import", {})
        self.matching_cfg = self.cfg["app"].get("matching", {})
        db_path = Path(self.cfg["app"].get("app", {}).get("database_path", "data/qc.db"))
        if not db_path.is_absolute():
            db_path = config_dir.parent / db_path
        self.db = Database(db_path)
        self.db.initialize()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def run(self, log_path: Path, excel_path: Path, store_id: str | None = None) -> dict[str, Any]:
        log_sha = self._sha256(log_path)
        existing = self.db.find_batch_by_sha(log_sha)
        if existing:
            return {"duplicated": True, "batch_id": existing["id"],
                    "message": f"该聊天记录已于 {existing['imported_at']} 导入过（批次 {existing['id']}），未重复导入。"}

        log_parser = LogParser(self.rm, encoding=self.import_cfg.get("log_encoding", "utf-8-sig"))
        excel_parser = ExcelParser(self.rm, sheet_name=self.import_cfg.get("excel_sheet_name", "咨询会话查询"))
        sessions = log_parser.parse(log_path)
        records = excel_parser.parse(excel_path) if excel_path and Path(excel_path).exists() else []
        matcher = Matcher(self.rm, time_tolerance_seconds=int(self.matching_cfg.get("time_tolerance_seconds", 600)))
        diag = matcher.diagnose(sessions, records)
        log_to_excel = {item["log"]["index"]: item["excel"] for item in diag["matched_records"]}

        batch_id = f"batch-{log_sha[:8]}"
        times = [s.first_message_at for s in sessions if s.first_message_at]
        self.db.insert_batch({
            "id": batch_id, "log_file": str(log_path), "excel_file": str(excel_path),
            "log_sha256": log_sha, "store_id": store_id,
            "data_start_at": min(times).strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "data_end_at": max(times).strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "session_count": len(sessions), "matched_count": diag["matched"],
        })

        conv_rows: list[dict[str, Any]] = []
        result_rows: list[dict[str, Any]] = []
        for idx, s in enumerate(sessions):
            conv = build_conversation(s, log_to_excel.get(idx), store_id, batch_id, self.rm, log_sha, self.model_matcher)
            decision, signals = self.engine.screen(conv)
            score = self.scoring.calculate(conv, decision, signals)
            match_state = "matched" if idx in log_to_excel else "unmatched"
            conv_rows.append({
                "id": conv.conversation_id, "batch_id": batch_id, "store_id": store_id,
                "source_file": conv.source_file, "source_session_index": conv.source_session_index,
                "agent_id": conv.agent_id, "agent_display": conv.agent_display,
                "customer_id": conv.customer_id, "product_ids": conv.product_ids,
                "excel_labels": conv.excel_labels, "messages": conv.messages,
                "first_message_at": conv.first_message_at, "last_message_at": conv.last_message_at,
                "message_count": len(conv.messages), "match_state": match_state,
                "parse_warnings": s.warnings,
            })
            result_rows.append({
                "conversation_id": conv.conversation_id, "rule_version": RULE_VERSION,
                "scoring_version": SCORING_VERSION, "service_stage": decision.service_stage,
                "validity": decision.validity, "lead_level": decision.lead_level,
                "tele_sales_lead": decision.tele_sales_lead, "follow_up_advice": decision.follow_up_advice,
                "reason_codes": decision.reason_codes, "evidence_refs": decision.evidence_refs,
                "dimensions": score.dimensions, "deductions": score.deductions,
                "fatal_candidates": score.fatal_candidates, "calculated_score": score.calculated_score,
                "final_status": score.final_status, "final_score": score.final_score,
                "review_status": "pending" if decision.suspicious else "not_required",
            })
        self.db.bulk_import(conv_rows, result_rows)

        return {
            "duplicated": False, "batch_id": batch_id,
            "session_count": len(sessions), "matched": diag["matched"], "unmatched": diag["unmatched_log"],
            "message": f"导入完成：{len(sessions)} 会话（匹配标签 {diag['matched']}，未匹配独立保留 {diag['unmatched_log']}）。",
        }

    # ---- AI ----

    def ai_client(self) -> AIClient:
        return AIClient({**load_ai_config(), "timeout_seconds": 60}, self.db)

    def run_ai_review(self, rows: list[dict[str, Any]], progress=None) -> dict[str, int]:
        """对可疑会话逐条 AI 质检，写回数据库。"""
        client = self.ai_client()
        targets = [
            r for r in rows
            if r["review_status"] != "completed"
            and (r["review_status"] == "pending" or r["service_stage"] == "needs_review")
        ]
        done = 0
        for r in targets:
            payload = {
                "conversation_id": r["id"],
                "messages": [
                    {"message_ref": f"message:{m['index']}", "sender_role": m["sender_role"], "body_text": m["body_text"]}
                    for m in r["messages"]
                ],
            }
            result = client.judge_conversation(payload)
            self.db.update_ai_judgment(r["id"], result.get("status", "failed"),
                                       result.get("judgment"), result.get("reason"), result.get("suggestion"),
                                       result.get("evidence"))
            done += 1
            if progress and done % 20 == 0:
                progress(done, len(targets))
        return {"total": len(targets), "processed": done}

    def ai_summarize(self, rows: list[dict[str, Any]]) -> str:
        client = self.ai_client()
        blobs = [
            f"客服={r['agent']} 阶段={r['service_stage']} 等级={r['lead_level']} 有效={r['validity']} 分={r['calculated_score']}\n"
            f"摘要: {self._excerpt(r)}"
            for r in rows[:40]
        ]
        return client.summarize(blobs, f"筛选后的 {len(rows)} 条会话")

    @staticmethod
    def _excerpt(r: dict[str, Any]) -> str:
        parts = []
        for m in r["messages"][:10]:
            role = {"agent": "客服", "customer": "客户", "bot": "机器人"}.get(m.get("sender_role"), "?")
            parts.append(f"[{role}]{m.get('body_text', '')[:80]}")
        return " | ".join(parts)[:600]

    # ---- 复核 ----

    def save_review(self, r: dict[str, Any], final_status: str, final_score: int | None, note: str, reviewer: str, fatal_confirmed: bool) -> None:
        before = {"final_status": r.get("final_status"), "final_score": r.get("final_score"),
                  "review_status": r.get("review_status"), "review_note": r.get("review_note")}
        self.db.save_review(r["id"], final_status, final_score, note, reviewer, fatal_confirmed, before)
