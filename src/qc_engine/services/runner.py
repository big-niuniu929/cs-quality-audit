from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from qc_engine.config_loader import load_all_config, load_yaml
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
SCORING_VERSION = "scoring-v2.0.0"


def _project_dir() -> Path:
    """源码运行取项目根目录；打包后取 exe 所在目录（config/data 与 exe 同级）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[3]


PROJECT_DIR = _project_dir()
AI_CONFIG_PATH = PROJECT_DIR / "config" / "ai_config.json"


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


def _phone_from_messages(messages: list[dict[str, Any]]) -> bool:
    """单条内没命中时，把同一客户连续消息拼接后再判断（号码分段发送）。"""
    import re as _re

    customer_messages = [m for m in messages if m.get("sender_role") == "customer"]
    if any(phone_hits(str(m.get("body_text", ""))) for m in customer_messages):
        return True
    customer_texts = [str(m.get("body_text", "")) for m in customer_messages]
    for start in range(len(customer_texts)):
        combined = ""
        for text in customer_texts[start:start + 5]:
            combined += _re.sub(r"[\s\-–—]+", "", text)
            if len(combined) > 80:
                break
            if phone_hits(combined):
                return True
    return False


def load_records(db: Database) -> list[dict[str, Any]]:
    """从库载入全部历史会话（跨店铺累积），转成 UI 行结构。"""
    rows = db.load_all_conversations()
    out: list[dict[str, Any]] = []
    for r in rows:
        messages = json.loads(r["messages_json"] or "[]")
        labels = json.loads(r["excel_labels_json"] or "{}")
        # 显示名优先 Excel 顾客（未打码）；合并键仍用日志账号（稳定）
        customer_display = str(labels.get("customer_name") or "").strip() or (r["customer_id"] or "")
        has_phone = _phone_from_messages(messages)
        out.append({
            "id": r["id"],
            "batch_id": r["batch_id"],
            "store_id": r["store_id"] or "",
            "agent": r["agent_display"] or "",
            "customer": customer_display,
            "customer_key": r["customer_id"] or customer_display,
            "first_message_at": r["first_message_at"] or "",
            "product_ids": json.loads(r["product_ids_json"] or "[]"),
            "excel_labels": labels,
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
            "ai_suggestion": r["ai_suggestion"],
            "ai_evidence": json.loads(r["ai_evidence_json"] or "[]"),
            "ai_suggest_stage": r["ai_suggest_stage"] or "",
            "ai_suggest_validity": r["ai_suggest_validity"] or "",
            "ai_suggest_reason": r["ai_suggest_reason"] or "",
            "review_status": r["review_status"],
            "review_note": r["review_note"],
            "fatal_confirmed": bool(r["fatal_confirmed"]),
        })
    return out


class QCRunner:
    """完整质检流程：解析→匹配→规则→评分→SQLite 持久化（多店铺累积、批次去重）。"""

    def __init__(self, config_dir: Path, scoring_profile: str | None = None):
        self.config_dir = config_dir
        self.cfg = load_all_config(config_dir)
        self.rm = RoleMapper(self.cfg["roles"])
        self.engine = RuleEngine(self.cfg["rules"])
        self.scoring_profile = scoring_profile or ""
        self.scoring = ScoringEngine(self._scoring_config())
        self.model_matcher = ModelMatcher(self.cfg.get("products", {}))
        self.import_cfg = self.cfg["app"].get("import", {})
        self.matching_cfg = self.cfg["app"].get("matching", {})
        db_path = Path(self.cfg["app"].get("app", {}).get("database_path", "data/qc.db"))
        if not db_path.is_absolute():
            db_path = config_dir.parent / db_path
        self.db = Database(db_path)
        self.db.initialize()

    def _scoring_config(self) -> dict[str, Any]:
        if self.scoring_profile:
            profile = self.config_dir / "scoring_profiles" / self.scoring_profile
            cfg = load_yaml(profile)
            if cfg:
                return cfg
        return self.cfg["scoring"]

    def set_scoring_profile(self, profile: str | None) -> None:
        """切换评分标准（profile 为 scoring_profiles 下的文件名；空字符串=默认 scoring.yaml）。"""
        self.scoring_profile = profile or ""
        self.scoring = ScoringEngine(self._scoring_config())

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
            existing_count = self.db.count_conversations(existing["id"])
            if existing_count > 0:
                return {"duplicated": True, "batch_id": existing["id"],
                        "message": f"该聊天记录已于 {existing['imported_at']} 导入过（批次 {existing['id']}），未重复导入。"}
            # 上次导入只写了批次、会话写入失败（旧版遗留）：清掉空批次后继续导入
            self.db.delete_batch(existing["id"])

        log_parser = LogParser(self.rm, encoding=self.import_cfg.get("log_encoding", "utf-8-sig"))
        excel_parser = ExcelParser(self.rm, sheet_name=self.import_cfg.get("excel_sheet_name", "咨询会话查询"))
        records = excel_parser.parse(excel_path) if excel_path and Path(excel_path).exists() else []

        # 用 Excel「客服」「转接后客服」列校准本批次的客服账号集合（客户昵称不再被误判）
        self._batch_agent_ids = set()
        for rec in records:
            for key in ("客服", "转接后客服"):
                raw = str(rec.get(key) or "").replace("，", ",").replace("、", ",").replace("；", ",").replace(";", ",")
                for name in (x.strip() for x in raw.split(",")):
                    if name and self.rm.role_for(name) != "bot":
                        self._batch_agent_ids.add(name)
        for name in self._batch_agent_ids:
            self.rm.agents.setdefault(name, name)

        sessions = log_parser.parse(log_path)
        original_count = len(sessions)
        sessions = self._merge_sessions(
            sessions, int(self.import_cfg.get("session_merge_gap_minutes", 60)) * 60)
        merged_fragments = original_count - len(sessions)

        matcher = Matcher(self.rm, time_tolerance_seconds=int(self.matching_cfg.get("time_tolerance_seconds", 600)))
        diag = matcher.diagnose(sessions, records)
        log_to_excel = {item["log"]["index"]: item["excel"] for item in diag["matched_records"]}

        batch_id = f"batch-{log_sha[:8]}"
        times = [s.first_message_at for s in sessions if s.first_message_at]
        batch_record = {
            "id": batch_id, "log_file": str(log_path), "excel_file": str(excel_path),
            "log_sha256": log_sha, "store_id": store_id,
            "data_start_at": min(times).strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "data_end_at": max(times).strftime("%Y-%m-%d %H:%M:%S") if times else None,
            "session_count": len(sessions), "matched_count": diag["matched"],
        }

        conv_rows: list[dict[str, Any]] = []
        result_rows: list[dict[str, Any]] = []
        for idx, s in enumerate(sessions):
            conv = build_conversation(s, log_to_excel.get(idx), store_id, batch_id, self.rm, log_sha,
                                      self.model_matcher, agent_ids=self._batch_agent_ids)
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
                "review_status": ("pending" if (decision.suspicious or score.suspicious_reasons)
                                  else "not_required"),
            })
        # 批次、会话、质检结果同一事务：失败不会留下“有批次、没数据”的空壳
        self.db.import_batch(batch_record, conv_rows, result_rows)

        return {
            "duplicated": False, "batch_id": batch_id,
            "session_count": len(sessions), "matched": diag["matched"], "unmatched": diag["unmatched_log"],
            "merged_fragments": merged_fragments,
            "message": (f"导入完成：{len(sessions)} 次咨询（已合并同一客户碎片会话 {merged_fragments} 条；"
                        f"匹配标签 {diag['matched']}，未匹配独立保留 {diag['unmatched_log']}）。"),
        }

    # ---- 会话碎片合并 ----

    @staticmethod
    def _merge_sessions(sessions, gap_seconds: int):
        """同一客户、间隔不超过 gap_seconds 的连续会话 → 合并成一次咨询。

        电商平台日志会把一次咨询按超时/转接切成多通；不合并会导致统计虚高、首响时间失真。
        """
        ordered = sorted(
            (s for s in sessions if s.first_message_at),
            key=lambda s: s.first_message_at,
        ) + [s for s in sessions if not s.first_message_at]
        merged = []
        last_by_customer: dict = {}
        for session in ordered:
            customer = next(
                (m.sender_id for m in session.messages if m.sender_role == "customer"), None)
            if customer:
                prev = last_by_customer.get(customer)
                if prev is not None and (
                    session.first_message_at - (prev.last_message_at or prev.first_message_at)
                ).total_seconds() <= gap_seconds:
                    prev.messages.extend(session.messages)
                    prev.last_message_at = max(prev.last_message_at, session.last_message_at)
                    prev.warnings.extend(session.warnings)
                    if "merged_fragments" not in prev.warnings:
                        prev.warnings.append("merged_fragments")
                    last_by_customer[customer] = prev
                    continue
            merged.append(session)
            if customer:
                last_by_customer[customer] = session
        for index, session in enumerate(merged):
            session.session_index = index
        return merged

    # ---- 重算评分 ----

    def rescore(self, rows: list[dict[str, Any]], progress=None) -> dict[str, int]:
        """按当前规则/评分配置重算历史会话（保留 AI 判定与人工复核记录）。"""
        from qc_engine.quality.contracts import ConversationView

        total = len(rows)
        done = 0
        for row in rows:
            conv = ConversationView(
                conversation_id=row["id"],
                batch_id=row.get("batch_id") or "",
                store_id=row.get("store_id"),
                source_file="",
                source_session_index=0,
                agent_id=None,
                agent_display=row.get("agent") or None,
                customer_id=row.get("customer") or None,
                product_ids=row.get("product_ids") or [],
                excel_labels=row.get("excel_labels") or {},
                messages=row.get("messages") or [],
                first_message_at=row.get("first_message_at"),
                last_message_at=None,
            )
            decision, signals = self.engine.screen(conv)
            score = self.scoring.calculate(
                conv, decision, signals,
                ai_judgment=row.get("ai_judgment"), ai_status=row.get("ai_status"),
            )
            self.db.update_scoring_result(row["id"], {
                "rule_version": RULE_VERSION,
                "scoring_version": SCORING_VERSION,
                "service_stage": decision.service_stage,
                "validity": decision.validity,
                "lead_level": decision.lead_level,
                "tele_sales_lead": decision.tele_sales_lead,
                "follow_up_advice": decision.follow_up_advice,
                "reason_codes": decision.reason_codes,
                "evidence_refs": decision.evidence_refs,
                "dimensions": score.dimensions,
                "deductions": score.deductions,
                "fatal_candidates": score.fatal_candidates,
                "calculated_score": score.calculated_score,
                "final_status": score.final_status,
                "final_score": score.final_score,
                "review_status": ("pending" if (decision.suspicious or score.suspicious_reasons)
                                  else "not_required"),
            })
            done += 1
            if progress and done % 25 == 0:
                progress(done, total)
        return {"total": total, "processed": done}

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
            messages = []
            for i, m in enumerate(r.get("messages") or [], start=1):
                if m.get("sender_role") == "system":
                    continue
                messages.append({
                    "message_ref": f"message:{m.get('index', i)}",
                    "sender_role": m.get("sender_role") or "customer",
                    "body_text": str(m.get("body_text") or ""),
                })
            payload = {
                "conversation_id": r["id"],
                "rule_judgment": {"service_stage": r.get("service_stage"),
                                  "validity": r.get("validity"),
                                  "lead_level": r.get("lead_level"),
                                  "calculated_score": r.get("calculated_score")},
                "messages": messages or [{"message_ref": "message:0", "sender_role": "system", "body_text": "（空会话）"}],
            }
            result = client.judge_conversation(payload)
            self.db.update_ai_judgment(r["id"], result.get("status", "failed"),
                                       result.get("judgment"), result.get("reason"), result.get("suggestion"),
                                       result.get("evidence"), result.get("suggest_stage"),
                                       result.get("suggest_validity"), result.get("suggest_reason"))
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
