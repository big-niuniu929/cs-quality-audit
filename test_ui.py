from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication
from app import MainWindow

app = QApplication(sys.argv)
win = MainWindow()

LOG = r"~/Downloads/聊天记录_4a6cc50209ea4079a71c04bb5f41c334.log"
XLSX = r"~/Desktop/品牌A客服质检系统_完整项目资料包_20261021/09_真实聊天样本与结果/会话记录_58e69fe1233c46bcbeaded77e59f430c.xlsx"

# 0) 清库重测
if win.runner.db.path.exists():
    win.runner.db.path.unlink()
win.runner.db.initialize()
win.records = []
win._refresh_all()

# 1) 首次导入
win.log_input.setText(LOG)
win.excel_input.setText(XLSX)
win._do_import()
n1 = len(win.records)
print("① 首次导入记录数:", n1, "| 状态:", win.import_status.text()[:50])

# 2) 重复导入应去重
win._do_import()
n2 = len(win.records)
print("② 重复导入后记录数:", n2, "| 提示:", win.import_status.text()[:50])
assert n1 == n2, "重复导入去重失败"

# 3) 总览统计 + 筛选联动
win._refresh_view()
print("③ 总览行数:", win.table.rowCount(), "| 统计:", {k: v.text() for k, v in win.stat_labels.items()})
win.f_agent.blockSignals(True); win.f_agent.setCurrentText("客服A"); win.f_agent.blockSignals(False)
win._refresh_view()
print("   筛选客服=客服A 后行数:", win.table.rowCount())
assert all(win.table.item(i, 2).text() == "客服A" for i in range(win.table.rowCount())), "客服筛选失效"
from PyQt6.QtCore import QDate
win.f_start.setDate(QDate(2026, 10, 18)); win._refresh_view()
print("   日期>=10-18 后行数:", win.table.rowCount())
assert win.table.item(0, 0).text()[:10] >= "2026-10-18", "日期筛选失效"
win.f_agent.blockSignals(True); win.f_agent.setCurrentText("全部"); win.f_agent.blockSignals(False)
win.f_start.setDate(QDate(2026, 10, 12)); win._refresh_view()

# 4) 复核队列 + 复核保存（含审计）
win._refresh_review()
pending_n = win.review_table.rowCount()
print("④ 待复核条数:", pending_n)
if pending_n:
    row = win._review_pending[0]
    win.runner.save_review(row, "合格", row.get("calculated_score"), "测试复核", "质检员", False)
    win._refresh_all()
    after = [r for r in win.records if r["id"] == row["id"]][0]
    print("   复核后:", after["review_status"], "|", after["review_note"])
    assert after["review_status"] == "completed", "复核保存失败"
    audits = win.runner.db.fetch_all("SELECT * FROM audit_log")
    assert audits, "审计日志为空"
    print("   审计日志条数:", len(audits))

# 5) 电销页
print("⑤ 电销线索条数:", win.tele_table.rowCount())

# 6) 批次历史
print("⑥ 批次历史行数:", win.batch_table.rowCount())
assert win.batch_table.rowCount() >= 1, "批次未登记"

# 7) AI 配置持久化
from qc_engine.services.runner import save_ai_config, load_ai_config
save_ai_config({"base_url": "https://gateway.example.com/v1", "model": "glm-5.3-flash", "api_key": "TEST_KEY"})
cfg = load_ai_config()
print("⑦ AI 配置读写:", cfg["base_url"], cfg["model"], "| key:", "已存" if cfg["api_key"] else "无")
save_ai_config({})

print("=== ALL TESTS OK ===")
