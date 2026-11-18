from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import threading
import traceback
from pathlib import Path
from datetime import datetime, date

from PyQt6.QtCore import (Qt, QTimer, QPointF, QRectF, QThread, pyqtSignal, QSettings, QLibraryInfo,
                         QTranslator)
from PyQt6.QtGui import (QPainter, QRadialGradient, QColor, QFont, QPalette, QPainterPath,
                         QLinearGradient, QPen, QBrush, QFontMetrics, QFontDatabase, QKeySequence, QShortcut)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QFrame, QLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QTextEdit,
    QVBoxLayout, QWidget, QHeaderView, QListWidget, QListWidgetItem, QCheckBox,
    QProgressDialog, QSpinBox, QGraphicsDropShadowEffect, QSizePolicy, QMenu,
    QTabWidget, QStyledItemDelegate, QStyle, QStyleOptionViewItem,
)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

def _resolve_app_dir() -> Path:
    """数据/配置根目录。源码=app.py 目录；Windows 打包=exe 目录；macOS .app=含 .app 的文件夹。"""
    env_dir = os.environ.get("QC_APP_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if sys.platform == "darwin":
            for parent in exe.parents:
                if parent.suffix == ".app":
                    return parent.parent
        return exe.parent
    return Path(__file__).resolve().parent


APP_DIR = _resolve_app_dir()

# ---------- 跨平台字体 ----------
UI_FONT_FAMILY = "Microsoft YaHei"
_UI_FONT_DETECTED = False


def _detect_ui_font():
    global UI_FONT_FAMILY, _UI_FONT_DETECTED
    if _UI_FONT_DETECTED:
        return
    try:
        families = set(QFontDatabase.families())
    except Exception:
        return
    for candidate in ("Microsoft YaHei", "PingFang SC", "Hiragino Sans GB",
                      "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei"):
        if candidate in families:
            UI_FONT_FAMILY = candidate
            _UI_FONT_DETECTED = True
            return
    _UI_FONT_DETECTED = True


def _qss(css: str) -> str:
    """把样式里的 Windows 字体名替换成当前系统可用字体（macOS 用苹方）。"""
    _detect_ui_font()
    return css.replace("Microsoft YaHei", UI_FONT_FAMILY)


SHOVEL_EMOJI = "\U0001FA8F"
EMOJI_FONT_FAMILY = ""
_EMOJI_FONT_DETECTED = False


def _detect_emoji_font():
    global EMOJI_FONT_FAMILY, _EMOJI_FONT_DETECTED
    if _EMOJI_FONT_DETECTED:
        return
    _EMOJI_FONT_DETECTED = True
    try:
        families = set(QFontDatabase.families())
    except Exception:
        return
    for family in ("Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"):
        if family in families:
            try:
                if QFontMetrics(QFont(family)).inFontUcs4(ord(SHOVEL_EMOJI)):
                    EMOJI_FONT_FAMILY = family
                    return
            except Exception:
                pass

from qc_engine.services.runner import QCRunner, load_records, load_ai_config, save_ai_config
from qc_engine.ai.copilot import (
    CopilotAgent, build_context, build_system_prompt, load_history, save_history, net_error_text,
    summary_line, build_map_messages, build_reduce_messages, BATCH_CARDS,
    conversation_text, batch_texts,
)
from qc_engine.ai import stats as stats_ai

STATS_HINTS = ("多少", "几条", "数量", "占比", "比例", "排名", "统计", "分布", "趋势", "平均",
               "最高", "最低", "最多", "最少", "前几", "合计", "总计", "汇总", "总共", "几个",
               "几次", "均值", "中位数", "同比", "环比", "top")

COPILOT_HISTORY_PATH = APP_DIR / "data" / "copilot_history.json"


# ---------------- 液态水晶背景 ----------------

class LiquidBackground(QWidget):
    ORBS = [
        {"color": (123, 92, 255, 150), "rx": 0.30, "ry": 0.30, "r": 0.46, "phase": 0.0, "speed": 0.18},
        {"color": (255, 92, 157, 120), "rx": 0.72, "ry": 0.62, "r": 0.42, "phase": 1.7, "speed": 0.15},
        {"color": (56, 232, 255, 100), "rx": 0.50, "ry": 0.40, "r": 0.38, "phase": 3.2, "speed": 0.21},
        {"color": (255, 177, 92, 70), "rx": 0.62, "ry": 0.72, "r": 0.34, "phase": 4.9, "speed": 0.13},
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.light = False
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)
        self.setAutoFillBackground(False)

    def set_light(self, light: bool):
        self.light = light
        self.update()

    def _tick(self):
        self._t += 0.04
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        base = QRadialGradient(QPointF(w / 2, h / 2), max(w, h) * 0.75)
        if self.light:
            base.setColorAt(0, QColor(250, 250, 252))
            base.setColorAt(1, QColor(236, 238, 245))
        else:
            base.setColorAt(0, QColor(12, 12, 20))
            base.setColorAt(1, QColor(7, 7, 12))
        p.fillRect(self.rect(), base)
        for orb in self.ORBS:
            t = self._t * orb["speed"] + orb["phase"]
            cx = (math.sin(t) * 0.18 + orb["rx"]) * w
            cy = (math.cos(t * 0.83) * 0.14 + orb["ry"]) * h
            radius = orb["r"] * max(w, h)
            r, g, b, a = orb["color"]
            grad = QRadialGradient(QPointF(cx, cy), radius)
            if self.light:
                grad.setColorAt(0.0, QColor(r, g, b, a // 3))
                grad.setColorAt(0.5, QColor(r, g, b, a // 6))
            else:
                grad.setColorAt(0.0, QColor(r, g, b, a))
                grad.setColorAt(0.5, QColor(r, g, b, a // 3))
            grad.setColorAt(1.0, QColor(r, g, b, 0))
            p.setBrush(grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx, cy), radius, radius)


class GlassCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("glassCard")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 12)
        self._shadow.setColor(QColor(0, 0, 0, 115))
        self.setGraphicsEffect(self._shadow)

    def enterEvent(self, event):
        self._shadow.setBlurRadius(36)
        self._shadow.setOffset(0, 8)
        self._shadow.setColor(QColor(51, 36, 110, 145))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 12)
        self._shadow.setColor(QColor(0, 0, 0, 115))
        super().leaveEvent(event)


class BarChart(QWidget):
    """自绘柱状图：数量标在柱顶、占比标在柱中，支持点击筛选。"""

    barClicked = pyqtSignal(int)

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.labels: list[str] = []
        self.values: list[int] = []
        self.colors: list[str] = []
        self.light = False
        self.display = "share"
        self.suffix = ""
        self.setMinimumHeight(190)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击柱子可按该分类筛选")

    def set_light(self, light: bool):
        self.light = light
        self.update()

    def set_data(self, labels: list[str], values: list[int], colors: list[str],
                 display: str = "share", suffix: str = ""):
        self.labels, self.values, self.colors = labels, values, colors
        self.display, self.suffix = display, suffix
        self.update()

    def _slot(self) -> tuple[float, float]:
        n = max(1, len(self.values))
        slot = (self.width() - 24) / n
        return slot, min(slot * 0.58, 96)

    def mousePressEvent(self, event):
        if not self.values:
            return
        slot, _ = self._slot()
        idx = int((event.position().x() - 12) // slot)
        if 0 <= idx < len(self.values):
            self.barClicked.emit(idx)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        fg = QColor(30, 32, 40, 190) if self.light else QColor(255, 255, 255, 200)
        fg_label = QColor(30, 32, 40, 150) if self.light else QColor(255, 255, 255, 150)
        fg_val = QColor(30, 32, 40, 225) if self.light else QColor(255, 255, 255, 235)
        p.setPen(fg)
        f = QFont(); f.setPointSize(11); f.setBold(True)
        p.setFont(f)
        p.drawText(12, 22, self.title)
        if not self.values:
            return
        area_top, area_bottom = 46, h - 34
        max_v = max(self.values) or 1
        total = sum(self.values) or 1
        n = len(self.values)
        slot, bar_w = self._slot()
        for i, v in enumerate(self.values):
            bh = (area_bottom - area_top) * v / max_v
            x = 12 + i * slot + (slot - bar_w) / 2
            color = QColor(self.colors[i] if i < len(self.colors) else "#7b5cff")
            # 数量：柱子正上方，字号加大
            f_count = QFont(); f_count.setPointSize(12); f_count.setBold(True)
            p.setFont(f_count)
            p.setPen(fg_val)
            p.drawText(QRectF(int(x) - 10, max(area_top - 16, int(area_bottom - bh) - 18),
                              int(bar_w) + 20, 18), Qt.AlignmentFlag.AlignHCenter, str(v))
            p.setBrush(color)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(int(x), int(area_bottom - bh), int(bar_w), int(bh), 5, 5)
            # 占比：柱子正中间；柱子太矮时放到数量上方，避免压住分类标签
            if self.display == "value":
                pct = f"{v}{self.suffix}"
            else:
                pct = f"{v / total * 100:.0f}%" if total else "0%"
            luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            if bh < 26:
                f_pct = QFont(); f_pct.setPointSize(10); f_pct.setBold(True)
                p.setFont(f_pct)
                p.setPen(fg_val)
                p.drawText(QRectF(int(x) - 10, max(area_top - 34, int(area_bottom - bh) - 36),
                                  int(bar_w) + 20, 16), Qt.AlignmentFlag.AlignHCenter, pct)
            else:
                p.setFont(f_count)
                p.setPen(QColor("#1f2329") if luminance > 170 else QColor("#ffffff"))
                p.drawText(QRectF(int(x), int(area_bottom - bh / 2 - 8), int(bar_w), 20),
                           Qt.AlignmentFlag.AlignHCenter, pct)
            # 分类：柱下
            f_lab = QFont(); f_lab.setPointSize(11)
            p.setFont(f_lab)
            p.setPen(fg_label)
            p.drawText(QRectF(int(x) - 12, area_bottom + 8, int(bar_w) + 24, 20),
                       Qt.AlignmentFlag.AlignHCenter, self.labels[i] if i < len(self.labels) else "")


class ScoreBarDelegate(QStyledItemDelegate):
    """表格里的维度得分率条：按得分率填充单元格，类似 Excel 的数据条。"""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        data = index.data(Qt.ItemDataRole.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect.adjusted(5, 7, -5, -7)
        if data in (None, "", "pending"):
            painter.setPen(QColor("#98a1b4"))
            f = QFont(); f.setPointSize(9)
            painter.setFont(f)
            painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, "待AI")
            painter.restore()
            return
        try:
            pct = max(0.0, min(1.0, float(data)))
        except (TypeError, ValueError):
            painter.restore()
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e8ecf4"))
        painter.drawRoundedRect(rect, 4, 4)
        if pct > 0:
            if pct >= 0.9:
                color = QColor("#7b5cff")
            elif pct >= 0.7:
                color = QColor("#4dabf7")
            elif pct >= 0.5:
                color = QColor("#f0a94b")
            else:
                color = QColor("#e05a5a")
            painter.setBrush(color)
            fill = rect.adjusted(0, 0, -int(rect.width() * (1 - pct)), 0)
            painter.drawRoundedRect(fill, 4, 4)
        painter.setPen(QColor("#1f2430") if pct < 0.55 else QColor("#ffffff"))
        f = QFont(); f.setPointSize(9); f.setBold(True)
        painter.setFont(f)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, f"{round(pct * 100)}%")
        painter.restore()


def _advice(row: dict) -> str:
    """优先显示 AI 语义建议（不只跟进，也含话术/服务改进），没有 AI 时退回规则建议。"""
    ai_text = str(row.get("ai_suggestion") or "").strip()
    rule_text = str(row.get("follow_up_advice") or "").strip()
    return ai_text or rule_text


class ChatView(QScrollArea):
    """微信风格聊天重现：浅灰会话底、绿/白圆角气泡、头像、系统消息居中。

    时间显示（按用户要求只用具体日期时间，不用「今天/昨天」等相对说法）：
    - 换天时显示完整日期（如 2026年9月1日 星期二）；
    - 当天内每 5 分钟一个时间标签，只显示具体时刻（如 15:30）；
    - 点击时间标签可切换为完整格式（2026年9月2日 星期三 15:30）。
    """

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("chatScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._full_time = False
        self._time_btns: list[tuple[QPushButton, str, str]] = []
        self._customer_name = _customer_label(row)
        self._agent_name = str(row.get("agent") or "客服")

        msgs = row.get("messages") or []
        container = QWidget()
        container.setObjectName("chatCanvas")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(12, 8, 12, 14)
        lay.setSpacing(0)

        if not msgs:
            empty = QLabel("该会话没有聊天记录")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color:#9aa0a8;font-size:12px;padding:30px;background:transparent;")
            lay.addWidget(empty)

        last_day = None
        last_bucket = None
        for m in msgs:
            role = m.get("sender_role")
            mtype = m.get("message_type", "text")
            body = _clean_body(m.get("body_text", ""))
            if mtype == "image_link" and not body:
                body = "［图片］"
            elif body.startswith("http") and re.search(r"dd-static|ddimg|\.(?:png|jpe?g|gif|webp)", body, re.I):
                body = "［图片］"
            if mtype == "bot_template" and "欢迎卡片" in body:
                body = "［模板消息］欢迎卡片内容暂不支持展示"
            sent = m.get("sent_at", "")
            try:
                dt = datetime.fromisoformat(str(sent)) if sent else None
            except (ValueError, TypeError):
                dt = None

            # 日期分隔线：显示具体日期，不使用「今天/昨天」等相对说法
            day_key = dt.date() if dt else None
            if dt and day_key != last_day:
                lay.addLayout(self._day_line(dt))
                last_day = day_key
                last_bucket = None

            # 时间标签：每 5 分钟一个跨度，只显示具体时刻
            if dt:
                bucket = (dt.hour, dt.minute // 5)
                if bucket != last_bucket:
                    lay.addLayout(self._time_line(dt))
                    last_bucket = bucket

            if role in ("bot", "system"):
                sysp = QLabel(body)
                sysp.setObjectName("sysPill")
                sysp.setWordWrap(True)
                sysp.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sysp.setMaximumWidth(560)
                sysp.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                wrap = QHBoxLayout(); wrap.setContentsMargins(0, 6, 0, 6)
                wrap.addStretch(1); wrap.addWidget(sysp, 0); wrap.addStretch(1)
                lay.addLayout(wrap)
                continue
            if not body:
                continue
            me = role == "agent"
            who = self._agent_name if me else self._customer_name
            caption = f"{who} · {dt:%H:%M:%S}" if dt else who
            lay.addLayout(self._msg_line(body, caption, me))

        self.setWidget(container)
        QTimer.singleShot(0, self._scroll_bottom)

    def _scroll_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._scroll_bottom)

    # ---- 行构造 ----

    def _msg_line(self, text: str, caption: str, me: bool) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        row.setContentsMargins(0, 6, 0, 6)
        avatar = QLabel("服" if me else "客")
        avatar.setObjectName("avatarMe" if me else "avatarOther")
        avatar.setFixedSize(38, 38)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap = QLabel(caption)
        cap.setObjectName("chatWho")
        cap.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cap.setToolTip(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignRight if me else Qt.AlignmentFlag.AlignLeft)
        bub = QLabel(text)
        bub.setObjectName("bubbleMe" if me else "bubbleOther")
        bub.setWordWrap(True)
        bub.setMaximumWidth(620)
        bub.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bub_row = QHBoxLayout(); bub_row.setSpacing(0)
        col = QVBoxLayout(); col.setSpacing(3)
        col.addWidget(cap)
        if me:
            bub_row.addStretch(1); bub_row.addWidget(bub)
            col.addLayout(bub_row)
            row.addStretch(1); row.addLayout(col, 1); row.addWidget(avatar)
        else:
            bub_row.addWidget(bub); bub_row.addStretch(1)
            col.addLayout(bub_row)
            row.addWidget(avatar); row.addLayout(col, 1); row.addStretch(1)
        row.setAlignment(avatar, Qt.AlignmentFlag.AlignTop)
        return row

    def _day_line(self, dt: datetime) -> QHBoxLayout:
        text = f"{dt.year}年{dt.month}月{dt.day}日 {WEEK_CN[dt.weekday()]}"
        pill = QLabel(text)
        pill.setObjectName("dayPill")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap = QHBoxLayout(); wrap.setContentsMargins(0, 12, 0, 2)
        wrap.addStretch(1); wrap.addWidget(pill, 0); wrap.addStretch(1)
        return wrap

    def _time_line(self, dt: datetime) -> QHBoxLayout:
        compact, full = self._time_texts(dt)
        btn = QPushButton(compact)
        btn.setObjectName("timePill")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("点击切换完整时间")
        btn.clicked.connect(self._toggle_time)
        wrap = QHBoxLayout(); wrap.setContentsMargins(0, 8, 0, 4)
        wrap.addStretch(1); wrap.addWidget(btn, 0); wrap.addStretch(1)
        self._time_btns.append((btn, compact, full))
        return wrap

    @staticmethod
    def _time_texts(dt: datetime) -> tuple[str, str]:
        """简洁格式只显示具体时刻（HH:MM）；点击切换为「年月日 星期 时刻」完整格式。"""
        return f"{dt:%H:%M:%S}", f"{dt.year}年{dt.month}月{dt.day}日 {WEEK_CN[dt.weekday()]} {dt:%H:%M:%S}"

    def _toggle_time(self):
        self._full_time = not self._full_time
        for btn, compact, full in self._time_btns:
            btn.setText(full if self._full_time else compact)
            btn.setToolTip("点击切换简洁时间" if self._full_time else "点击切换完整时间")


DARK_QSS = """
QWidget { background: transparent; color: rgba(255,255,255,0.92); font-size: 13px; font-family: 'Microsoft YaHei','Segoe UI',sans-serif; }
QMainWindow { background: #07070c; }
QStackedWidget { background: transparent; }
QDialog { background: #f5f7fb; color: #1f2937; }
QDialog QLabel { color: #334155; }
QMessageBox { background: #f5f7fb; color: #1f2937; }
QMessageBox QLabel { color: #334155; }
QMessageBox QPushButton { background: #ffffff; border: 1px solid #c9d4e2; color: #334155; min-height: 30px; }
QMessageBox QPushButton:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QLabel { background: transparent; }
QLabel#brand { color: #ffffff; font-size: 16px; font-weight: 650; letter-spacing: 0.02em; }
QLabel#brandMeta { color: rgba(255,255,255,0.42); font-size: 11px; }
QLabel#pageHint { color: rgba(255,255,255,0.52); font-size: 12px; }
QLabel#title { font-size: 28px; font-weight: 650; color: #ffffff; letter-spacing: -0.02em; }
QLabel#statLabel { color: rgba(255,255,255,0.52); font-size: 11px; }
QLabel#statValue { font-size: 24px; font-weight: 650; color: #b79bff; }
QLabel#statSub { font-size: 11px; color: rgba(255,255,255,0.45); }
QListWidget#nav { background: rgba(7,7,12,0.48); border: none; outline: none; padding: 18px 10px; }
QListWidget#nav::item { min-height: 24px; padding: 12px 16px; margin: 3px 0; color: rgba(255,255,255,0.55); border: 1px solid transparent; border-radius: 12px; }
QListWidget#nav::item:hover { color: rgba(255,255,255,0.84); background: rgba(255,255,255,0.055); }
QListWidget#nav::item:selected { color: #ffffff; border: 1px solid rgba(183,155,255,0.30); background: rgba(123,92,255,0.18); }
QFrame#topbar { background: rgba(12,12,20,0.72); border: 1px solid rgba(255,255,255,0.10); border-radius: 18px; }
QFrame#glassCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.10), stop:1 rgba(255,255,255,0.035)); border: 1px solid rgba(255,255,255,0.14); border-radius: 24px; }
QFrame#glassCard:hover { border: 1px solid rgba(183,155,255,0.32); }
QFrame#filterCard { background: rgba(255,255,255,0.055); border: 1px solid rgba(255,255,255,0.12); border-radius: 18px; }
QPushButton { min-height: 34px; padding: 0 15px; background: rgba(255,255,255,0.055); border: 1px solid rgba(255,255,255,0.15); border-radius: 11px; color: rgba(255,255,255,0.86); }
QPushButton:hover { background: rgba(255,255,255,0.11); border: 1px solid rgba(183,155,255,0.48); color: #ffffff; }
QPushButton:pressed { background: rgba(123,92,255,0.28); padding-top: 2px; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus, QDateEdit:focus, QTextEdit:focus, QTableWidget:focus { border: 2px solid #b79bff; }
QPushButton#primary { min-height: 40px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #7b5cff, stop:1 #9d83ff); color: #ffffff; border: 1px solid rgba(255,255,255,0.18); border-radius: 13px; font-weight: 600; }
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #8b70ff, stop:1 #ad98ff); }
QPushButton#primary:pressed { background: #6f51ec; }
QPushButton#themeToggle { min-width: 42px; max-width: 42px; min-height: 38px; max-height: 38px; padding: 0; border-radius: 12px; color: #d9d2ff; font-size: 18px; font-family: 'Segoe UI Symbol','Microsoft YaHei'; }
QComboBox, QLineEdit, QDateEdit { min-height: 32px; background: rgba(255,255,255,0.065); border: 1px solid rgba(255,255,255,0.14); border-radius: 10px; padding: 0 10px; color: #ffffff; }
QSpinBox { min-height: 32px; min-width: 92px; background: rgba(255,255,255,0.065); border: 1px solid rgba(255,255,255,0.14); border-radius: 10px; padding: 0 8px; color: #ffffff; }
QComboBox:hover, QLineEdit:hover, QDateEdit:hover { border: 1px solid rgba(183,155,255,0.34); }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView { background: #151520; border: 1px solid rgba(255,255,255,0.18); selection-background-color: rgba(123,92,255,0.42); color: #ffffff; padding: 4px; }
QTableWidget { background: rgba(255,255,255,0.035); alternate-background-color: rgba(255,255,255,0.025); border: 1px solid rgba(255,255,255,0.11); border-radius: 16px; gridline-color: rgba(255,255,255,0.06); selection-background-color: rgba(123,92,255,0.28); }
QTableWidget::item { padding: 5px 7px; }
QHeaderView::section { background: rgba(123,92,255,0.15); color: rgba(255,255,255,0.78); border: none; padding: 9px; font-weight: 600; }
QTextEdit { background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.12); border-radius: 13px; padding: 10px; color: #ffffff; }
QDialog#detailDialog { background: #eef2f6; color: #1f2937; }
QLabel#detailHeader { background: #ffffff; border: 1px solid #dce3ec; border-radius: 12px; padding: 12px; color: #1f2937; }
QLabel#detailMeta { color: #58677a; padding: 2px 4px; }
QPushButton#copyNameBtn { background: #ffffff; border: 1px solid #c9d4e2; border-radius: 7px; color: #334155; font-size: 11px; padding: 0 8px; min-height: 26px; }
QPushButton#copyNameBtn:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QLabel#detailEvidence { background: #e7f5f6; border: 1px solid #c8e5e7; border-radius: 10px; padding: 9px; color: #285b63; }
QWidget#chatCanvas { background: #ededed; }
QFrame#chatHeader { background: #f7f7f7; border: 1px solid #dce3ec; border-bottom: none; border-top-left-radius: 12px; border-top-right-radius: 12px; }
QScrollArea#chatScroll { background: #ededed; border: 1px solid #dce3ec; border-radius: 12px; border-top-left-radius: 0; border-top-right-radius: 0; }
QScrollArea#chatScroll QScrollBar:vertical { background: transparent; width: 10px; margin: 3px; }
QScrollArea#chatScroll QScrollBar::handle:vertical { background: rgba(0,0,0,0.18); border-radius: 5px; min-height: 30px; }
QScrollArea#chatScroll QScrollBar::add-line:vertical, QScrollArea#chatScroll QScrollBar::sub-line:vertical { height: 0px; }
QLabel#avatarMe { background: #5d83d7; color: #ffffff; border-radius: 19px; font-size: 13px; font-weight: 600; }
QLabel#avatarOther { background: #aeb9c8; color: #ffffff; border-radius: 19px; font-size: 13px; font-weight: 600; }
QLabel#bubbleMe { background: #95ec69; color: #14330f; border-radius: 10px; border-top-right-radius: 2px; padding: 9px 13px; font-size: 13px; }
QLabel#bubbleOther { background: #ffffff; color: #1f2329; border-radius: 10px; border-top-left-radius: 2px; padding: 9px 13px; font-size: 13px; }
QLabel#chatWho { color: #9aa0a8; font-size: 11px; padding-top: 4px; background: transparent; }
QPushButton#timePill { background: rgba(0,0,0,0.07); color: #646b75; border: none; border-radius: 6px; padding: 2px 10px; font-size: 11px; min-height: 20px; max-height: 20px; }
QPushButton#timePill:hover { background: rgba(0,0,0,0.14); color: #343a42; }
QPushButton#timePill:pressed { background: rgba(0,0,0,0.20); }
QLabel#dayPill { background: rgba(0,0,0,0.12); color: #565d66; border-radius: 6px; padding: 2px 10px; font-size: 11px; }
QLabel#sysPill { background: rgba(0,0,0,0.05); color: #7a828c; border-radius: 8px; padding: 4px 12px; font-size: 11px; }
QLabel#detailAdvice { background: #edf8f3; border: 1px solid #cde8d9; border-radius: 10px; padding: 9px; color: #2b5e43; }
QLabel#detailAiSuggestion { background: #f3efff; border: 1px solid #ddd3ff; border-radius: 10px; padding: 9px; color: #4a3a8f; }
QDialog#detailDialog QPushButton { background: #ffffff; border: 1px solid #c9d4e2; color: #334155; }
QDialog#detailDialog QPushButton:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QDialog#detailDialog QLineEdit { background: #ffffff; border: 1px solid #c9d4e2; color: #1f2937; }
QDialog#detailDialog QSpinBox { background: #ffffff; border: 1px solid #c9d4e2; color: #1f2937; }
QDialog#storeDialog { background: #f5f7fb; color: #1f2937; }
QDialog#storeDialog QLabel { color: #334155; }
QDialog#storeDialog QListWidget { background: #ffffff; border: 1px solid #dce3ec; border-radius: 10px; color: #1f2937; }
QDialog#storeDialog QListWidget::item { padding: 8px 10px; }
QDialog#storeDialog QListWidget::item:selected { background: rgba(109,75,255,0.16); color: #2a2350; }
QDialog#summaryDialog { background: #f5f7fb; color: #1f2937; }
QDialog#summaryDialog QLabel { color: #334155; }
QDialog#summaryDialog QTextEdit { background: #ffffff; border: 1px solid #e6e9ef; border-radius: 10px; color: #1f2937; }
QCalendarWidget { background: #ffffff; color: #1f2937; border: 1px solid #d6dee9; border-radius: 10px; }
QCalendarWidget QWidget { background: #ffffff; color: #1f2937; }
QCalendarWidget QToolButton { color: #334155; background: transparent; border-radius: 6px; padding: 2px 6px; }
QCalendarWidget QToolButton:hover { background: #eceafd; }
QCalendarWidget QSpinBox { background: #ffffff; color: #1f2937; border: 1px solid #c9d4e2; border-radius: 6px; margin: 2px; }
QCalendarWidget QMenu { background: #ffffff; color: #1f2937; }
QCalendarWidget QAbstractItemView { background: #ffffff; color: #1f2937; selection-background-color: #6d4bff; selection-color: #ffffff; outline: 0px; }
QMenu { background: #ffffff; color: #1f2937; border: 1px solid #d6dee9; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #efecff; color: #4a37b8; }
QMenu::separator { height: 1px; background: #e6ebf3; margin: 4px 8px; }
QToolTip { background: #ffffff; color: #1f2937; border: 1px solid #d6dee9; padding: 4px 8px; border-radius: 6px; }
QProgressDialog#progressDialog { background: #f6f8fb; border: 1px solid #d9e1eb; border-radius: 14px; color: #1f2937; }
QProgressDialog#progressDialog QLabel { color: #1f2937; }
QProgressDialog#progressDialog QPushButton { background: #6d4bff; border: none; color: #ffffff; min-height: 34px; }
QProgressDialog#progressDialog QProgressBar { background: #e5eaf2; border: 1px solid #cbd5e1; color: #334155; }
QProgressDialog#progressDialog QProgressBar::chunk { background: #6d4bff; }
QCheckBox { color: rgba(255,255,255,0.85); spacing: 7px; }
QProgressBar { min-height: 16px; background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.14); border-radius: 8px; text-align: center; color: #ffffff; }
QProgressBar::chunk { background: #7b5cff; border-radius: 7px; }
"""

LIGHT_QSS = """
QWidget { background: transparent; color: rgba(22,20,46,0.92); font-size: 13px; font-family: 'Microsoft YaHei','Segoe UI',sans-serif; }
QMainWindow { background: #eef0f8; }
QStackedWidget { background: transparent; }
QDialog { background: #f5f7fb; color: #1f2937; }
QDialog QLabel { color: #334155; }
QMessageBox { background: #f5f7fb; color: #1f2937; }
QMessageBox QLabel { color: #334155; }
QLabel { background: transparent; }
QLabel#brand { color: #2a2350; font-size: 16px; font-weight: 650; letter-spacing: 0.02em; }
QLabel#brandMeta { color: rgba(22,20,46,0.48); font-size: 11px; }
QLabel#pageHint { color: rgba(22,20,46,0.55); font-size: 12px; }
QLabel#title { font-size: 28px; font-weight: 650; color: #2a2350; letter-spacing: -0.02em; }
QLabel#statLabel { color: rgba(22,20,46,0.52); font-size: 11px; }
QLabel#statValue { font-size: 24px; font-weight: 650; color: #6d4bff; }
QLabel#statSub { font-size: 11px; color: #94a3b8; }
QListWidget#nav { background: rgba(255,255,255,0.48); border: none; outline: none; padding: 18px 10px; }
QListWidget#nav::item { min-height: 24px; padding: 12px 16px; margin: 3px 0; color: rgba(22,20,46,0.58); border: 1px solid transparent; border-radius: 12px; }
QListWidget#nav::item:hover { color: #2a2350; background: rgba(255,255,255,0.54); }
QListWidget#nav::item:selected { color: #2a2350; border: 1px solid rgba(109,75,255,0.28); background: rgba(109,75,255,0.13); }
QFrame#topbar { background: rgba(255,255,255,0.64); border: 1px solid rgba(30,28,60,0.10); border-radius: 18px; }
QFrame#glassCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.74), stop:1 rgba(255,255,255,0.36)); border: 1px solid rgba(30,28,60,0.10); border-radius: 24px; }
QFrame#glassCard:hover { border: 1px solid rgba(109,75,255,0.42); }
QFrame#filterCard { background: rgba(255,255,255,0.58); border: 1px solid rgba(30,28,60,0.10); border-radius: 18px; }
QPushButton { min-height: 34px; padding: 0 15px; background: rgba(255,255,255,0.44); border: 1px solid rgba(109,75,255,0.25); border-radius: 11px; color: #4d3b9e; }
QPushButton:hover { background: rgba(255,255,255,0.78); border: 1px solid rgba(109,75,255,0.58); color: #2a2350; }
QPushButton:pressed { background: rgba(109,75,255,0.18); padding-top: 2px; }
QPushButton:focus, QComboBox:focus, QLineEdit:focus, QDateEdit:focus, QTextEdit:focus, QTableWidget:focus { border: 2px solid #6d4bff; }
QPushButton#primary { min-height: 40px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #6d4bff, stop:1 #8970ff); color: #ffffff; border: 1px solid rgba(255,255,255,0.55); border-radius: 13px; font-weight: 600; }
QPushButton#primary:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #795aff, stop:1 #9b87ff); }
QPushButton#primary:pressed { background: #5f3ee8; }
QPushButton#themeToggle { min-width: 42px; max-width: 42px; min-height: 38px; max-height: 38px; padding: 0; border-radius: 12px; color: #5f46cc; font-size: 18px; font-family: 'Segoe UI Symbol','Microsoft YaHei'; }
QComboBox, QLineEdit, QDateEdit { min-height: 32px; background: rgba(255,255,255,0.58); border: 1px solid rgba(30,28,60,0.14); border-radius: 10px; padding: 0 10px; color: #2a2350; }
QSpinBox { min-height: 32px; min-width: 92px; background: rgba(255,255,255,0.58); border: 1px solid rgba(30,28,60,0.14); border-radius: 10px; padding: 0 8px; color: #2a2350; }
QComboBox:hover, QLineEdit:hover, QDateEdit:hover { border: 1px solid rgba(109,75,255,0.44); }
QComboBox::drop-down { width: 24px; border: none; }
QComboBox QAbstractItemView { background: #ffffff; border: 1px solid rgba(30,28,60,0.16); selection-background-color: rgba(109,75,255,0.20); color: #2a2350; padding: 4px; }
QTableWidget { background: rgba(255,255,255,0.48); alternate-background-color: rgba(255,255,255,0.32); border: 1px solid rgba(30,28,60,0.10); border-radius: 16px; gridline-color: rgba(30,28,60,0.06); selection-background-color: rgba(109,75,255,0.18); }
QTableWidget::item { padding: 5px 7px; }
QHeaderView::section { background: rgba(109,75,255,0.13); color: rgba(30,28,60,0.78); border: none; padding: 9px; font-weight: 600; }
QTextEdit { background: rgba(255,255,255,0.58); border: 1px solid rgba(30,28,60,0.12); border-radius: 13px; padding: 10px; color: #2a2350; }
QDialog#detailDialog { background: #eef2f6; color: #1f2937; }
QLabel#detailHeader { background: #ffffff; border: 1px solid #dce3ec; border-radius: 12px; padding: 12px; color: #1f2937; }
QLabel#detailMeta { color: #58677a; padding: 2px 4px; }
QPushButton#copyNameBtn { background: #ffffff; border: 1px solid #c9d4e2; border-radius: 7px; color: #334155; font-size: 11px; padding: 0 8px; min-height: 26px; }
QPushButton#copyNameBtn:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QLabel#detailEvidence { background: #e7f5f6; border: 1px solid #c8e5e7; border-radius: 10px; padding: 9px; color: #285b63; }
QWidget#chatCanvas { background: #ededed; }
QFrame#chatHeader { background: #f7f7f7; border: 1px solid #dce3ec; border-bottom: none; border-top-left-radius: 12px; border-top-right-radius: 12px; }
QScrollArea#chatScroll { background: #ededed; border: 1px solid #dce3ec; border-radius: 12px; border-top-left-radius: 0; border-top-right-radius: 0; }
QScrollArea#chatScroll QScrollBar:vertical { background: transparent; width: 10px; margin: 3px; }
QScrollArea#chatScroll QScrollBar::handle:vertical { background: rgba(0,0,0,0.18); border-radius: 5px; min-height: 30px; }
QScrollArea#chatScroll QScrollBar::add-line:vertical, QScrollArea#chatScroll QScrollBar::sub-line:vertical { height: 0px; }
QLabel#avatarMe { background: #5d83d7; color: #ffffff; border-radius: 19px; font-size: 13px; font-weight: 600; }
QLabel#avatarOther { background: #aeb9c8; color: #ffffff; border-radius: 19px; font-size: 13px; font-weight: 600; }
QLabel#bubbleMe { background: #95ec69; color: #14330f; border-radius: 10px; border-top-right-radius: 2px; padding: 9px 13px; font-size: 13px; }
QLabel#bubbleOther { background: #ffffff; color: #1f2329; border-radius: 10px; border-top-left-radius: 2px; padding: 9px 13px; font-size: 13px; }
QLabel#chatWho { color: #9aa0a8; font-size: 11px; padding-top: 4px; background: transparent; }
QPushButton#timePill { background: rgba(0,0,0,0.07); color: #646b75; border: none; border-radius: 6px; padding: 2px 10px; font-size: 11px; min-height: 20px; max-height: 20px; }
QPushButton#timePill:hover { background: rgba(0,0,0,0.14); color: #343a42; }
QPushButton#timePill:pressed { background: rgba(0,0,0,0.20); }
QLabel#dayPill { background: rgba(0,0,0,0.12); color: #565d66; border-radius: 6px; padding: 2px 10px; font-size: 11px; }
QLabel#sysPill { background: rgba(0,0,0,0.05); color: #7a828c; border-radius: 8px; padding: 4px 12px; font-size: 11px; }
QLabel#detailAdvice { background: #edf8f3; border: 1px solid #cde8d9; border-radius: 10px; padding: 9px; color: #2b5e43; }
QLabel#detailAiSuggestion { background: #f3efff; border: 1px solid #ddd3ff; border-radius: 10px; padding: 9px; color: #4a3a8f; }
QDialog#detailDialog QPushButton { background: #ffffff; border: 1px solid #c9d4e2; color: #334155; }
QDialog#detailDialog QPushButton:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QDialog#detailDialog QLineEdit { background: #ffffff; border: 1px solid #c9d4e2; color: #1f2937; }
QDialog#detailDialog QSpinBox { background: #ffffff; border: 1px solid #c9d4e2; color: #1f2937; }
QDialog#storeDialog { background: #f5f7fb; color: #1f2937; }
QDialog#storeDialog QLabel { color: #334155; }
QDialog#storeDialog QListWidget { background: #ffffff; border: 1px solid #dce3ec; border-radius: 10px; color: #1f2937; }
QDialog#storeDialog QListWidget::item { padding: 8px 10px; }
QDialog#storeDialog QListWidget::item:selected { background: rgba(109,75,255,0.16); color: #2a2350; }
QDialog#summaryDialog { background: #f5f7fb; color: #1f2937; }
QDialog#summaryDialog QLabel { color: #334155; }
QDialog#summaryDialog QTextEdit { background: #ffffff; border: 1px solid #e6e9ef; border-radius: 10px; color: #1f2937; }
QCalendarWidget { background: #ffffff; color: #1f2937; border: 1px solid #d6dee9; border-radius: 10px; }
QCalendarWidget QWidget { background: #ffffff; color: #1f2937; }
QCalendarWidget QToolButton { color: #334155; background: transparent; border-radius: 6px; padding: 2px 6px; }
QCalendarWidget QToolButton:hover { background: #eceafd; }
QCalendarWidget QSpinBox { background: #ffffff; color: #1f2937; border: 1px solid #c9d4e2; border-radius: 6px; margin: 2px; }
QCalendarWidget QMenu { background: #ffffff; color: #1f2937; }
QCalendarWidget QAbstractItemView { background: #ffffff; color: #1f2937; selection-background-color: #6d4bff; selection-color: #ffffff; outline: 0px; }
QMenu { background: #ffffff; color: #1f2937; border: 1px solid #d6dee9; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 18px; border-radius: 6px; }
QMenu::item:selected { background: #efecff; color: #4a37b8; }
QMenu::separator { height: 1px; background: #e6ebf3; margin: 4px 8px; }
QToolTip { background: #ffffff; color: #1f2937; border: 1px solid #d6dee9; padding: 4px 8px; border-radius: 6px; }
QProgressDialog#progressDialog { background: #f6f8fb; border: 1px solid #d9e1eb; border-radius: 14px; color: #1f2937; }
QProgressDialog#progressDialog QLabel { color: #1f2937; }
QProgressDialog#progressDialog QPushButton { background: #6d4bff; border: none; color: #ffffff; min-height: 34px; }
QProgressDialog#progressDialog QProgressBar { background: #e5eaf2; border: 1px solid #cbd5e1; color: #334155; }
QProgressDialog#progressDialog QProgressBar::chunk { background: #6d4bff; }
QCheckBox { color: rgba(22,20,46,0.85); spacing: 7px; }
QProgressBar { min-height: 16px; background: rgba(30,28,60,0.08); border: 1px solid rgba(30,28,60,0.14); border-radius: 8px; text-align: center; color: #2a2350; }
QProgressBar::chunk { background: #6d4bff; border-radius: 7px; }
"""

STAGE_CN = {"pre_sale": "售前", "after_sale": "售后", "needs_review": "待复核"}
VALID_CN = {"valid": "有效", "invalid": "无效", "needs_review": "待复核"}
AI_CN = {"pass": "合格", "fail": "不合格", "needs_review": "待复核", "not_run": "未运行",
         "not_configured": "未配置", "done": "已完成", "failed": "失败"}
REASON_CN = {
    "default_presale_pending": "售前咨询，等待进一步确认",
    "presale_signal": "识别到售前咨询信号",
    "after_sale_signal": "识别到售后咨询信号",
    "mixed_stage_first_business_stage": "售后与售前信号混合，按售前处理",
    "no_customer_message": "没有客户消息，需人工确认",
    "contact_information": "客户留下联系方式",
    "explicit_purchase_of_our_product": "客户有明确购买意向",
    "discount_or_promotion_intent": "客户咨询优惠或活动",
    "purchase_time_soon": "客户近期有购买计划",
    "product_comparison": "客户在对比其他产品",
    "purchase_plan_or_repeat_purchase": "客户有购买计划或复购意向",
    "cross_day_consultation": "客户跨天多次咨询",
    "repeated_parameter_questions": "客户围绕参数反复咨询",
    "customer_left_before_after_sale_answer": "客户未等到售后回复就离开",
    "single_after_sale_question_answered_without_follow_up": "售后答复后未继续跟进",
    "after_sale_resolved_or_transferred": "售后问题已解决或转交",
    "after_sale_resolution_unclear": "售后问题是否解决不明确",
    "no_substantive_customer_consultation": "没有实质性咨询内容",
    "short_conversation_without_explicit_business_signal": "会话过短且无明确业务信号",
    "customer_left_before_agent_answer": "客户未等到客服回复就离开",
    "substantive_customer_need_answered_or_engaged": "客户有明确需求，客服已响应",
    "substantive_customer_need": "客户有明确需求",
    "no_substantive_customer_question": "没有实质性问题",
    "internal_chat": "内部闲聊",
    "customer_need_unanswered": "客户需求未得到回应",
    "needs_manual_review": "需要人工复核",
    "matched_by_agent_time": "已按客服和时间匹配",
    "unmatched": "未匹配到对应记录",
}
REVIEW_CN = {"pending": "待复核", "completed": "已完成", "not_required": "无需复核"}
DIM_CN = {"response_speed": "响应速度", "presale_required_questions": "售前必问",
          "problem_resolution": "问题解决", "lead_capture": "引导留资",
          "phrase_match": "话术匹配", "promotion_touch": "优惠触达"}


def _rating_label(score) -> str:
    """评分评级：优秀≥90 / 良好≥75 / 合格≥60 / 不合格（100 分制）。"""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "待AI质检"
    if value >= 90:
        return "优秀"
    if value >= 75:
        return "良好"
    if value >= 60:
        return "合格"
    return "不合格"
FINAL_CN = {"合格": "合格", "不合格": "不合格", "needs_review": "待复核",
            "after_sale_record_only": "售后仅记录", "ai_pending": "待AI质检"}
SCORE_DIM_ORDER = ["response_speed", "presale_required_questions", "phrase_match",
                   "problem_resolution", "lead_capture", "promotion_touch"]
SCORE_DIM_SHORT = {"response_speed": "响应", "presale_required_questions": "必问",
                   "phrase_match": "话术", "problem_resolution": "问题",
                   "lead_capture": "留资", "promotion_touch": "优惠"}
WEEK_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
EXC_CN = {
    "FileNotFoundError": "找不到文件，请检查所选文件路径",
    "PermissionError": "文件被占用或无读取权限，请关闭占用它的程序后重试",
    "ValueError": "数据格式不正确，请确认选择的是同一时期导出的文件",
    "KeyError": "缺少必要字段（请把错误日志发给管理员）",
    "UnicodeDecodeError": "文件编码无法识别",
    "OSError": "文件读写失败",
    "OperationalError": "数据库读写失败",
}


def _reason_label(code: str) -> str:
    """把内部规则码转换成用户可读的中文，未知码也不直接暴露英文。"""
    return REASON_CN.get(str(code), "其他判定原因")


def _exc_cn(exc: Exception) -> str:
    """把异常翻译成中文提示；完整堆栈打印到终端，方便排查。"""
    import traceback
    traceback.print_exc()
    return EXC_CN.get(type(exc).__name__, "操作失败，请检查文件或配置后重试")


def _ref_cn(ref) -> str:
    """AI 证据引用 message:3 → 第 3 条。"""
    m = re.match(r"message[:：]\s*(\d+)", str(ref or ""))
    return f"第 {m.group(1)} 条" if m else str(ref or "?")


def _clean_body(text) -> str:
    """清理聊天正文里的 HTML 标签与实体，还原成可读纯文本。"""
    s = str(text or "")
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p>", "\n", s)
    s = re.sub(r"<[^>]*>", "", s)
    s = html.unescape(s)
    return s.strip()


def _display_score(row: dict) -> int | None:
    """复核完成后优先展示人工最终分，未复核时展示规则计算分。"""
    if row.get("review_status") == "completed" and row.get("final_score") is not None:
        return row.get("final_score")
    return row.get("calculated_score")


def _pshort(name) -> str:
    if not name:
        return "-"
    s = str(name)
    return s if len(s) <= 20 else s[:18] + ".."


def _product_label(r: dict) -> str:
    """产品列显示：优先型号，识别不出则填产品名称（截断），都不为空则不显示 '-'。"""
    model = (r.get("excel_labels") or {}).get("model") or ""
    model = str(model).strip()
    if model:
        return model
    name = (r.get("excel_labels") or {}).get("product_name") or ""
    name = str(name).strip()
    if name:
        return _pshort(name)
    return "-"


def _customer_label(row: dict) -> str:
    """客户显示名：优先 Excel「顾客」昵称，其次聊天账号（可能脱敏），最后回退「客户」。"""
    name = str((row.get("excel_labels") or {}).get("customer_name") or "").strip()
    if name:
        return name
    cid = str(row.get("customer") or "").strip()
    return cid or "客户"


# 手机号识别：11 位，1[3-9] 开头、末位必须是数字；中间 8 位允许数字或屏蔽符（* x X ＊ ×）。
# 兼容「13800000000」「139*******6」「159******45」「159****1234」等常见掩码格式。
_PHONE_RE = re.compile(r"(?<![0-9])1[3-9][0-9*xX＊×]{8}[0-9](?![0-9*xX＊×])")


def _phone_in_text(text) -> str:
    """在文本中找电话号码，先原样匹配，再去除空格/短横线后匹配。"""
    t = str(text or "")
    hit = _PHONE_RE.search(t)
    if hit:
        return hit.group(0)
    norm = re.sub(r"[\s\-–—]+", "", t)
    hit = _PHONE_RE.search(norm)
    return hit.group(0) if hit else ""


_AGENT_PREFIX_RE = re.compile(r"^(?:音视频|brandb|品牌A|brandA|品牌A官方自营旗舰店|品牌B)[-_－—]+")


def _short_agent_label(name: str) -> str:
    """筛选下拉里显示短客服名：去掉店铺前缀（音视频-zhenpeng → zhenpeng）。"""
    text = str(name or "").strip()
    short = _AGENT_PREFIX_RE.sub("", text)
    return short or text


_MERGE_KEYS_UNUSED = None


def _extract_phone(r: dict) -> str:
    """从客户消息里提取电话号码；支持同一客户把号码拆成多条消息发送（防屏蔽）。

    注意：客服发的售后/服务电话不算客户留资，因此只扫描客户消息。
    """
    messages = r.get("messages") or []
    customer_texts = [str(m.get("body_text") or "") for m in messages if m.get("sender_role") == "customer"]
    # 1) 单条客户消息内匹配
    for text in customer_texts:
        found = _phone_in_text(text)
        if found:
            return found
    # 2) 同一客户连续多条消息拼接后再匹配（如「138」「1234」「5678」）
    for start in range(len(customer_texts)):
        combined = ""
        for text in customer_texts[start:start + 5]:
            combined += re.sub(r"[\s\-–—]+", "", text)
            if len(combined) > 80:
                break
            found = _phone_in_text(combined)
            if found:
                return found
    return ""


def _merge_customer_key(row: dict) -> str:
    """合并键：店铺 + 客户（优先客户账号，其次 Excel 客户名）。"""
    key = str(row.get("customer_key") or "").strip()
    name = str(row.get("customer") or "").strip()
    # 电商平台日志的打码账号同一客户也会变（昵称打码规则不同），所以以 Excel 客户名为主；
    # 通用昵称（如 电商平台用户）不参与合并，避免误合不同客户。
    generic = {"电商平台用户", "电商平台客户", "客户", "保密", "匿名", "无", "-"}
    if name and name not in generic:
        return f"{row.get('store_id') or ''}|{name}"
    return f"{row.get('store_id') or ''}|{key or name or row.get('id')}"


def merge_consultations(records: list[dict]) -> list[dict]:
    """把同一客户在同一店铺的多次咨询合并成一条（客服列合并去重，可为多个）。"""
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in records:
        key = _merge_customer_key(row)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    merged: list[dict] = []
    for key in order:
        rows = sorted(groups[key], key=lambda x: str(x.get("first_message_at") or ""))
        first = rows[0]
        display_customer = next(
            (str(row.get("customer") or "").strip() for row in rows
             if str(row.get("customer") or "").strip()
             and not str(row.get("customer")).strip().lower().startswith("jd_")),
            str(first.get("customer") or "").strip(),
        )
        agents: list[str] = []
        for row in rows:
            name = str(row.get("agent") or "").strip()
            if name and name not in agents:
                agents.append(name)
        messages: list[dict] = []
        for index, row in enumerate(rows, start=1):
            if index > 1:
                messages.append({
                    "sender_role": "system",
                    "message_type": "text",
                    "sent_at": row.get("first_message_at") or "",
                    "body_text": f"—— 第 {index} 次咨询 · {row.get('first_message_at') or ''} ——",
                })
            messages.extend(row.get("messages") or [])
        scores = [s for s in (_display_score(row) for row in rows) if s is not None]
        stages = [row.get("service_stage") for row in rows]
        valids = [row.get("validity") for row in rows]
        leads = [row.get("lead_level") for row in rows if row.get("lead_level")]
        lead_rank = {"A": 3, "B": 2, "C": 1}
        reason_codes: list[str] = []
        fatal: list[str] = []
        deductions: dict[str, float] = {}
        excel: dict = {}
        tele = False
        advice = ""
        for row in rows:
            for code in row.get("reason_codes") or []:
                if code not in reason_codes:
                    reason_codes.append(code)
            for code in row.get("fatal_candidates") or []:
                if code not in fatal:
                    fatal.append(code)
            for dkey, dval in (row.get("deductions") or {}).items():
                deductions[dkey] = deductions.get(dkey, 0) + float(dval or 0)
            for ekey, eval_ in (row.get("excel_labels") or {}).items():
                if eval_ and not excel.get(ekey):
                    excel[ekey] = eval_
            tele = tele or bool(row.get("tele_sales_lead"))
            if not advice:
                advice = str(row.get("follow_up_advice") or "")
        ai_row = next((row for row in rows if row.get("ai_status") == "done"), rows[0])
        merged.append({
            "id": first.get("id"),
            "batch_id": first.get("batch_id"),
            "store_id": first.get("store_id"),
            "agent": "、".join(agents),
            "customer": display_customer or first.get("customer"),
            "first_message_at": min(str(row.get("first_message_at") or "") for row in rows),
            "product_ids": sorted({pid for row in rows for pid in (row.get("product_ids") or [])}),
            "excel_labels": excel,
            "messages": messages,
            "service_stage": ("needs_review" if "needs_review" in stages else stages[0]) if stages else "needs_review",
            "validity": ("invalid" if "invalid" in valids else
                         "needs_review" if "needs_review" in valids else
                         "valid" if "valid" in valids else "needs_review"),
            "lead_level": max(leads, key=lambda x: lead_rank.get(x, 0)) if leads else None,
            "tele_sales_lead": tele,
            "follow_up_advice": advice,
            "reason_codes": reason_codes,
            "dimensions": rows[0].get("dimensions") or {},
            "deductions": deductions,
            "fatal_candidates": fatal,
            "calculated_score": min(scores) if scores else None,
            "final_score": min(scores) if scores else None,
            "final_status": rows[0].get("final_status"),
            "ai_status": ai_row.get("ai_status"),
            "ai_judgment": ai_row.get("ai_judgment"),
            "ai_reason": ai_row.get("ai_reason"),
            "ai_suggestion": ai_row.get("ai_suggestion"),
            "ai_evidence": ai_row.get("ai_evidence") or [],
            "review_status": ("completed" if all(row.get("review_status") == "completed" for row in rows)
                              else "pending" if any(row.get("review_status") == "pending" for row in rows)
                              else "not_required"),
            "review_note": "；".join(str(row.get("review_note")) for row in rows if row.get("review_note")),
            "fatal_confirmed": any(bool(row.get("fatal_confirmed")) for row in rows),
            "_merged": True,
            "_session_count": len(rows),
            "_sessions": rows,
        })
    return merged


_WECHAT_RE = re.compile(r"(?:微信|加我|加v|加V|weixin|WeChat|wx)[：:号\s]*([A-Za-z][-_A-Za-z0-9]{4,19})")
_QQ_RE = re.compile(r"(?:QQ|qq|扣扣)[：:号\s]*([1-9][0-9]{4,11})")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_WECHAT_KW = re.compile(r"微信|加我|加v|加V|weixin|wx|WeChat")


def _contact_info(r: dict) -> tuple[str, str]:
    """识别客户留资方式，返回（类型, 内容）；类型取值：电话/微信/QQ/邮箱/其他/空字符串。

    只统计客户消息：客服发的售后电话/引导语不算客户留资。
    """
    joined = " ".join(str(m.get("body_text") or "") for m in r.get("messages") or []
                      if m.get("sender_role") == "customer")
    phone = _extract_phone(r)
    if phone:
        return ("微信" if _WECHAT_KW.search(joined) else "电话"), phone
    hit = _WECHAT_RE.search(joined)
    if hit:
        return "微信", hit.group(0)[:30]
    hit = _QQ_RE.search(joined)
    if hit:
        return "QQ", hit.group(0)[:30]
    hit = _EMAIL_RE.search(joined)
    if hit:
        return "邮箱", hit.group(0)[:40]
    if re.search(r"微信|加我|联系|电话|手机|私聊", joined):
        return "其他", "提到联系方式（未识别具体号码）"
    return "", ""


LOG_DIR = APP_DIR / "logs"


def _log_crash(exc: BaseException) -> str:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"crash_{datetime.now():%Y%m%d_%H%M%S}.log"
        path.write_text(text, encoding="utf-8")
        return str(path)
    except Exception:
        return ""


def _report_error(parent, title: str, exc: BaseException):
    path = _log_crash(exc)
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(f"{title}：{type(exc).__name__}: {exc}")
    if path:
        box.setInformativeText(f"错误详情已保存到：\n{path}")
    box.exec()


def _md_escape(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def _md_inline(text: str) -> str:
    s = _md_escape(text)
    s = re.sub(r"`([^`\n]+)`", r'<span style="font-family:Consolas,Menlo,monospace; color:#475569;">\1</span>', s)
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*([^*\n]+)\*", r"<i>\1</i>", s)
    s = s.replace("\n", "<br>")
    return f'<div style="margin:4px 0; line-height:150%;">{s}</div>'


def _md_to_html(md: str) -> str:
    """把聊天气泡里的 Markdown 转成 Qt 富文本 HTML（代码块/引用/列表/标题/加粗可控）。"""
    lines = str(md or "").split("\n")
    out: list[str] = []
    para: list[str] = []

    def flush_para():
        if not para:
            return
        chunk = "\n".join(para).strip()
        para.clear()
        if chunk:
            out.append(_md_inline(chunk))

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("`"):
            flush_para()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("`"):
                code_lines.append(lines[i])
                i += 1
            i += 1
            code = _md_escape("\n".join(code_lines))
            out.append(
                '<div style="margin:8px 0; ">'
                '<span style="font-family:Consolas,Menlo,monospace; font-size:12.5px;">'
                f'{code}</span></div>'
            )
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        if stripped.startswith("#"):
            flush_para()
            level = len(stripped) - len(stripped.lstrip("#"))
            content = stripped[level:].strip()
            size = {1: 20, 2: 17, 3: 15}.get(level, 14)
            out.append(
                f'<div style="font-size:{size}px; font-weight:600; margin:10px 0 4px;">'
                f'{_md_inline(content)}</div>'
            )
            i += 1
            continue
        if stripped.startswith(">"):
            flush_para()
            quote = stripped.lstrip(">").strip()
            out.append(
                '<div style="margin:6px 0; border-left:2px solid #d5dbe5; color:#5b6472;">'
                f'{_md_inline(quote)}</div>'
            )
            i += 1
            continue
        if stripped.startswith(("- ", "* ")):
            flush_para()
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            lis = "".join(f"<li>{_md_inline(it)}</li>" for it in items)
            out.append(f'<ul style="margin:4px 0 6px 18px;">{lis}</ul>')
            continue
        if re.match(r"^\d+[.、]\s", stripped):
            flush_para()
            items = []
            while i < len(lines) and re.match(r"^\d+[.、]\s", lines[i].strip()):
                items.append(re.sub(r"^\d+[.、]\s*", "", lines[i].strip()))
                i += 1
            lis = "".join(f"<li>{_md_inline(it)}</li>" for it in items)
            out.append(f'<ol style="margin:4px 0 6px 18px;">{lis}</ol>')
            continue
        para.append(line)
        i += 1
    flush_para()
    return "".join(out) or "<div></div>"


class GoldTextButton(QPushButton):
    """金色 3D 立体字按钮：白底浅金渐变 + 金色渐变文字 + 阴影/高光，Win/mac 一致。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(124)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(17)
        self.setFont(font)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        pressed = self.isDown()
        hover = self.underMouse() and not pressed

        bg = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
        if pressed:
            bg.setColorAt(0, QColor("#FBEFC4"))
            bg.setColorAt(1, QColor("#EFD48C"))
        elif hover:
            bg.setColorAt(0, QColor("#FFFEF8"))
            bg.setColorAt(1, QColor("#FCF0C8"))
        else:
            bg.setColorAt(0, QColor("#FFFDF5"))
            bg.setColorAt(1, QColor("#FBF1D0"))
        painter.setPen(QPen(QColor("#D3A93F"), 1.2))
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 11, 11)

        font = self.font()
        painter.setFont(font)
        text = self.text()

        # 阴影（右下）
        shadow_pen = QPen(QColor(120, 82, 10, 120))
        shadow_pen.setWidth(0)
        painter.setPen(shadow_pen)
        painter.drawText(rect.translated(1, 2), Qt.AlignmentFlag.AlignCenter, text)

        # 高光（左上）
        highlight_pen = QPen(QColor(255, 252, 226, 180))
        highlight_pen.setWidth(0)
        painter.setPen(highlight_pen)
        painter.drawText(rect.translated(0, -1), Qt.AlignmentFlag.AlignCenter, text)

        # 金色渐变填充
        gold = QLinearGradient(QPointF(rect.left(), rect.top()), QPointF(rect.left(), rect.bottom()))
        gold.setColorAt(0.0, QColor("#FFF6C2"))
        gold.setColorAt(0.35, QColor("#F5CB4E"))
        gold.setColorAt(0.72, QColor("#DDA41B"))
        gold.setColorAt(1.0, QColor("#A96C08"))
        gold_pen = QPen(QBrush(gold), 0)
        painter.setPen(gold_pen)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


class CopilotThread(QThread):
    """后台流式请求：逐段回传内容，可中途停止，不阻塞界面。"""

    delta = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, cfg: dict, messages: list[dict]):
        super().__init__()
        self._cfg = cfg
        self._messages = messages
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            text = CopilotAgent(self._cfg).stream(self._messages, self.delta.emit, self._stop.is_set)
            self.finished_ok.emit(text)
        except Exception as exc:
            if self._stop.is_set():
                self.finished_ok.emit("")
            else:
                self.failed.emit(net_error_text(exc))


class DeepAnalysisThread(QThread):
    """全量内容分析：会话卡片分批提炼 → 合并成最终报告（不再受 200 条限制）。"""

    progress = pyqtSignal(int, int, str)
    delta = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, cfg: dict, question: str, filter_text: str, batches: list[str],
                 mode: str = "card", covered: int = 0):
        super().__init__()
        self._cfg = cfg
        self._question = question
        self._filter_text = filter_text
        self._batches = [str(b) for b in batches if str(b).strip()] or [""]
        self._mode = mode
        self._covered = covered or len(self._batches)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            agent = CopilotAgent(self._cfg)
            total_batches = len(self._batches)
            findings: list[str] = []
            for index, payload in enumerate(self._batches, 1):
                if self._stop.is_set():
                    self.finished_ok.emit("")
                    return
                self.progress.emit(index - 1, total_batches, f"正在分析第 {index}/{total_batches} 批")
                text = agent.complete(build_map_messages(self._question, payload, index, total_batches,
                                                         self._mode))
                if text.strip():
                    findings.append(f"【第{index}批】{text.strip()}")
                self.progress.emit(index, total_batches, f"第 {index}/{total_batches} 批完成")
            if self._stop.is_set():
                self.finished_ok.emit("")
                return
            self.progress.emit(total_batches, total_batches, "正在合并各批结论…")
            messages = build_reduce_messages(self._question, self._filter_text,
                                             "\n\n".join(findings), self._covered, total_batches)
            final = agent.stream(messages, self.delta.emit, self._stop.is_set)
            self.finished_ok.emit(final)
        except Exception as exc:
            if self._stop.is_set():
                self.finished_ok.emit("")
            else:
                self.failed.emit(net_error_text(exc))


class DeductionDialog(QDialog):
    """客服扣分率：按客服统计有扣分咨询占比。"""

    def __init__(self, rows: list[dict], parent=None):
        super().__init__(parent)
        self.setObjectName("storeDialog")
        self.setWindowTitle("客服扣分率")
        self.resize(760, 540)
        lay = QVBoxLayout(self)
        hint = QLabel("扣分率 = 有扣分的咨询数 ÷ 该客服咨询总数；合并模式下按参与客服分别计入。")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        data: dict[str, dict] = {}
        for row in rows:
            agents = [a for a in str(row.get("agent") or "").split("、") if a]
            dims = row.get("deductions") or {}
            deduction = sum(float(v or 0) for v in dims.values())
            has = deduction > 0 or bool(row.get("fatal_candidates"))
            for agent in agents:
                info = data.setdefault(agent, {"total": 0, "has": 0, "deduction": 0.0})
                info["total"] += 1
                info["has"] += 1 if has else 0
                info["deduction"] += deduction
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["客服", "咨询数", "有扣分", "扣分率", "总扣分", "平均扣分"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in [(1, 90), (2, 90), (3, 100), (4, 90), (5, 100)]:
            table.setColumnWidth(col, width)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        ordered = sorted(data.items(),
                         key=lambda kv: (kv[1]["has"] / kv[1]["total"] if kv[1]["total"] else 0,
                                         kv[1]["deduction"]), reverse=True)
        for agent, info in ordered:
            index = table.rowCount()
            table.insertRow(index)
            total = info["total"] or 1
            values = [agent, str(info["total"]), str(info["has"]),
                      f"{info['has'] / total * 100:.1f}%", f"{info['deduction']:g}",
                      f"{info['deduction'] / total:.1f}"]
            for col, value in enumerate(values):
                table.setItem(index, col, QTableWidgetItem(value))
        lay.addWidget(table, 1)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close)
        lay.addLayout(row)


class AITestThread(QThread):
    """异步测试 AI 接口，避免界面卡住。"""

    finished_test = pyqtSignal(bool, str)

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg

    def run(self):
        try:
            from qc_engine.ai.client import AIClient
            ok, msg = AIClient(self._cfg).test_connection()
        except Exception as exc:
            ok, msg = False, _exc_cn(exc)
        self.finished_test.emit(ok, msg)


class StatsThread(QThread):
    """全量统计：生成只读 SQL → 校验 → 执行 → 把结果交给模型流式总结。"""

    sql_ready = pyqtSignal(str, int)
    delta = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, cfg: dict, question: str, filters: dict, filter_text: str, db_path: Path):
        super().__init__()
        self._cfg = cfg
        self._question = question
        self._filters = filters
        self._filter_text = filter_text
        self._db_path = db_path
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            sql = stats_ai.generate_sql(self._cfg, self._question, self._filter_text)
            ok, err = stats_ai.validate_sql(sql)
            if not ok:
                sql = stats_ai.generate_sql(self._cfg, self._question, self._filter_text, feedback=err)
                ok, err = stats_ai.validate_sql(sql)
            if not ok:
                self.failed.emit(f"统计查询生成失败（{err}）。可以换个问法，或先缩小筛选范围再试。")
                return
            view_sql, params = stats_ai.build_view(self._filters)
            result = stats_ai.run_sql(self._db_path, view_sql, params, sql)
            self.sql_ready.emit(sql, result["count"])
            if self._stop.is_set():
                self.finished_ok.emit("")
                return
            messages = stats_ai.build_answer_messages(self._question, self._filter_text, sql, result)
            text = CopilotAgent(self._cfg).stream(messages, self.delta.emit, self._stop.is_set)
            self.finished_ok.emit(text)
        except Exception as exc:
            if self._stop.is_set():
                self.finished_ok.emit("")
            else:
                self.failed.emit(stats_ai.net_error_text(exc))


class Worker(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(object)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.finished_ok.emit(self.fn(self.progress.emit))
        except Exception as exc:
            self.finished_ok.emit({"error": _exc_cn(exc)})


class DetailDialog(QDialog):
    """会话详情：聊天 + 扣分明细 + AI 判定 + 复核操作。"""

    def __init__(self, row: dict, runner: QCRunner | None, on_review=None, on_apply_ai=None, light: bool = False):
        super().__init__()
        self.setWindowTitle("会话详情")
        self.resize(1000, 820)
        self.setMinimumSize(880, 640)
        self.setObjectName("detailDialog")
        self.setAutoFillBackground(True)
        self.row = row
        self.runner = runner
        self.on_review = on_review
        self.on_apply_ai = on_apply_ai
        self.light = light
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)

        dims_all = row.get("dimensions") or {}
        parts = []
        for code in SCORE_DIM_ORDER:
            dim = dims_all.get(code) or {}
            label = DIM_CN.get(code, code)
            if dim.get("status") == "ai_pending":
                parts.append(f"{label} 待AI质检")
            elif dim.get("score_ratio") is not None:
                tier = dim.get("tier_label") or ""
                parts.append(f"{label} {tier} {dim.get('points', '-')}/{dim.get('total', '-')}"
                             f"（{round(float(dim.get('score_ratio')) * 100)}%）")
        dim_lines = "    ".join(parts) or "无评分数据"
        ai_line = f"智能判定：{AI_CN.get(row.get('ai_judgment') or row.get('ai_status'), '待复核')}"
        if row.get("ai_reason"):
            ai_line += f"（{row['ai_reason'][:60]}）"
        fatal = row.get("fatal_candidates") or []
        fatal_line = f"｜ 致命候选 {len(fatal)} 项" if fatal else ""
        session_count = int(row.get("_session_count") or 1)
        merged_line = f"｜ 合并 {session_count} 次咨询" if session_count > 1 else ""
        cust_name = _customer_label(row)
        cust_id = str(row.get("customer") or "").strip()
        cust_line = f"{cust_name}（{cust_id}）" if cust_id and cust_id != cust_name else cust_name
        final_score_value = _display_score(row)
        rating = _rating_label(final_score_value)
        head = QLabel(
            f"客服 {row['agent'] or '-'} ｜ 客户 {cust_line} ｜ 店铺 {row['store_id'] or '-'} ｜ 时间 {row['first_message_at']}{merged_line} ｜ 型号 {(row['excel_labels'].get('model') or '').strip() or '-'} ｜ 评级 {rating}\n"
            f"阶段 {STAGE_CN.get(row['service_stage'], '-')} ｜ {VALID_CN.get(row['validity'], '-')} ｜ 商机 {row['lead_level'] or '-'} ｜ "
            f"电销 {'是' if row['tele_sales_lead'] else '否'} ｜ 计算分 {row['calculated_score'] if row['calculated_score'] is not None else '-'} ｜ 最终分 {_display_score(row) if _display_score(row) is not None else '-'} ｜ 复核 {REVIEW_CN.get(row['review_status'], '待复核')}{fatal_line}\n"
            f"维度得分：{dim_lines}\n{ai_line}"
        )
        head.setObjectName("detailHeader")
        head.setWordWrap(True)
        lay.addWidget(head)

        if row.get("reason_codes"):
            rc = QLabel("判定原因：" + "、".join(_reason_label(code) for code in row["reason_codes"]))
            rc.setObjectName("detailMeta")
            rc.setWordWrap(True)
            lay.addWidget(rc)

        # AI 引用证据展示（AI 判断时引用的原文）
        ai_evidence = row.get("ai_evidence") or []
        if ai_evidence:
            ev_lines = []
            for ev in ai_evidence:
                if isinstance(ev, dict):
                    ref = ev.get("message_ref", "")
                    quote = str(ev.get("quote", "")).strip()
                    if quote:
                        ev_lines.append(f"  · {_ref_cn(ref)}：{quote[:80]}")
            if ev_lines:
                ev_text = "智能判定依据：\n" + "\n".join(ev_lines)
                ev = QLabel(ev_text)
                ev.setObjectName("detailEvidence")
                ev.setWordWrap(True)
                lay.addWidget(ev)

        # 聊天区顶部：客户与客服名称（不随聊天滚动，始终可见）
        chat_head = QFrame(); chat_head.setObjectName("chatHeader")
        chl = QHBoxLayout(chat_head); chl.setContentsMargins(12, 7, 12, 7); chl.setSpacing(8)
        customer_name = _customer_label(row)
        name_lab = QLabel(f"客户：{customer_name}")
        name_lab.setStyleSheet("font-size:13px;font-weight:600;color:#2a2f36;background:transparent;")
        name_lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        name_lab.setToolTip("可选中复制；点右侧按钮可一键复制客户名")
        copy_btn = QPushButton("复制客户名")
        copy_btn.setObjectName("copyNameBtn")
        copy_btn.setFixedHeight(26)
        copy_btn.setToolTip("把客户名称复制到剪贴板，方便粘贴到表格")
        copy_btn.clicked.connect(
            lambda _=False: (QApplication.clipboard().setText(customer_name), copy_btn.setText("已复制")))
        agent_lab = QLabel(f"客服：{row.get('agent') or '-'}")
        agent_lab.setStyleSheet("font-size:12px;color:#8a9099;background:transparent;")
        chl.addWidget(name_lab); chl.addWidget(copy_btn); chl.addStretch(1); chl.addWidget(agent_lab)
        lay.addWidget(chat_head)

        # 微信风格聊天重现：浅灰底、绿/白气泡、头像与时间分组
        chat = ChatView(row)
        chat.setMinimumHeight(420)
        lay.addWidget(chat, 1)

        advice = QLabel(f"建议：{_advice(row)}")
        advice.setObjectName("detailAdvice")
        advice.setWordWrap(True)
        lay.addWidget(advice)

        suggest_stage = str(row.get("ai_suggest_stage") or "keep")
        suggest_validity = str(row.get("ai_suggest_validity") or "keep")
        stage_change = suggest_stage != "keep" and suggest_stage != str(row.get("service_stage") or "")
        valid_change = suggest_validity != "keep" and suggest_validity != str(row.get("validity") or "")
        if stage_change or valid_change:
            parts = []
            if stage_change:
                parts.append(f"阶段 {STAGE_CN.get(row.get('service_stage'), '-')} → {STAGE_CN.get(suggest_stage, suggest_stage)}")
            if valid_change:
                parts.append(f"有效性 {VALID_CN.get(row.get('validity'), '-')} → {VALID_CN.get(suggest_validity, suggest_validity)}")
            reason = str(row.get("ai_suggest_reason") or row.get("ai_reason") or "").strip()
            ai_box = QLabel("AI 建议改判：" + "；".join(parts) + (f"\n依据：{reason}" if reason else ""))
            ai_box.setObjectName("detailAiSuggestion")
            ai_box.setWordWrap(True)
            lay.addWidget(ai_box)
            adopt = QPushButton("采纳 AI 建议改判")
            adopt.setObjectName("copyNameBtn")
            adopt.setToolTip("采纳后修改阶段/有效性并写入审计日志，可再次人工复核修正")

            def _adopt():
                answer = QMessageBox.question(
                    self, "采纳 AI 建议",
                    "确定按 AI 建议修改这条会话的判定吗？\n\n" + "；".join(parts),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                if self.on_apply_ai is not None:
                    self.on_apply_ai(self.row,
                                     None if suggest_stage == "keep" else suggest_stage,
                                     None if suggest_validity == "keep" else suggest_validity,
                                     "采纳AI建议：" + (reason or "；".join(parts)))
                    self.accept()
                else:
                    QMessageBox.information(self, "提示", "当前会话不支持采纳 AI 建议。")

            adopt.clicked.connect(_adopt)
            adopt_row = QHBoxLayout()
            adopt_row.addWidget(adopt)
            adopt_row.addStretch()
            lay.addLayout(adopt_row)

        if row.get("ai_suggestion"):
            sug = QLabel("智能建议话术：" + str(row["ai_suggestion"]))
            sug.setObjectName("detailAiSuggestion")
            sug.setWordWrap(True)
            lay.addWidget(sug)

        if on_review is not None:
            score_row = QHBoxLayout()
            score_row.addWidget(QLabel("人工最终分"))
            self.score_input = QSpinBox()
            self.score_input.setRange(0, 100)
            current_score = row.get("final_score") if row.get("final_score") is not None else row.get("calculated_score")
            self.score_input.setValue(int(current_score or 0))
            self.score_input.setSuffix(" 分")
            self.score_input.setToolTip("可直接修改最终分数")
            self.score_input.valueChanged.connect(self._update_score_hint)
            score_row.addWidget(self.score_input)
            self.score_hint = QLabel("")
            self.score_hint.setObjectName("detailMeta")
            score_row.addWidget(self.score_hint)
            score_row.addStretch()
            lay.addLayout(score_row)
            self._update_score_hint()
            btn_row = QHBoxLayout()
            self.note_input = QLineEdit(); self.note_input.setPlaceholderText("复核说明（改判理由）")
            btn_row.addWidget(self.note_input, 1)
            btn_pass = QPushButton("确认合格")
            btn_fail = QPushButton("改判不合格")
            fatal_score = int(((runner.scoring.config.get("fatal_item") or {}).get("final_score_after_confirmation", 39))
                              if runner else 39)
            btn_fatal = QPushButton(f"确认致命项({fatal_score}分)")
            btn_pass.clicked.connect(lambda: self._review("合格", self.score_input.value(), False))
            btn_fail.clicked.connect(lambda: self._review("不合格", self.score_input.value(), False))
            btn_fatal.clicked.connect(lambda: self._review("不合格", fatal_score, True))
            btn_row.addWidget(btn_pass); btn_row.addWidget(btn_fail); btn_row.addWidget(btn_fatal)
            lay.addLayout(btn_row)

    def _update_score_hint(self, *_):
        if not hasattr(self, "score_hint"):
            return
        base = self.row.get("calculated_score")
        base_txt = str(base) if base is not None else "无"
        self.score_hint.setText(f"原计算分 {base_txt}；点下方按钮保存后，总览分数立即更新")

    def _review(self, status: str, score, fatal: bool):
        if self.runner and self.on_review is not None:
            if fatal:
                fatal_score = int(((self.runner.scoring.config.get("fatal_item") or {}).get("final_score_after_confirmation", 39))
                                  if getattr(self, "runner", None) else 39)
                self.score_input.setValue(fatal_score)
                score = fatal_score
            else:
                score = self.score_input.value()
            self.on_review(self.row, status, score, self.note_input.text().strip() or "人工复核", fatal)
            self.accept()
        else:
            QMessageBox.information(self, "提示", "当前会话不支持人工复核。")


# ---------------- 爆单一铲：AI 质检副驾（第一步：界面 + 胶囊） ----------------

TEMPLATES_DIR = APP_DIR / "templates"
CAPSULES_PATH = TEMPLATES_DIR / "capsules.json"

DEFAULT_CAPSULES = [
    {
        "id": "warranty_check",
        "icon": "🛡️",
        "title": "质保是否说清",
        "prompt": (
            "检查对话中客服是否明确告知了质保年限、起算日（收货次日 vs 激活日 vs 出货日）、是否覆盖屏幕和触摸。"
            "如果有模糊表述（“放心，有质保的”），提取原句；如果客户主动问了但客服回避，标记为高风险。"
            "品牌A官网明确显示显示/触摸/周边部件保修期为1年，起算日优先看发票，无发票按激活日，"
            "无激活记录按SN出货日——客服如果承诺“3年质保”必须确认是否有延保套餐支撑。"
        ),
        "enabled": True,
        "default_tags": ["售后", "A级"],
    },
    {
        "id": "meeting_match",
        "icon": "📏",
        "title": "会议室场景匹配",
        "prompt": (
            "根据客户的会议室面积/人数，判断客服推荐的尺寸是否合理（10人以内→65寸，10-15人→75寸，"
            "15-30人→86寸，大型报告厅→98寸）。客户提到“投影仪老坏”“HDMI线找不到”“Mac投不上”等传统会议痛点时，"
            "客服是否顺势解释了品牌A的无线投屏/双系统/白板批注优势。"
        ),
        "enabled": True,
        "default_tags": ["售前", "A级", "B级"],
    },
    {
        "id": "competitor_compare",
        "icon": "🥊",
        "title": "竞品对比是否得当",
        "prompt": (
            "客户提到“华为”“品牌B”“海康”或其他品牌时，客服的应对话术是否专业。品牌A对华为的差异化在于："
            "白板软件成熟度更高、OPS电脑选择更丰富、第三方会议软件（腾讯会议/飞书）适配更好；"
            "对品牌B的差异化在于：品牌B偏教育场景，企业办公生态弱；对海康的差异化在于：海康白板体验一般、生态配套偏弱。"
            "如果客服只会说“我们更好”而没有具体对比点，标记为话术薄弱。"
        ),
        "enabled": True,
        "default_tags": ["售前", "B级"],
    },
    {
        "id": "opportunity_signal",
        "icon": "🔍",
        "title": "商机信号与探需",
        "prompt": (
            "在这批筛出的会话中，找出所有出现了以下信号但未被客服有效承接的对话：①主动问价格/优惠/活动；"
            "②提到“公司要采购”“老板让我看”“下个月要上”；③主动留电话/微信；④在品牌A不同型号之间犹豫。"
            "对每条会话，指出客服在哪一轮对话中错过了推进机会。"
        ),
        "enabled": True,
        "default_tags": ["A级", "B级", "未成交"],
    },
    {
        "id": "rewrite_script",
        "icon": "✍️",
        "title": "话术改写生成",
        "prompt": (
            "从这批会话中，选出3条“客户有明确意向但最终未成交”的对话。针对每条，先指出客服最后一句“把天聊死”的话，"
            "然后重写一段不超过80字的跟进话术，要求：①引用客户之前提过的具体需求；②给出一个明确的下一步动作；"
            "③语气专业但不压迫。"
        ),
        "enabled": True,
        "default_tags": ["A级", "未成交"],
    },
]


def load_capsules() -> list[dict]:
    """读取胶囊配置；首次运行写入内置的 5 个专业胶囊。"""
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if not CAPSULES_PATH.exists():
        save_capsules(DEFAULT_CAPSULES)
    try:
        data = json.loads(CAPSULES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return [dict(c) for c in DEFAULT_CAPSULES]


def save_capsules(caps: list[dict]) -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    CAPSULES_PATH.write_text(json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")


class ChatInput(QPlainTextEdit):
    """多行输入：Enter 发送，Shift+Enter 换行。"""

    send_requested = pyqtSignal()

    def keyPressEvent(self, event):
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if is_enter and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class CapsuleDialog(QDialog):
    """提示词胶囊管理：增、删、改、启用/禁用。"""

    def __init__(self, capsules: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理提示词胶囊")
        self.resize(780, 560)
        self.setObjectName("capsuleDialog")
        self.setAutoFillBackground(True)
        self.capsules = [dict(c) for c in capsules]
        self._row = -1

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        body = QHBoxLayout()
        body.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(QLabel("胶囊列表（勾选 = 启用）"))
        self.listw = QListWidget()
        self.listw.setObjectName("capsuleList")
        left.addWidget(self.listw, 1)
        row1 = QHBoxLayout()
        add = QPushButton("＋ 新增")
        rm = QPushButton("删除")
        add.clicked.connect(self._add)
        rm.clicked.connect(self._remove)
        row1.addWidget(add)
        row1.addWidget(rm)
        row1.addStretch(1)
        left.addLayout(row1)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(6)
        form = QFormLayout()
        form.setSpacing(8)
        self.icon_edit = QLineEdit()
        self.icon_edit.setMaxLength(4)
        self.icon_edit.setPlaceholderText("如 🛡️")
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("胶囊短标题，如 质保是否说清")
        self.tags_edit = QLineEdit()
        self.tags_edit.setPlaceholderText("推荐标签，逗号分隔，如 售前,A级（用于按筛选自动推荐）")
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("点击胶囊后填入输入框的完整提示词")
        self.prompt_edit.setMinimumHeight(200)
        self.enabled_box = QCheckBox("启用该胶囊")
        form.addRow("图标", self.icon_edit)
        form.addRow("标题", self.title_edit)
        form.addRow("推荐标签", self.tags_edit)
        form.addRow("提示词", self.prompt_edit)
        form.addRow("", self.enabled_box)
        right.addLayout(form, 1)
        row2 = QHBoxLayout()
        save = QPushButton("保存修改")
        save.setObjectName("primary")
        save.clicked.connect(self._save_current)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        row2.addWidget(save)
        row2.addWidget(close)
        row2.addStretch(1)
        right.addLayout(row2)
        body.addLayout(right, 2)
        lay.addLayout(body, 1)

        self.listw.currentRowChanged.connect(self._show_row)
        self.listw.itemChanged.connect(self._toggle_enabled)
        self._reload_list()

    def _reload_list(self, select: int = 0):
        self.listw.blockSignals(True)
        self.listw.clear()
        for c in self.capsules:
            item = QListWidgetItem(f"{c.get('icon', '')} {c.get('title', '')}".strip())
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if c.get("enabled", True) else Qt.CheckState.Unchecked
            )
            self.listw.addItem(item)
        self.listw.blockSignals(False)
        if self.capsules:
            self.listw.setCurrentRow(min(select, len(self.capsules) - 1))
        else:
            self._clear_form()

    def _clear_form(self):
        self._row = -1
        self.icon_edit.clear()
        self.title_edit.clear()
        self.tags_edit.clear()
        self.prompt_edit.clear()
        self.enabled_box.setChecked(True)

    def _show_row(self, row: int):
        self._row = row
        if row < 0 or row >= len(self.capsules):
            self._clear_form()
            return
        c = self.capsules[row]
        self.icon_edit.setText(str(c.get("icon", "")))
        self.title_edit.setText(str(c.get("title", "")))
        self.tags_edit.setText("，".join(c.get("default_tags") or []))
        self.prompt_edit.setPlainText(str(c.get("prompt", "")))
        self.enabled_box.setChecked(bool(c.get("enabled", True)))

    def _collect(self) -> dict:
        tags = [t.strip() for t in re.split(r"[,，]", self.tags_edit.text()) if t.strip()]
        return {
            "icon": self.icon_edit.text().strip() or "💬",
            "title": self.title_edit.text().strip() or "未命名胶囊",
            "prompt": self.prompt_edit.toPlainText().strip(),
            "enabled": self.enabled_box.isChecked(),
            "default_tags": tags,
        }

    def _save_current(self):
        if self._row < 0 or self._row >= len(self.capsules):
            return
        data = self._collect()
        if not data["prompt"]:
            QMessageBox.information(self, "提示", "提示词不能为空。")
            return
        data["id"] = self.capsules[self._row].get("id") or f"capsule_{int(datetime.now().timestamp())}"
        self.capsules[self._row] = data
        self._reload_list(self._row)

    def _add(self):
        self.capsules.append({
            "id": f"capsule_{int(datetime.now().timestamp())}",
            "icon": "💬",
            "title": "新胶囊",
            "prompt": "在这里填写提示词…",
            "enabled": True,
            "default_tags": [],
        })
        self._reload_list(len(self.capsules) - 1)

    def _remove(self):
        if not (0 <= self._row < len(self.capsules)):
            return
        title = self.capsules[self._row].get("title", "")
        if QMessageBox.question(
            self, "确认删除", f"确定删除「{title}」吗？"
        ) != QMessageBox.StandardButton.Yes:
            return
        self.capsules.pop(self._row)
        self._reload_list(max(0, self._row - 1))

    def _toggle_enabled(self, item: QListWidgetItem):
        row = self.listw.row(item)
        if 0 <= row < len(self.capsules):
            enabled = item.checkState() == Qt.CheckState.Checked
            self.capsules[row]["enabled"] = enabled
            if row == self._row:
                self.enabled_box.setChecked(enabled)


COPILOT_QSS_LIGHT = """
QLabel#copilotContext { background: rgba(109,75,255,0.07); border: 1px solid rgba(109,75,255,0.20); border-radius: 10px; padding: 8px 12px; color: #4a3a8f; font-size: 12.5px; }
QFrame#copilotSide, QFrame#copilotMain { background: rgba(255,255,255,0.62); border: 1px solid rgba(30,28,60,0.10); border-radius: 16px; }
QListWidget#copilotHistory { background: transparent; border: none; outline: none; }
QListWidget#copilotHistory::item { padding: 7px 9px; margin: 2px 0; border-radius: 9px; color: #4b5563; }
QListWidget#copilotHistory::item:hover { background: rgba(109,75,255,0.08); }
QListWidget#copilotHistory::item:selected { background: rgba(109,75,255,0.16); color: #2a2350; font-weight: 600; }
QTextBrowser#copilotView { background: #ffffff; border: 1px solid #e3e8f0; border-radius: 12px; padding: 12px; color: #1f2937; font-size: 13.5px; }
QScrollArea#capsuleBar { border: none; background: transparent; }
QWidget#capsuleHost { background: transparent; }
QPushButton#capsuleChip { min-height: 28px; padding: 0 10px; border-radius: 14px; background: #f5f2ff; border: 1px solid #ddd3ff; color: #4a37b8; font-size: 12px; }
QPushButton#capsuleChip:hover { background: #ebe5ff; border: 1px solid #c3b4ff; }
QPushButton#capsuleChip:pressed { background: #ded4ff; }
QPushButton#capsuleChip[recommended="true"] { background: #efe9ff; border: 1px solid #b79bff; font-weight: 600; }
QPlainTextEdit#copilotInput { background: #ffffff; border: 1px solid #dce3ec; border-radius: 12px; padding: 8px; color: #1f2937; font-size: 13.5px; }
QPlainTextEdit#copilotInput:focus { border: 1px solid #7b5cff; }
QDialog#copilotDialog { background: #eef2f6; }
QDialog#copilotDialog QLabel { color: #334155; }
QDialog#capsuleDialog { background: #f5f7fb; color: #1f2937; }
QDialog#capsuleDialog QLabel { color: #334155; }
QDialog#capsuleDialog QListWidget { background: #ffffff; border: 1px solid #dce3ec; border-radius: 10px; color: #1f2937; }
QDialog#capsuleDialog QListWidget::item { padding: 6px 8px; }
QDialog#capsuleDialog QListWidget::item:selected { background: rgba(109,75,255,0.16); color: #2a2350; }
QDialog#capsuleDialog QLineEdit, QDialog#capsuleDialog QPlainTextEdit { background: #ffffff; border: 1px solid #c9d4e2; border-radius: 8px; color: #1f2937; padding: 6px; }
QDialog#capsuleDialog QPushButton { background: #ffffff; border: 1px solid #c9d4e2; color: #334155; }
QDialog#capsuleDialog QPushButton:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QDialog#capsuleDialog QPushButton#primary { background: #6d4bff; border: 1px solid #6d4bff; color: #ffffff; }
QDialog#capsuleDialog QCheckBox { color: #334155; }
QScrollArea#copilotChat { background: #f7f8fa; border: 1px solid #dce3ec; border-radius: 12px; }
QWidget#copilotChatCanvas { background: #f7f8fa; }
QScrollArea#copilotChat QScrollBar:vertical { background: transparent; width: 10px; margin: 3px; }
QScrollArea#copilotChat QScrollBar::handle:vertical { background: rgba(0,0,0,0.20); border-radius: 5px; min-height: 30px; }
QScrollArea#copilotChat QScrollBar::add-line:vertical, QScrollArea#copilotChat QScrollBar::sub-line:vertical { height: 0px; }
QLabel#copilotAvatarAi { background: #ffffff; color: #8a6d1f; border: 1px solid #e8d9ab; border-radius: 17px; font-size: 16px; }
QLabel#copilotAvatarMe { background: #b7c3d4; color: #ffffff; border-radius: 17px; font-size: 12px; font-weight: 600; }
QLabel#copilotAiContent { background: transparent; color: #1f2329; font-size: 13.5px; padding: 2px 2px; }
QLabel#copilotBubbleMe { background: #95ec69; color: #14330f; border-radius: 10px; border-top-right-radius: 2px; padding: 9px 13px; font-size: 13.5px; }
QFrame#copilotThinkBox { background: transparent; border: none; border-left: 2px solid #dfe4ec; border-radius: 0px; }
QPushButton#copilotThinkToggle { background: transparent; border: none; color: #8b93a1; font-size: 12px; text-align: left; padding: 0px; }
QPushButton#copilotThinkToggle:hover { color: #5f6773; }
QPushButton#copilotDelBtn { background: transparent; border: none; color: #98a1ae; font-size: 12px; padding: 2px 6px; }
QPushButton#copilotDelBtn:hover { color: #d14b4b; }
QLabel#copilotThinkText { color: #97a0ad; font-size: 11.5px; }
"""

COPILOT_QSS_DARK = """
QLabel#copilotContext { background: rgba(123,92,255,0.16); border: 1px solid rgba(183,155,255,0.30); border-radius: 10px; padding: 8px 12px; color: rgba(255,255,255,0.86); font-size: 12.5px; }
QFrame#copilotSide, QFrame#copilotMain { background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.12); border-radius: 16px; }
QListWidget#copilotHistory { background: transparent; border: none; outline: none; }
QListWidget#copilotHistory::item { padding: 7px 9px; margin: 2px 0; border-radius: 9px; color: rgba(255,255,255,0.72); }
QListWidget#copilotHistory::item:hover { background: rgba(255,255,255,0.07); }
QListWidget#copilotHistory::item:selected { background: rgba(123,92,255,0.28); color: #ffffff; font-weight: 600; }
QTextBrowser#copilotView { background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 12px; color: rgba(255,255,255,0.90); font-size: 13.5px; }
QScrollArea#capsuleBar { border: none; background: transparent; }
QWidget#capsuleHost { background: transparent; }
QPushButton#capsuleChip { min-height: 28px; padding: 0 10px; border-radius: 14px; background: rgba(255,255,255,0.06); border: 1px solid rgba(183,155,255,0.35); color: #d9d2ff; font-size: 12px; }
QPushButton#capsuleChip:hover { background: rgba(183,155,255,0.18); border: 1px solid rgba(183,155,255,0.60); color: #ffffff; }
QPushButton#capsuleChip:pressed { background: rgba(123,92,255,0.34); }
QPushButton#capsuleChip[recommended="true"] { background: rgba(123,92,255,0.30); border: 1px solid rgba(183,155,255,0.70); font-weight: 600; }
QPlainTextEdit#copilotInput { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); border-radius: 12px; padding: 8px; color: #ffffff; font-size: 13.5px; }
QPlainTextEdit#copilotInput:focus { border: 1px solid #b79bff; }
QDialog#copilotDialog { background: #0d0f16; }
QDialog#copilotDialog QLabel { color: rgba(255,255,255,0.86); }
QDialog#capsuleDialog { background: #f5f7fb; color: #1f2937; }
QDialog#capsuleDialog QLabel { color: #334155; }
QDialog#capsuleDialog QListWidget { background: #ffffff; border: 1px solid #dce3ec; border-radius: 10px; color: #1f2937; }
QDialog#capsuleDialog QListWidget::item { padding: 6px 8px; }
QDialog#capsuleDialog QListWidget::item:selected { background: rgba(109,75,255,0.16); color: #2a2350; }
QDialog#capsuleDialog QLineEdit, QDialog#capsuleDialog QPlainTextEdit { background: #ffffff; border: 1px solid #c9d4e2; border-radius: 8px; color: #1f2937; padding: 6px; }
QDialog#capsuleDialog QPushButton { background: #ffffff; border: 1px solid #c9d4e2; color: #334155; }
QDialog#capsuleDialog QPushButton:hover { background: #eef3ff; border: 1px solid #7b8ee8; color: #334da3; }
QDialog#capsuleDialog QPushButton#primary { background: #6d4bff; border: 1px solid #6d4bff; color: #ffffff; }
QDialog#capsuleDialog QCheckBox { color: #334155; }
QScrollArea#copilotChat { background: #f7f8fa; border: 1px solid #dce3ec; border-radius: 12px; }
QWidget#copilotChatCanvas { background: #f7f8fa; }
QScrollArea#copilotChat QScrollBar:vertical { background: transparent; width: 10px; margin: 3px; }
QScrollArea#copilotChat QScrollBar::handle:vertical { background: rgba(0,0,0,0.20); border-radius: 5px; min-height: 30px; }
QScrollArea#copilotChat QScrollBar::add-line:vertical, QScrollArea#copilotChat QScrollBar::sub-line:vertical { height: 0px; }
QLabel#copilotAvatarAi { background: #ffffff; color: #8a6d1f; border: 1px solid #e8d9ab; border-radius: 17px; font-size: 16px; }
QLabel#copilotAvatarMe { background: #b7c3d4; color: #ffffff; border-radius: 17px; font-size: 12px; font-weight: 600; }
QLabel#copilotAiContent { background: transparent; color: #1f2329; font-size: 13.5px; padding: 2px 2px; }
QLabel#copilotBubbleMe { background: #95ec69; color: #14330f; border-radius: 10px; border-top-right-radius: 2px; padding: 9px 13px; font-size: 13.5px; }
QFrame#copilotThinkBox { background: transparent; border: none; border-left: 2px solid #dfe4ec; border-radius: 0px; }
QPushButton#copilotThinkToggle { background: transparent; border: none; color: #8b93a1; font-size: 12px; text-align: left; padding: 0px; }
QPushButton#copilotThinkToggle:hover { color: #5f6773; }
QPushButton#copilotDelBtn { background: transparent; border: none; color: #98a1ae; font-size: 12px; padding: 2px 6px; }
QPushButton#copilotDelBtn:hover { color: #d14b4b; }
QLabel#copilotThinkText { color: #97a0ad; font-size: 11.5px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("全量自动化客服质检系统 · 爆单一铲")
        self.resize(1360, 840)
        self.setMinimumSize(1080, 680)
        self.config_dir = APP_DIR / "config"
        self._settings = QSettings("QCConsole", "QCQualityConsole")
        self.runner = QCRunner(self.config_dir)
        self._batch_repair: dict[str, int] = {}
        try:
            self._batch_repair = self.runner.db.repair_batches()
        except Exception:
            self._batch_repair = {}
        self.records: list[dict] = load_records(self.runner.db)
        # 升级到新规则库时自动重算一次（保留 AI 判定与已完成的人工复核）
        if self.records and any(
            r.get("final_status") != "after_sale_record_only"
            and (r.get("dimensions") or {}).get("response_speed", {}).get("tier") is None
            and r.get("calculated_score") is not None
            for r in self.records
        ):
            try:
                self.runner.rescore(self.records)
                self.records = load_records(self.runner.db)
            except Exception:
                pass
        self.filtered: list[dict] = []
        self._review_pending: list[dict] = []
        self._tele_rows: list[dict] = []
        # 默认浅色（像微信一样清爽），避免一打开就是大面积深色；用户手动切换后记忆选择。
        stored_theme = self._settings.value("appTheme", None)
        self.light = True if stored_theme is None else str(stored_theme).lower() == "light"

        central = LiquidBackground()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.nav = QListWidget(); self.nav.setObjectName("nav"); self.nav.setFixedWidth(204)
        for label in ["数据导入", "质检总览", "人工复核", "电销跟进", "智能设置"]:
            QListWidgetItem(label, self.nav)
        self.nav.currentRowChanged.connect(self._switch_page)
        root.addWidget(self.nav)

        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(20, 16, 20, 18)
        content_lay.setSpacing(12)
        topbar = QFrame(); topbar.setObjectName("topbar")
        top_lay = QHBoxLayout(topbar); top_lay.setContentsMargins(16, 10, 12, 10); top_lay.setSpacing(10)
        brand_wrap = QVBoxLayout(); brand_wrap.setSpacing(1)
        brand = QLabel("全量自动化客服质检系统"); brand.setObjectName("brand")
        brand_meta = QLabel("爆单一铲 · 客服会话规则、智能与人工复核工作台"); brand_meta.setObjectName("brandMeta")
        brand_wrap.addWidget(brand); brand_wrap.addWidget(brand_meta)
        top_lay.addLayout(brand_wrap)
        top_lay.addStretch()
        theme_hint = QLabel("主题"); theme_hint.setObjectName("brandMeta")
        top_lay.addWidget(theme_hint)
        self._theme_btn = QPushButton("☼"); self._theme_btn.setObjectName("themeToggle")
        self._theme_btn.setToolTip("切换深色 / 浅色主题")
        self._theme_btn.clicked.connect(self._theme_toggle)
        top_lay.addWidget(self._theme_btn)
        content_lay.addWidget(topbar)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_import())
        self.stack.addWidget(self._page_overview())
        self.stack.addWidget(self._page_review())
        self.stack.addWidget(self._page_tele())
        self.stack.addWidget(self._page_ai())
        content_lay.addWidget(self.stack, 1)
        root.addWidget(content, 1)
        self.setCentralWidget(central)
        self._central_bg = central
        self._apply_theme()
        self.nav.setCurrentRow(1 if self.records else 0)
        self._refresh_all()

    def _theme_toggle(self):
        self.light = not self.light
        self._settings.setValue("appTheme", "light" if self.light else "dark")
        self._apply_theme()
        self._refresh_view()

    def _apply_theme(self):
        qss = (LIGHT_QSS + COPILOT_QSS_LIGHT) if self.light else (DARK_QSS + COPILOT_QSS_DARK)
        QApplication.instance().setStyleSheet(_qss(qss))
        self._central_bg.set_light(self.light)
        self.chart_lead.set_light(self.light)
        self.chart_score.set_light(self.light)
        if hasattr(self, "svc_chart_agents"):
            self.svc_chart_agents.set_light(self.light)
            self.svc_chart_dims.set_light(self.light)
        self._theme_btn.setText("☾" if self.light else "☼")
        self._theme_btn.setToolTip("切换到深色主题" if self.light else "切换到浅色主题")

    # ---------- 页面构建 ----------

    def _card(self) -> QFrame:
        return GlassCard()

    def _page_import(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(30, 30, 30, 30); lay.setSpacing(12)
        t = QLabel("数据导入"); t.setObjectName("title"); lay.addWidget(t)
        hint = QLabel("选择同期导出的一对文件：聊天记录 .log + 会话记录 .xlsx。店铺从下拉框选择（新增/删除请点「管理店铺」）；数据按店铺累积保存，重复导入自动去重。")
        hint.setObjectName("pageHint"); hint.setWordWrap(True); lay.addWidget(hint)
        form = QFormLayout()
        self.log_input = QLineEdit(); self.log_input.setReadOnly(True)
        b1 = QPushButton("选择 .log"); b1.clicked.connect(lambda: self._pick(self.log_input, "聊天记录 (*.log *.txt)"))
        w1 = QWidget(); r1 = QHBoxLayout(w1); r1.setContentsMargins(0, 0, 0, 0); r1.addWidget(self.log_input, 1); r1.addWidget(b1)
        form.addRow("聊天记录", w1)
        self.excel_input = QLineEdit(); self.excel_input.setReadOnly(True)
        b2 = QPushButton("选择 .xlsx"); b2.clicked.connect(lambda: self._pick(self.excel_input, "会话记录 (*.xlsx)"))
        w2 = QWidget(); r2 = QHBoxLayout(w2); r2.setContentsMargins(0, 0, 0, 0); r2.addWidget(self.excel_input, 1); r2.addWidget(b2)
        form.addRow("会话记录", w2)
        self.store_combo = QComboBox()
        # 只允许下拉选择，避免出现「只能手动输入、点不开列表」的困惑；新增店铺走「管理店铺」
        self.store_combo.setEditable(False)
        self.store_combo.setMinimumWidth(240)
        self.store_combo.setToolTip("点击下拉选择本次导入的店铺；如需新增或删除店铺，请点右侧「管理店铺」")
        store_row = QHBoxLayout()
        store_row.addWidget(self.store_combo, 1)
        mgr = QPushButton("管理店铺"); mgr.clicked.connect(self._manage_stores)
        store_row.addWidget(mgr)
        store_w = QWidget(); store_w.setLayout(store_row)
        form.addRow("店铺标记", store_w)
        lay.addLayout(form)
        run = QPushButton("开始质检导入"); run.setObjectName("primary"); run.clicked.connect(self._do_import)
        lay.addWidget(run)
        self.import_status = QLabel(""); self.import_status.setWordWrap(True); lay.addWidget(self.import_status)
        repaired = getattr(self, "_batch_repair", {}) or {}
        if repaired.get("removed_empty"):
            self.import_status.setText(
                f"已自动清理 {repaired['removed_empty']} 个未完成的空批次（上次导入中断残留），可以重新导入同一文件。")
        lay.addWidget(QLabel("历史批次"))
        batch_btn_row = QHBoxLayout()
        edit_batch = QPushButton("编辑选中批次")
        edit_batch.setToolTip("修改批次的店铺标记和备注；双击批次行也可以编辑")
        edit_batch.clicked.connect(self._edit_batch)
        repair_batch = QPushButton("修复空白批次")
        repair_batch.setToolTip("清理导入中断留下的空批次；有会话数据的批次不会动")
        repair_batch.clicked.connect(self._repair_batches)
        del_batch = QPushButton("删除选中批次"); del_batch.clicked.connect(self._delete_batch)
        batch_btn_row.addWidget(edit_batch); batch_btn_row.addWidget(repair_batch); batch_btn_row.addWidget(del_batch)
        batch_btn_row.addStretch()
        lay.addLayout(batch_btn_row)
        self.batch_table = QTableWidget(0, 7)
        self.batch_table.setHorizontalHeaderLabels(["批次", "店铺", "导入时间", "数据范围", "会话数", "匹配数", "备注"])
        self.batch_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 140), (1, 150), (2, 168), (4, 72), (5, 72), (6, 180)]:
            self.batch_table.setColumnWidth(col, w)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.verticalHeader().setDefaultSectionSize(34)
        self.batch_table.doubleClicked.connect(lambda _i: self._edit_batch())
        lay.addWidget(self.batch_table, 1)
        return page

    def _page_overview(self) -> QWidget:
        page = QWidget(); page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(24, 24, 24, 24); page_lay.setSpacing(8)
        head_row = QHBoxLayout()
        t = QLabel("质检总览"); t.setObjectName("title"); head_row.addWidget(t)
        head_row.addStretch(1)
        head_row.addWidget(QLabel("看板角色"))
        self.role_combo = QComboBox()
        self.role_combo.addItem("运营"); self.role_combo.addItem("客服")
        self.role_combo.setMinimumWidth(120)
        self.role_combo.currentIndexChanged.connect(self._on_role_change)
        head_row.addWidget(self.role_combo)
        page_lay.addLayout(head_row)

        # ---------- 两套看板共用筛选区 ----------
        fc = self._card(); fc.setObjectName("filterCard")
        fl = QVBoxLayout(fc); fl.setContentsMargins(12, 8, 12, 8); fl.setSpacing(6)
        row0 = QHBoxLayout(); row0.setSpacing(6)
        row1 = QHBoxLayout(); row1.setSpacing(6)
        row2 = QHBoxLayout(); row2.setSpacing(6)
        row0.addWidget(QLabel("搜索"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜客户名 / 账号 / 客服 / 商品 / 聊天内容（空格分隔多个关键词）")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(430)
        self.search_input.setToolTip("输入即筛选：支持客户名、账号、客服名、商品名称/型号、聊天内容；多个关键词用空格分隔")
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True); self.search_timer.setInterval(260)
        self.search_timer.timeout.connect(self._refresh_view)
        self.search_input.textChanged.connect(lambda _t: self.search_timer.start())
        self.search_hint = QLabel(""); self.search_hint.setStyleSheet("color:#7a6bb5;font-size:12px;")
        row0.addWidget(self.search_input, 1); row0.addWidget(self.search_hint); row0.addStretch(1)
        self.f_store = QComboBox(); self.f_agent = QComboBox(); self.f_product = QComboBox()
        self.f_stage = QComboBox(); self.f_lead = QComboBox(); self.f_valid = QComboBox()
        self.f_score = QComboBox(); self.f_deduction = QComboBox()
        self.f_agent.setMinimumWidth(210)
        self.f_agent.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)

        def add_filter(combo, label, items, row):
            row.addWidget(QLabel(label))
            combo.addItems(items)
            combo.setMinimumWidth(210 if combo is self.f_agent else 96)
            combo.currentIndexChanged.connect(self._refresh_view)
            row.addWidget(combo)

        for combo, label, items, row in [
            (self.f_store, "店铺", ["全部"], row1), (self.f_agent, "客服", ["全部"], row1),
            (self.f_product, "产品", ["全部"], row1),
            (self.f_stage, "阶段", ["全部", "售前", "售后", "待复核"], row1),
            (self.f_lead, "商机", ["全部", "A", "B", "C", "无"], row1),
            (self.f_valid, "有效", ["全部", "有效", "无效", "待复核"], row2),
            (self.f_score, "分数", ["全部", "90+", "75-89", "60-74", "<60", "无分数"], row2),
            (self.f_deduction, "扣分", ["全部", "有扣分", "无扣分", "致命候选"] + [f"{v}扣分" for v in DIM_CN.values()], row2),
        ]:
            add_filter(combo, label, items, row)
        self.btn_clear_filter = QPushButton("清除筛选")
        self.btn_clear_filter.setToolTip("一键恢复全部筛选条件（日期恢复为数据全范围）")
        self.btn_clear_filter.clicked.connect(self._clear_filters)
        row1.addWidget(self.btn_clear_filter); row1.addStretch(1)
        self.f_merge = QCheckBox("按客户合并（一人一条）")
        self.f_merge.setChecked(True)
        self.f_merge.setToolTip("同一客户在同一店铺的多次咨询合并为一条，客服列显示参与过的所有客服")
        self.f_merge.stateChanged.connect(self._on_merge_toggle)
        row2.addWidget(self.f_merge); row2.addStretch(1)
        self.f_start = QDateEdit(); self.f_end = QDateEdit()
        for d in (self.f_start, self.f_end):
            d.setCalendarPopup(True); d.setDisplayFormat("yyyy-MM-dd"); d.setMinimumWidth(122)
            d.dateChanged.connect(self._refresh_view)
        row2.addWidget(QLabel("开始")); row2.addWidget(self.f_start)
        row2.addWidget(QLabel("结束")); row2.addWidget(self.f_end)
        legend = QLabel("浅红行 = 待复核"); legend.setStyleSheet("color:#b05a5a; font-size:12px;")
        row2.addWidget(legend)
        fl.addLayout(row0); fl.addLayout(row1); fl.addLayout(row2)
        page_lay.addWidget(fc)

        self.overview_stack = QStackedWidget()
        page_lay.addWidget(self.overview_stack, 1)

        # ================= 运营看板 =================
        ops = QWidget(); lay = QVBoxLayout(ops)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(10)
        self.ops_stats_container = QWidget()
        stat_row = QHBoxLayout(self.ops_stats_container); stat_row.setContentsMargins(0, 0, 0, 0)
        self.stat_labels = {}; self.stat_subs = {}
        for key, name in [("total", "总咨询"), ("pre", "售前"), ("post", "售后"), ("valid", "有效"),
                          ("a", "A 级"), ("b", "B 级"), ("c", "C 级"), ("tele", "电销线索"), ("avg", "售前平均分")]:
            card = self._card(); cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10)
            lab = QLabel(name); lab.setObjectName("statLabel")
            val = QLabel("-"); val.setObjectName("statValue")
            sub = QLabel(""); sub.setObjectName("statSub")
            cl.addWidget(lab); cl.addWidget(val); cl.addWidget(sub)
            stat_row.addWidget(card, 1); self.stat_labels[key] = val; self.stat_subs[key] = sub
        lay.addWidget(self.ops_stats_container)

        self.ops_charts_container = QWidget()
        chart_row = QHBoxLayout(self.ops_charts_container); chart_row.setContentsMargins(0, 0, 0, 0)
        self.chart_lead = BarChart("商机等级分布")
        self.chart_score = BarChart("售前评分分布")
        for c in (self.chart_lead, self.chart_score):
            card = self._card(); cl = QVBoxLayout(card); cl.setContentsMargins(8, 8, 8, 8); cl.addWidget(c)
            chart_row.addWidget(card, 1)
        self.chart_lead.barClicked.connect(self._filter_by_lead_index)
        self.chart_score.barClicked.connect(self._filter_by_score_index)
        lay.addWidget(self.ops_charts_container)

        btn_row = QHBoxLayout()
        ai_run = QPushButton("智能批量质检可疑会话"); ai_run.clicked.connect(self._ai_review_batch)
        ai_all = QPushButton("全量智能质检"); ai_all.clicked.connect(self._ai_review_all)
        ai_all.setToolTip("对当前筛选的全部会话逐条调用 AI 质检（含规则已判定的会话，已人工复核完成的会跳过）")
        ai_btn = QPushButton("智能总结当前筛选"); ai_btn.clicked.connect(self._ai_summarize)
        ded_btn = QPushButton("客服扣分率")
        ded_btn.setToolTip("按客服统计扣分占比（有扣分咨询 ÷ 总咨询）")
        ded_btn.clicked.connect(self._open_deduction_dialog)
        exp = QPushButton("导出 Excel"); exp.clicked.connect(self._export_excel)
        btn_row.addWidget(ai_run); btn_row.addWidget(ai_all); btn_row.addWidget(ai_btn); btn_row.addWidget(ded_btn)
        std_btn = QPushButton("评分规则")
        self.std_btn = std_btn
        std_btn.setToolTip("查看评分规则与各档位详细标准")
        std_btn.clicked.connect(self._open_scoring_standard)
        btn_row.addWidget(std_btn)
        self.ops_full_btn = QPushButton("⛶ 放大列表")
        self.ops_full_btn.setCheckable(True)
        self.ops_full_btn.setToolTip("隐藏统计与图表，放大明细表；再次点击缩回")
        self.ops_full_btn.toggled.connect(self._toggle_ops_fullscreen)
        btn_row.addWidget(self.ops_full_btn)
        col_btn = QPushButton("列")
        col_btn.setToolTip("显示/隐藏表格列（类似 Excel 隐藏列）")
        col_btn.clicked.connect(lambda: self._show_column_menu(self.table, col_btn))
        btn_row.addWidget(col_btn)
        copilot_btn = GoldTextButton("爆单一铲")
        copilot_btn.setToolTip("打开 AI 质检副驾（默认分析当前筛选出的会话）")
        copilot_btn.clicked.connect(self._open_copilot)
        btn_row.addWidget(copilot_btn)
        btn_row.addStretch(); btn_row.addWidget(exp)
        lay.addLayout(btn_row)

        self.table = QTableWidget(0, 13)
        self.table.setHorizontalHeaderLabels(["时间", "店铺", "客服", "客户", "产品", "商品名称", "阶段", "有效", "商机", "分数", "智能判定", "留资线索", "建议"])
        self.table.horizontalHeader().setSectionResizeMode(12, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 160), (1, 64), (2, 118), (3, 132), (4, 86), (5, 214), (6, 54), (7, 54), (8, 44), (9, 46), (10, 88), (11, 132)]:
            self.table.setColumnWidth(col, w)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.doubleClicked.connect(self._open_detail)
        self._attach_header_column_menu(self.table)
        lay.addWidget(self.table, 1)
        self.overview_stack.addWidget(ops)

        # ================= 客服看板 =================
        self._build_service_page()
        self.overview_stack.addWidget(self._service_page)

        role = str(self._settings.value("dashboardRole", "运营") or "运营")
        idx = 1 if role == "客服" else 0
        self.role_combo.blockSignals(True)
        self.role_combo.setCurrentIndex(idx)
        self.role_combo.blockSignals(False)
        self.overview_stack.setCurrentIndex(idx)
        return page

    # ---------- 客服看板 ----------

    def _on_role_change(self, index: int):
        role = "客服" if index == 1 else "运营"
        self._settings.setValue("dashboardRole", role)
        if hasattr(self, "overview_stack"):
            self.overview_stack.setCurrentIndex(index)
        if index == 1:
            self._refresh_service_view()

    def _build_service_page(self):
        page = QWidget(); lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        head = QHBoxLayout()
        hint = QLabel("客服视角：统计/汇总与明细分两个子页；筛选、搜索与运营看板共用")
        hint.setObjectName("pageHint"); hint.setWordWrap(True)
        head.addWidget(hint, 1)
        rules_btn = QPushButton("评分规则")
        rules_btn.setToolTip("查看每个维度各档位的详细达标标准")
        rules_btn.clicked.connect(self._open_scoring_standard)
        head.addWidget(rules_btn)
        self.agent_all_btn = QPushButton("全部客服")
        self.agent_all_btn.setToolTip("清除客服筛选，显示全部客服")
        self.agent_all_btn.clicked.connect(lambda: (self.f_agent.setCurrentIndex(0), self._refresh_view()))
        head.addWidget(self.agent_all_btn)
        self.svc_full_btn = QPushButton("⛶ 放大列表")
        self.svc_full_btn.setCheckable(True)
        self.svc_full_btn.setToolTip("隐藏统计、切到明细子页并最大化；再次点击缩回")
        self.svc_full_btn.toggled.connect(self._toggle_service_fullscreen)
        head.addWidget(self.svc_full_btn)
        lay.addLayout(head)

        self.svc_stats_container = QWidget()
        stats_lay = QHBoxLayout(self.svc_stats_container)
        stats_lay.setContentsMargins(0, 0, 0, 0); stats_lay.setSpacing(10)
        self.svc_stat_labels: dict[str, QLabel] = {}
        for key, name in [("total", "咨询数"), ("avg", "平均分"), ("pending", "待AI质检"),
                          ("review", "待复核"), ("pass", "合格率")]:
            card = self._card(); cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10)
            lab = QLabel(name); lab.setObjectName("statLabel")
            val = QLabel("-"); val.setObjectName("statValue")
            cl.addWidget(lab); cl.addWidget(val)
            stats_lay.addWidget(card, 1); self.svc_stat_labels[key] = val
        lay.addWidget(self.svc_stats_container)

        # 基础质检 / 副驾功能保留在客服看板
        act = QHBoxLayout()
        ai_run = QPushButton("智能批量质检可疑会话"); ai_run.clicked.connect(self._ai_review_batch)
        ai_all = QPushButton("全量智能质检"); ai_all.clicked.connect(self._ai_review_all)
        ai_all.setToolTip("对当前筛选的全部会话调用 AI 质检，完成后自动重算 AI 维度分数")
        ai_sum = QPushButton("智能总结当前筛选"); ai_sum.clicked.connect(self._ai_summarize)
        ded = QPushButton("客服扣分率"); ded.clicked.connect(self._open_deduction_dialog)
        col_btn = QPushButton("列")
        col_btn.setToolTip("显示/隐藏表格列（类似 Excel 隐藏列）")
        col_btn.clicked.connect(lambda: self._show_column_menu(self.svc_table, col_btn))
        copilot = GoldTextButton("爆单一铲")
        copilot.setToolTip("打开 AI 质检副驾（默认分析当前筛选出的会话）")
        copilot.clicked.connect(self._open_copilot)
        exp = QPushButton("导出 Excel"); exp.clicked.connect(self._export_excel)
        for b in (ai_run, ai_all, ai_sum, ded, col_btn):
            act.addWidget(b)
        act.addWidget(copilot); act.addStretch(); act.addWidget(exp)
        lay.addLayout(act)

        self.svc_tabs = QTabWidget()
        self.svc_tabs.setStyleSheet(
            "QTabBar::tab { background:#eef0f7; color:#5d6780; padding:6px 18px; margin-right:4px; "
            "border-top-left-radius:6px; border-top-right-radius:6px; font-size:12.5px; }"
            "QTabBar::tab:selected { background:#f1edff; color:#4c3f8f; font-weight:600; }"
            "QTabWidget::pane { border:0; }")
        # ---- 子页1：统计 + 客服汇总 ----
        summary_tab = QWidget(); s_lay = QVBoxLayout(summary_tab)
        s_lay.setContentsMargins(0, 4, 0, 0); s_lay.setSpacing(6)
        self.svc_charts_container = QWidget()
        chart_lay = QHBoxLayout(self.svc_charts_container)
        chart_lay.setContentsMargins(0, 0, 0, 0); chart_lay.setSpacing(10)
        self.svc_chart_agents = BarChart("客服平均分对比")
        self.svc_chart_dims = BarChart("6 维平均得分率")
        self.svc_chart_agents.barClicked.connect(self._filter_agent_from_chart)
        for chart in (self.svc_chart_agents, self.svc_chart_dims):
            card = self._card(); cl = QVBoxLayout(card); cl.setContentsMargins(8, 8, 8, 8)
            cl.addWidget(chart); chart_lay.addWidget(card, 1)
        s_lay.addWidget(self.svc_charts_container)
        sum_title = QLabel("客服汇总：点击某行只看该客服；再次点「全部客服」恢复")
        sum_title.setStyleSheet("color:#5d6780;font-size:12.5px;")
        s_lay.addWidget(sum_title)
        self.agent_table = QTableWidget(0, 14)
        self.agent_table.setHorizontalHeaderLabels([
            "客服", "咨询数", "平均分", "合格率", "待AI", "待复核", "平均扣分", "有扣分",
            "响应", "必问", "话术", "问题", "留资", "优惠"])
        self.agent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, w in [(1, 60), (2, 58), (3, 60), (4, 54), (5, 60), (6, 66), (7, 60),
                       (8, 82), (9, 82), (10, 82), (11, 82), (12, 82), (13, 82)]:
            self.agent_table.setColumnWidth(col, w)
        for col in range(8, 14):
            self.agent_table.setItemDelegateForColumn(col, ScoreBarDelegate(self.agent_table))
        self.agent_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.agent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.agent_table.setAlternatingRowColors(True)
        self.agent_table.verticalHeader().setDefaultSectionSize(32)
        self.agent_table.clicked.connect(self._filter_agent_from_summary)
        s_lay.addWidget(self.agent_table, 1)
        self.svc_tabs.addTab(summary_tab, "客服汇总 & 统计")

        # ---- 子页2：咨询明细 ----
        detail_tab = QWidget(); d_lay = QVBoxLayout(detail_tab)
        d_lay.setContentsMargins(0, 4, 0, 0); d_lay.setSpacing(4)
        self.svc_table = QTableWidget(0, 15)
        self.svc_table.setHorizontalHeaderLabels([
            "时间", "客服", "客户", "产品", "阶段",
            "响应", "必问", "话术", "问题", "留资", "优惠",
            "总分", "评级", "复核", "建议"])
        self.svc_table.horizontalHeader().setSectionResizeMode(14, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 146), (1, 104), (2, 132), (3, 78), (4, 48),
                       (5, 78), (6, 78), (7, 78), (8, 78), (9, 78), (10, 78),
                       (11, 52), (12, 54), (13, 66)]:
            self.svc_table.setColumnWidth(col, w)
        self.svc_table.horizontalHeader().setStretchLastSection(True)
        for col in range(5, 11):
            self.svc_table.setItemDelegateForColumn(col, ScoreBarDelegate(self.svc_table))
        for i, code in zip(range(5, 11), SCORE_DIM_ORDER):
            item = self.svc_table.horizontalHeaderItem(i)
            if item is not None:
                item.setToolTip(f"{DIM_CN.get(code, code)}：单元格数据条 = 当前得分 / 该维度满分（100% 填满）")
        self.svc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.svc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.svc_table.setAlternatingRowColors(True)
        self.svc_table.verticalHeader().setDefaultSectionSize(36)
        self.svc_table.doubleClicked.connect(self._open_service_detail)
        self._attach_header_column_menu(self.svc_table)
        d_lay.addWidget(self.svc_table, 1)
        self.svc_tabs.addTab(detail_tab, "咨询明细")
        lay.addWidget(self.svc_tabs, 1)
        self._service_page = page

    def _column_menu(self, table: QTableWidget, parent=None) -> QMenu:
        """Excel 式列显示/隐藏菜单。"""
        menu = QMenu(parent or table)
        show_all = menu.addAction("全部显示")
        show_all.triggered.connect(lambda: [table.setColumnHidden(c, False) for c in range(table.columnCount())])
        menu.addSeparator()
        for c in range(table.columnCount()):
            header = table.horizontalHeaderItem(c)
            name = header.text() if header is not None else f"列 {c + 1}"
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(not table.isColumnHidden(c))
            action.toggled.connect(lambda checked, col=c: table.setColumnHidden(col, not checked))
        return menu

    def _show_column_menu(self, table: QTableWidget, button: QPushButton):
        menu = self._column_menu(table, button)
        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _attach_header_column_menu(self, table: QTableWidget):
        table.horizontalHeader().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        def show(pos):
            menu = self._column_menu(table, table)
            menu.exec(table.horizontalHeader().mapToGlobal(pos))

        table.horizontalHeader().customContextMenuRequested.connect(show)

    @staticmethod
    def _dim_pct(ratio) -> str:
        if ratio == "pending":
            return "待AI"
        if ratio is None:
            return "-"
        try:
            return f"{round(float(ratio) * 100)}%"
        except (TypeError, ValueError):
            return "-"

    @staticmethod
    def _dim_ratio(row: dict, code: str):
        dim = (row.get("dimensions") or {}).get(code) or {}
        if dim.get("status") == "ai_pending":
            return "pending"
        ratio = dim.get("score_ratio")
        return ratio if ratio is not None else None

    @staticmethod
    def _dim_cell(row: dict, code: str) -> str:
        return MainWindow._dim_pct(MainWindow._dim_ratio(row, code))

    @staticmethod
    def _dim_tip(row: dict, code: str) -> str:
        dim = (row.get("dimensions") or {}).get(code) or {}
        label = DIM_CN.get(code, code)
        total = dim.get("total", "-")
        if dim.get("status") == "ai_pending":
            return f"{label}（满分 {total}）：待 AI 质检后出分"
        ratio = dim.get("score_ratio")
        if ratio is None:
            return f"{label}：-"
        tier = dim.get("tier_label") or ""
        return (f"{label}（满分 {total}）：{tier}，得 {dim.get('points', '-')} 分"
                f"（{round(float(ratio) * 100)}%）；明细 {dim.get('detail') or {}}")

    @staticmethod
    def _avg_dim_ratio(rows: list[dict], code: str):
        vals = []
        pending = False
        for r in rows:
            dim = (r.get("dimensions") or {}).get(code) or {}
            if dim.get("status") == "ai_pending":
                pending = True
            elif dim.get("status") == "scored" and dim.get("score_ratio") is not None:
                vals.append(float(dim.get("score_ratio")))
        if vals:
            return round(sum(vals) / len(vals), 3)
        return "pending" if pending else None

    @staticmethod
    def _avg_dim_pct(rows: list[dict], code: str):
        return MainWindow._dim_pct(MainWindow._avg_dim_ratio(rows, code))

    def _agent_summary_rows(self) -> list[dict]:
        records = self._apply_filter(skip_agent=True)
        groups: dict[str, list[dict]] = {}
        for r in records:
            agent = str(r.get("agent") or "").strip() or "未识别"
            groups.setdefault(agent, []).append(r)
        rows = []
        for agent, items in groups.items():
            scores = [s for s in (_display_score(r) for r in items) if s is not None]
            total = len(items)
            deductions = [sum(float(v or 0) for v in (r.get('deductions') or {}).values()) for r in items]
            rows.append({
                "agent": agent,
                "total": total,
                "avg": round(sum(scores) / len(scores), 1) if scores else "-",
                "pass": f"{(sum(1 for r in items if r.get('final_status') == '合格') / total * 100):.0f}%" if total else "-",
                "pending": sum(1 for r in items if r.get("final_status") == "ai_pending"),
                "review": sum(1 for r in items if r.get("review_status") == "pending"),
                "avg_deduct": round(sum(deductions) / len(deductions), 1) if deductions else 0,
                "dims": {code: self._avg_dim_ratio(items, code) for code in SCORE_DIM_ORDER},
                "deducted": f"{(sum(1 for d in deductions if d > 0) / total * 100):.0f}%" if total else "-",
            })
        rows.sort(key=lambda x: (-x["total"], str(x["agent"])))
        return rows

    def _refresh_service_view(self):
        if not hasattr(self, "svc_table"):
            return
        rows = getattr(self, "filtered", []) or []
        total = len(rows)
        scores = [s for s in (_display_score(r) for r in rows) if s is not None]
        avg = round(sum(scores) / len(scores), 1) if scores else "-"
        pending = sum(1 for r in rows if r.get("final_status") == "ai_pending")
        review = sum(1 for r in rows if r.get("review_status") == "pending")
        passed = sum(1 for r in rows if r.get("final_status") == "合格")
        for key, value in {"total": total, "avg": avg, "pending": pending,
                           "review": review,
                           "pass": f"{(passed / total * 100):.0f}%" if total else "0%"}.items():
            self.svc_stat_labels[key].setText(str(value))

        agent_rows = self._agent_summary_rows()
        selected_agent = self.f_agent.currentData() or "全部"
        self.agent_table.setRowCount(0)
        for info in agent_rows:
            row = self.agent_table.rowCount(); self.agent_table.insertRow(row)
            vals = [info["agent"], info["total"], info["avg"], info["pass"], info["pending"], info["review"],
                    info["avg_deduct"], info["deducted"]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v)); item.setToolTip(str(v))
                self.agent_table.setItem(row, c, item)
            for c, code in zip(range(8, 14), SCORE_DIM_ORDER):
                ratio = info["dims"][code]
                item = QTableWidgetItem(self._dim_pct(ratio))
                item.setData(Qt.ItemDataRole.UserRole, ratio)
                item.setToolTip(f"{DIM_CN.get(code, code)} 平均得分率：{self._dim_pct(ratio)}")
                self.agent_table.setItem(row, c, item)
            agent_item = self.agent_table.item(row, 0)
            agent_item.setData(Qt.ItemDataRole.UserRole, info["agent"])
            agent_item.setText(_short_agent_label(info["agent"]))
            if selected_agent != "全部" and info["agent"] == selected_agent:
                for c in range(14):
                    self.agent_table.item(row, c).setBackground(QColor("#EEE9FF"))

        # 统计图：客服平均分 + 6 维平均得分率
        chart_rows = [r for r in agent_rows if isinstance(r["avg"], (int, float))]
        self._svc_chart_agents = [r["agent"] for r in chart_rows]
        self.svc_chart_agents.set_data(
            [_short_agent_label(r["agent"]) for r in chart_rows],
            [max(0, int(round(float(r["avg"])))) for r in chart_rows],
            ["#7b5cff", "#38e8ff", "#b79bff", "#f0a94b", "#4dabf7", "#e05a5a"],
            display="value", suffix="分")
        dim_vals = []
        for code in SCORE_DIM_ORDER:
            ratio = self._avg_dim_ratio(rows, code)
            dim_vals.append(round(float(ratio) * 100) if isinstance(ratio, float) else 0)
        self.svc_chart_dims.set_data(
            [SCORE_DIM_SHORT[c] for c in SCORE_DIM_ORDER], dim_vals,
            ["#38e8ff", "#7b5cff", "#b79bff", "#ff8fab", "#4dabf7", "#f0a94b"],
            display="value", suffix="%")

        self.svc_table.setRowCount(0)
        for r in rows:
            row = self.svc_table.rowCount(); self.svc_table.insertRow(row)
            agent_full = str(r.get("agent") or "")
            agent_short = "、".join(_short_agent_label(a.strip()) for a in agent_full.split("、") if a.strip()) or "-"
            score = _display_score(r)
            rating = _rating_label(score)
            if r.get("final_status") == "ai_pending":
                rating = "待AI"
            vals = [
                r.get("first_message_at") or "", agent_short, _customer_label(r),
                _product_label(r), STAGE_CN.get(r.get("service_stage"), ""),
                "", "", "", "", "", "",
                f"{score:g}" if isinstance(score, (int, float)) else "-",
                rating, REVIEW_CN.get(r.get("review_status"), "-"), _advice(r)[:46],
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v)); item.setToolTip(str(v))
                self.svc_table.setItem(row, c, item)
            for c, code in zip(range(5, 11), SCORE_DIM_ORDER):
                ratio = self._dim_ratio(r, code)
                item = self.svc_table.item(row, c)
                item.setText(self._dim_pct(ratio))
                item.setData(Qt.ItemDataRole.UserRole, ratio)
                item.setToolTip(self._dim_tip(r, code))
            if r.get("review_status") == "pending":
                for c in range(15):
                    self.svc_table.item(row, c).setBackground(QColor("#FFF0F0"))

    def _filter_agent_from_chart(self, index: int):
        agents = getattr(self, "_svc_chart_agents", [])
        if 0 <= index < len(agents):
            target = agents[index]
            pos = self.f_agent.findData(target)
            if pos >= 0:
                self.f_agent.setCurrentIndex(pos)

    def _filter_agent_from_summary(self, index):
        item = self.agent_table.item(index.row(), 0)
        if item is None:
            return
        full = str(item.data(Qt.ItemDataRole.UserRole) or item.text())
        idx = self.f_agent.findData(full)
        if idx < 0:
            idx = self.f_agent.findData("全部") if full == "全部" else self.f_agent.findText(item.text())
        if idx >= 0:
            self.f_agent.setCurrentIndex(idx)

    def _open_service_detail(self, index):
        row = index.row()
        if 0 <= row < len(getattr(self, "filtered", [])):
            DetailDialog(self.filtered[row], self.runner, self._save_review_cb,
                         self._apply_ai_cb).exec()
            self._refresh_all()

    def _toggle_service_fullscreen(self, checked: bool):
        if not hasattr(self, "svc_stats_container"):
            return
        if checked:
            self._svc_saved_geometry = self.geometry()
            self._svc_saved_maximized = self.isMaximized()
            self._svc_saved_tab = self.svc_tabs.currentIndex()
            self.svc_stats_container.hide()
            self.svc_tabs.setCurrentIndex(1)
            self.showMaximized()
            self.svc_full_btn.setText("⤡ 缩回列表")
        else:
            self.svc_stats_container.show()
            self.svc_tabs.setCurrentIndex(getattr(self, "_svc_saved_tab", 0))
            if not getattr(self, "_svc_saved_maximized", False):
                self.showNormal()
                if hasattr(self, "_svc_saved_geometry"):
                    self.setGeometry(self._svc_saved_geometry)
            self.svc_full_btn.setText("⛶ 放大列表")

    def _toggle_ops_fullscreen(self, checked: bool):
        if not hasattr(self, "ops_stats_container"):
            return
        if checked:
            self._ops_saved_geometry = self.geometry()
            self._ops_saved_maximized = self.isMaximized()
            self.ops_stats_container.hide()
            self.ops_charts_container.hide()
            self.showMaximized()
            self.ops_full_btn.setText("⤡ 缩回列表")
        else:
            self.ops_stats_container.show()
            self.ops_charts_container.show()
            if not getattr(self, "_ops_saved_maximized", False):
                self.showNormal()
                if hasattr(self, "_ops_saved_geometry"):
                    self.setGeometry(self._ops_saved_geometry)
            self.ops_full_btn.setText("⛶ 放大列表")

    def _page_review(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(24, 24, 24, 24); lay.setSpacing(10)
        t = QLabel("人工复核"); t.setObjectName("title"); lay.addWidget(t)
        hint = QLabel("规则初筛标记为可疑的会话在此确认或改判；双击行进入会话详情，可直接修改最终分并保存。也可点「一键复核全部」按当前判断批量确认（待AI/售后记录会跳过），复核后总览最终数据立即更新，所有操作写入审计日志。")
        hint.setObjectName("pageHint"); hint.setWordWrap(True); lay.addWidget(hint)
        btn_row = QHBoxLayout()
        refresh = QPushButton("刷新队列"); refresh.clicked.connect(self._refresh_all)
        bulk = QPushButton("一键复核全部")
        bulk.setToolTip("按当前最终分数/状态确认所有可确认的待复核会话；待AI质检/售后记录会跳过")
        bulk.clicked.connect(self._bulk_confirm_reviews)
        btn_row.addWidget(refresh); btn_row.addWidget(bulk); btn_row.addStretch()
        self.review_count_label = QLabel(""); btn_row.addWidget(self.review_count_label)
        lay.addLayout(btn_row)
        self.review_table = QTableWidget(0, 8)
        self.review_table.setHorizontalHeaderLabels(["时间", "客服", "阶段", "有效", "商机", "分数", "原因", "复核状态"])
        self.review_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 168), (1, 74), (2, 60), (3, 64), (4, 54), (5, 56), (7, 84)]:
            self.review_table.setColumnWidth(col, w)
        self.review_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.review_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.review_table.setAlternatingRowColors(True)
        self.review_table.verticalHeader().setDefaultSectionSize(36)
        self.review_table.doubleClicked.connect(self._open_review_detail)
        lay.addWidget(self.review_table, 1)
        return page

    def _page_tele(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(24, 24, 24, 24); lay.setSpacing(10)
        t = QLabel("电销线索跟进"); t.setObjectName("title"); lay.addWidget(t)
        hint = QLabel("已获取电话号码或联系方式的会话汇总，建议优先跟进。双击查看聊天详情。")
        hint.setObjectName("pageHint"); hint.setWordWrap(True); lay.addWidget(hint)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("线索类型"))
        self.f_tele_kind = QComboBox()
        self.f_tele_kind.addItems(["全部", "有留资", "空白", "电话", "微信", "QQ", "邮箱", "其他"])
        self.f_tele_kind.currentIndexChanged.connect(self._refresh_tele)
        filter_row.addWidget(self.f_tele_kind)
        self.tele_hint = QLabel("")
        self.tele_hint.setObjectName("pageHint")
        filter_row.addWidget(self.tele_hint)
        filter_row.addStretch()
        exp = QPushButton("导出 Excel")
        exp.clicked.connect(self._export_tele)
        filter_row.addWidget(exp)
        lay.addLayout(filter_row)
        self.tele_table = QTableWidget(0, 8)
        self.tele_table.setHorizontalHeaderLabels(["时间", "店铺", "客服", "客户", "产品", "线索类型", "留资线索", "建议"])
        self.tele_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 158), (1, 150), (2, 74), (3, 104), (4, 84), (5, 76), (6, 130)]:
            self.tele_table.setColumnWidth(col, w)
        self.tele_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tele_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tele_table.setAlternatingRowColors(True)
        self.tele_table.verticalHeader().setDefaultSectionSize(36)
        self.tele_table.doubleClicked.connect(self._open_tele_detail)
        lay.addWidget(self.tele_table, 1)
        return page

    def _page_ai(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(30, 30, 30, 30); lay.setSpacing(12)
        t = QLabel("智能设置"); t.setObjectName("title"); lay.addWidget(t)
        hint = QLabel("公司智能入口（兼容常见对话协议）。配置保存在本地配置文件，接口密钥不写入代码。")
        hint.setObjectName("pageHint"); hint.setWordWrap(True); lay.addWidget(hint)
        cfg = load_ai_config()
        form = QFormLayout()
        self.ai_url = QLineEdit(cfg.get("base_url", "")); self.ai_url.setPlaceholderText("https://gateway.example.com/v1")
        self.ai_model = QLineEdit(cfg.get("model", "")); self.ai_model.setPlaceholderText("glm-5.3-flash")
        self.ai_key = QLineEdit(cfg.get("api_key", "")); self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_key.setPlaceholderText("sk-...")
        self.ai_type = QComboBox()
        self.ai_type.addItem("对话接口", "chat_completions")
        self.ai_type.addItem("响应接口", "responses")
        cur_type = cfg.get("api_type", "chat_completions")
        type_index = self.ai_type.findData(cur_type)
        self.ai_type.setCurrentIndex(type_index if type_index >= 0 else 0)
        form.addRow("接口地址", self.ai_url)
        form.addRow("模型名称", self.ai_model)
        form.addRow("协议类型", self.ai_type)
        form.addRow("接口密钥", self.ai_key)
        lay.addLayout(form)
        row = QHBoxLayout()
        test = QPushButton("测试连接"); test.clicked.connect(self._ai_test)
        self.ai_test_btn = test
        save = QPushButton("保存配置"); save.setObjectName("primary"); save.clicked.connect(self._ai_save)
        row.addWidget(test); row.addWidget(save); row.addStretch()
        lay.addLayout(row)
        self.ai_status = QLabel(""); lay.addWidget(self.ai_status)
        lay.addStretch()
        return page

    # ---------- 数据与筛选 ----------

    def _pick(self, target: QLineEdit, flt: str):
        val, _ = QFileDialog.getOpenFileName(self, "选择文件", str(Path.home()), flt)
        if val:
            target.setText(val)

    def _row_search_text(self, row: dict) -> str:
        """单条会话的可搜索文本（缓存，避免每次输入重复拼接）。"""
        cache = getattr(self, "_search_cache", None)
        if cache is None:
            self._search_cache = {}
            cache = self._search_cache
        rid = row.get("id")
        text = cache.get(rid)
        if text is None:
            labels = row.get("excel_labels") or {}
            parts = [
                row.get("customer"), row.get("customer_key"), row.get("agent"), row.get("store_id"),
                labels.get("product_name"), labels.get("model"), _advice(row),
            ]
            parts += [str(m.get("body_text") or "") for m in (row.get("messages") or [])]
            text = " ".join(str(x) for x in parts if x).lower()
            cache[rid] = text
        return text

    def _refresh_all(self):
        if self.runner:
            self.records = load_records(self.runner.db)
        self._search_cache = {}
        self._refresh_filters()
        self._refresh_view()
        self._refresh_batches()
        self._refresh_review()
        self._refresh_tele()

    def _refresh_filters(self):
        stores = sorted({r["store_id"] for r in self.records if r["store_id"]})
        agents = sorted({r["agent"] for r in self.records if r["agent"]})
        products = sorted({(r["excel_labels"].get("model") or "").strip() for r in self.records} - {"", "-"})
        for combo, items in [(self.f_store, stores), (self.f_product, products)]:
            cur = combo.currentText()
            combo.blockSignals(True); combo.clear(); combo.addItem("全部", "全部"); combo.addItems(items)
            if cur:
                idx = combo.findText(cur)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
        # 客服下拉：显示去掉店铺前缀的短名，完整账号存在 itemData 里用于筛选
        cur_agent = self.f_agent.currentData() or self.f_agent.currentText()
        self.f_agent.blockSignals(True)
        self.f_agent.clear(); self.f_agent.addItem("全部", "全部")
        for name in agents:
            self.f_agent.addItem(_short_agent_label(name), name)
        idx = self.f_agent.findData(cur_agent)
        self.f_agent.setCurrentIndex(idx if idx >= 0 else 0)
        self.f_agent.blockSignals(False)
        dates = [datetime.fromisoformat(r["first_message_at"]).date() for r in self.records if r["first_message_at"]]
        if dates:
            from PyQt6.QtCore import QDate
            self.f_start.blockSignals(True); self.f_end.blockSignals(True)
            self.f_start.setDate(QDate(dates[0].year, dates[0].month, dates[0].day))
            self.f_end.setDate(QDate(dates[-1].year, dates[-1].month, dates[-1].day))
            self.f_start.blockSignals(False); self.f_end.blockSignals(False)
        # 导入页店铺下拉：合并 config 预置 + 已导入数据的店铺，保持可编辑
        store_all = self._load_stores() + [s for s in stores if s not in self._load_stores()]
        existing = {self.store_combo.itemText(i) for i in range(self.store_combo.count())}
        for s in store_all:
            if s not in existing:
                self.store_combo.addItem(s)

    # ---------- 店铺管理 ----------

    def _load_stores(self) -> list[str]:
        import yaml
        p = self.config_dir / "config.yaml"
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            stores = data.get("stores") or []
            return [str(s).strip() for s in stores if str(s).strip()]
        except Exception:
            return ["品牌A官方自营旗舰店"]

    def _save_stores(self, stores: list[str]) -> None:
        import yaml
        p = self.config_dir / "config.yaml"
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        data["stores"] = stores
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _manage_stores(self):
        dlg = QDialog(self); dlg.setWindowTitle("管理店铺"); dlg.resize(420, 360)
        dlg.setObjectName("storeDialog")
        dlg.setAutoFillBackground(True)
        dl = QVBoxLayout(dlg)
        dl.addWidget(QLabel("维护店铺列表（导入时选择，可跨店铺归流）。"))
        lst = QListWidget()
        current = self._load_stores()
        # 合并已导入数据的店铺
        imported = sorted({r["store_id"] for r in self.records if r["store_id"]})
        for s in imported:
            if s not in current:
                current.append(s)
        for s in current:
            lst.addItem(s)
        dl.addWidget(lst, 1)
        inp = QLineEdit(); inp.setPlaceholderText("输入新店铺名称")
        dl.addWidget(inp)
        btn = QHBoxLayout()
        add = QPushButton("添加"); add.setObjectName("primary")
        rem = QPushButton("删除选中")
        btn.addWidget(add); btn.addWidget(rem); btn.addStretch()
        dl.addLayout(btn)

        def do_add():
            name = inp.text().strip()
            if not name:
                return
            if name not in [lst.item(i).text() for i in range(lst.count())]:
                lst.addItem(name)
            inp.clear()

        def do_remove():
            it = lst.currentItem()
            if it:
                lst.takeItem(lst.row(it))

        def do_ok():
            stores = [lst.item(i).text() for i in range(lst.count())]
            self._save_stores(stores)
            # 刷新导入页店铺下拉
            cur = self.store_combo.currentText()
            self.store_combo.blockSignals(True)
            self.store_combo.clear()
            self.store_combo.addItems(stores)
            if cur:
                idx = self.store_combo.findText(cur)
                self.store_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.store_combo.blockSignals(False)
            dlg.accept()

        add.clicked.connect(do_add)
        rem.clicked.connect(do_remove)
        ok = QPushButton("保存"); ok.setObjectName("primary"); ok.clicked.connect(do_ok)
        btn.addWidget(ok)
        dlg.exec()

    def _clear_filters(self):
        """一键清除总览筛选，恢复数据全范围。"""
        for combo in (self.f_store, self.f_agent, self.f_product, self.f_stage,
                      self.f_lead, self.f_valid, self.f_score, self.f_deduction):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        dates = [datetime.fromisoformat(r["first_message_at"]).date()
                 for r in self.records if r["first_message_at"]]
        if dates:
            from PyQt6.QtCore import QDate
            self.f_start.blockSignals(True); self.f_end.blockSignals(True)
            self.f_start.setDate(QDate(min(dates).year, min(dates).month, min(dates).day))
            self.f_end.setDate(QDate(max(dates).year, max(dates).month, max(dates).day))
            self.f_start.blockSignals(False); self.f_end.blockSignals(False)
        self.f_merge.setChecked(True)
        if hasattr(self, "search_input"):
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
        self._refresh_view()
        self._refresh_tele()

    def _on_merge_toggle(self, _state=None):
        self._refresh_view()
        self._refresh_tele()

    def _filter_by_lead_index(self, index: int):
        mapping = ["A", "B", "C"]
        if 0 <= index < len(mapping):
            target = mapping[index]
            self.f_lead.setCurrentText("全部" if self.f_lead.currentText() == target else target)

    def _filter_by_score_index(self, index: int):
        mapping = ["90+", "75-89", "60-74", "<60"]
        if 0 <= index < len(mapping):
            target = mapping[index]
            self.f_score.setCurrentText("全部" if self.f_score.currentText() == target else target)

    def _apply_filter(self, skip_agent: bool = False) -> list[dict]:
        store = self.f_store.currentText()
        agent = self.f_agent.currentData() or self.f_agent.currentText()
        keyword = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        tokens = [t for t in keyword.split() if t]
        prod = self.f_product.currentText()
        stage = self.f_stage.currentText()
        lead = self.f_lead.currentText()
        valid = self.f_valid.currentText()
        score_range = self.f_score.currentText()
        d_start = self.f_start.date().toPyDate()
        d_end = self.f_end.date().toPyDate()
        out = []
        for r in self.records:
            if tokens and not all(tok in self._row_search_text(r) for tok in tokens):
                continue
            if store != "全部" and r["store_id"] != store:
                continue
            if not skip_agent and agent != "全部" and r["agent"] != agent:
                continue
            if prod != "全部" and (r["excel_labels"].get("model") or "").strip() != prod:
                continue
            if stage != "全部" and STAGE_CN.get(r["service_stage"]) != stage:
                continue
            if lead != "全部" and (r["lead_level"] or "无") != lead:
                continue
            if valid != "全部" and VALID_CN.get(r["validity"]) != valid:
                continue
            deduction_filter = self.f_deduction.currentText()
            if deduction_filter != "全部":
                dims = r.get("deductions") or {}
                total_deduction = sum(float(v or 0) for v in dims.values())
                if deduction_filter == "有扣分" and total_deduction <= 0:
                    continue
                if deduction_filter == "无扣分" and total_deduction > 0:
                    continue
                if deduction_filter == "致命候选" and not r.get("fatal_candidates"):
                    continue
                dim_code = {f"{v}扣分": k for k, v in DIM_CN.items()}.get(deduction_filter)
                if dim_code and not dims.get(dim_code):
                    continue
            if score_range != "全部":
                score = _display_score(r)
                if score_range == "无分数":
                    if score is not None:
                        continue
                else:
                    if score is None:
                        continue
                    if score_range == "90+" and score < 90:
                        continue
                    if score_range == "75-89" and not (75 <= score < 90):
                        continue
                    if score_range == "60-74" and not (60 <= score < 75):
                        continue
                    if score_range == "<60" and score >= 60:
                        continue
            if not r["first_message_at"]:
                continue
            d = datetime.fromisoformat(r["first_message_at"]).date()
            if d < d_start or d > d_end:
                continue
            out.append(r)
        return out

    def _refresh_view(self):
        if not hasattr(self, "table"):
            return
        records = self._apply_filter()
        merge_on = getattr(self, "f_merge", None) is not None and self.f_merge.isChecked()
        self.filtered = merge_consultations(records) if merge_on else records
        n = len(self.filtered)
        if hasattr(self, "search_hint"):
            keyword = self.search_input.text().strip()
            if keyword:
                suffix = "（已按客户合并）" if merge_on else ""
                self.search_hint.setText(f"找到 {len(records)} 条会话，显示 {n} 条{suffix}")
            else:
                self.search_hint.setText("")
        pre = sum(1 for r in self.filtered if r["service_stage"] == "pre_sale")
        post = sum(1 for r in self.filtered if r["service_stage"] == "after_sale")
        valid = sum(1 for r in self.filtered if r["validity"] == "valid")
        lead = {"A": 0, "B": 0, "C": 0}
        scores = []
        for r in self.filtered:
            if r["lead_level"] in lead:
                lead[r["lead_level"]] += 1
            score = _display_score(r)
            if score is not None:
                scores.append(score)
        tele = sum(1 for r in self.filtered if r["tele_sales_lead"])
        avg = round(sum(scores) / len(scores), 1) if scores else "-"
        for k, v in {"total": n, "pre": pre, "post": post, "valid": valid, "a": lead["A"],
                     "b": lead["B"], "c": lead["C"], "tele": tele, "avg": avg}.items():
            self.stat_labels[k].setText(str(v))
        ratios = {"pre": pre, "post": post, "valid": valid, "a": lead["A"], "b": lead["B"],
                  "c": lead["C"], "tele": tele}
        for key, value in ratios.items():
            self.stat_subs[key].setText(f"占 {value / n * 100:.1f}%" if n else "占 0%")
        self.stat_subs["total"].setText("当前筛选结果")
        self.stat_subs["avg"].setText("满分 100")
        self.chart_lead.set_data(["A 级", "B 级", "C 级"], [lead["A"], lead["B"], lead["C"]],
                                 ["#b79bff", "#38e8ff", "#888780"])
        buckets = {"90+": 0, "75-89": 0, "60-74": 0, "<60": 0}
        for s in scores:
            k = "90+" if s >= 90 else "75-89" if s >= 75 else "60-74" if s >= 60 else "<60"
            buckets[k] += 1
        self.chart_score.set_data(list(buckets.keys()), list(buckets.values()),
                                  ["#38e8ff", "#7b5cff", "#b79bff", "#e24b4a"])
        self._refresh_service_view()
        self.table.setRowCount(0)
        for r in self.filtered:
            row = self.table.rowCount()
            self.table.insertRow(row)
            # AI 判定：区分 AI 结果与规则结果
            ai_stat = r.get("ai_status")
            if ai_stat in ("not_run", "not_configured", "", None):
                ai_label = "规则"
            elif ai_stat == "done":
                ai_label = "智能：" + AI_CN.get(r.get("ai_judgment"), "未知")
            elif ai_stat == "failed":
                ai_label = "智能判定失败"
            else:
                ai_label = "智能：" + AI_CN.get(str(ai_stat), "处理中")
            phone_kind, phone_value = _contact_info(r)
            product_name = str((r["excel_labels"] or {}).get("product_name") or "").strip()
            agent_full = str(r["agent"] or "")
            agent_short = "、".join(_short_agent_label(a.strip()) for a in agent_full.split("、") if a.strip()) or "-"
            vals = [r["first_message_at"], r["store_id"], agent_short, _customer_label(r),
                    _product_label(r), product_name or "-",
                    STAGE_CN.get(r["service_stage"], ""), VALID_CN.get(r["validity"], ""), r["lead_level"] or "",
                    str(_display_score(r)) if _display_score(r) is not None else "-",
                    ai_label, phone_value, _advice(r)[:36]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.table.setItem(row, c, item)
            if agent_full and agent_short != agent_full:
                self.table.item(row, 2).setToolTip(agent_full)
            score_value = _display_score(r)
            if score_value is not None:
                pending_note = "（待AI质检：当前只算规则维度）" if r.get("final_status") == "ai_pending" else ""
                self.table.item(row, 9).setToolTip(
                    f"{score_value:g} 分 ｜ 评级 {_rating_label(score_value)}{pending_note}")
            if product_name:
                self.table.item(row, 5).setToolTip("数据中的商品名称：" + product_name)
            # AI 列着色：AI 有结果的标蓝色，规则标灰色；悬停可看 AI 理由与建议
            if ai_label.startswith("智能"):
                self.table.item(row, 10).setForeground(QColor("#2972F4"))
            else:
                self.table.item(row, 10).setForeground(QColor("#8a9099"))
            suggest_tip = ""
            if (r.get("ai_suggest_stage") or "keep") != "keep" or (r.get("ai_suggest_validity") or "keep") != "keep":
                suggest_tip = "AI 建议改判：" + "；".join(
                    x for x in [
                        f"阶段→{STAGE_CN.get(r.get('ai_suggest_stage'), '')}" if (r.get("ai_suggest_stage") or "keep") != "keep" else "",
                        f"有效性→{VALID_CN.get(r.get('ai_suggest_validity'), '')}" if (r.get("ai_suggest_validity") or "keep") != "keep" else "",
                    ] if x
                )
            ai_tip = "；".join(x for x in [r.get("ai_reason"), r.get("ai_suggestion"), suggest_tip] if x)
            if ai_tip:
                self.table.item(row, 10).setToolTip(ai_tip)
            # 待人工复核的会话 → 整行浅红底，回到总览一眼能看到（已完成的恢复白底）
            if r.get("review_status") == "pending":
                for c in range(self.table.columnCount()):
                    cell = self.table.item(row, c)
                    if cell is not None:
                        cell.setBackground(QColor("#FFF0F0"))

    def _refresh_batches(self):
        if not self.runner:
            return
        rows = self.runner.db.list_batches()
        self.batch_table.setRowCount(0)
        for b in rows:
            row = self.batch_table.rowCount()
            self.batch_table.insertRow(row)
            vals = [b["id"], b["store_id"] or "-", b["imported_at"],
                    f"{b['data_start_at'] or ''} ~ {b['data_end_at'] or ''}",
                    str(b["session_count"]), str(b["matched_count"]), b["note"] or ""]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.batch_table.setItem(row, c, item)

    def _edit_batch(self):
        """编辑导入批次的店铺标记/备注。"""
        rows = self.batch_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在历史批次表里选中要编辑的批次行"); return
        batch_id = self.batch_table.item(rows[0].row(), 0).text()
        batch = self.runner.db.fetch_one("SELECT * FROM batches WHERE id = ?", (batch_id,))
        if not batch:
            QMessageBox.warning(self, "提示", "找不到该批次"); return
        dlg = QDialog(self); dlg.setWindowTitle("编辑导入批次")
        dlg.resize(520, 230)
        lay = QVBoxLayout(dlg)
        info = QLabel(f"批次：{batch_id}\n导入时间：{batch['imported_at']}　会话数：{batch['session_count']}")
        info.setWordWrap(True); lay.addWidget(info)
        form = QFormLayout()
        store_combo = QComboBox(); store_combo.setEditable(True)
        stores = [self.store_combo.itemText(i) for i in range(self.store_combo.count())]
        if not stores:
            stores = ["默认"]
        store_combo.addItems(stores)
        cur_store = str(batch["store_id"] or "")
        if cur_store and store_combo.findText(cur_store) < 0:
            store_combo.addItem(cur_store)
        store_combo.setCurrentText(cur_store or stores[0])
        note_input = QLineEdit(str(batch["note"] or ""))
        note_input.setPlaceholderText("例如：10 月华东区主推批次 / 补导 / 测试数据")
        form.addRow("店铺标记", store_combo)
        form.addRow("备注", note_input)
        lay.addLayout(form)
        tip = QLabel("修改店铺会同步更新该批次全部会话的店铺归属；数据与评分不变。")
        tip.setStyleSheet("color:#7a8399;font-size:12px;"); tip.setWordWrap(True); lay.addWidget(tip)
        btns = QHBoxLayout(); btns.addStretch()
        cancel = QPushButton("取消"); cancel.clicked.connect(dlg.reject)
        save = QPushButton("保存修改"); save.setObjectName("primary")
        btns.addWidget(cancel); btns.addWidget(save); lay.addLayout(btns)

        def do_save():
            store = store_combo.currentText().strip()
            note = note_input.text().strip()
            if not store:
                QMessageBox.warning(dlg, "提示", "店铺标记不能为空"); return
            dlg.accept()
            count = self.runner.db.update_batch(batch_id, store_id=store, note=note)
            self._refresh_batches()
            self._refresh_all()
            QMessageBox.information(self, "修改完成", f"批次 {batch_id} 已更新（店铺：{store}，影响 {count} 条会话）。")

        save.clicked.connect(do_save)
        dlg.exec()

    def _repair_batches(self):
        info = self.runner.db.repair_batches()
        self._refresh_all()
        msg = f"已清理空批次 {info.get('removed_empty', 0)} 个。"
        if info.get("duplicate_sha"):
            msg += f"\n另有 {info['duplicate_sha']} 个批次使用同一日志文件，未自动删除，请手动检查。"
        QMessageBox.information(self, "批次修复完成", msg)

    def _delete_batch(self):
        rows = self.batch_table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "提示", "请先在历史批次表里选中要删除的批次行"); return
        batch_id = self.batch_table.item(rows[0].row(), 0).text()
        ret = QMessageBox.question(
            self, "确认删除",
            f"确定删除批次 {batch_id} 及其全部会话、质检结果吗？\n此操作不可撤销（会写入审计日志）。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        count = self.runner.db.delete_batch(batch_id)
        self._refresh_all()
        QMessageBox.information(self, "删除完成", f"已删除批次 {batch_id}，共移除 {count} 条会话。")

    def _refresh_review(self):
        if not hasattr(self, "review_table"):
            return
        pending = [
            r for r in self.records
            if r["review_status"] != "completed"
            and (r["review_status"] == "pending" or r["service_stage"] == "needs_review")
        ]
        self.review_count_label.setText(f"待复核 {len(pending)} 条")
        self.review_table.setRowCount(0)
        for r in pending:
            row = self.review_table.rowCount()
            self.review_table.insertRow(row)
            score = _display_score(r)
            vals = [r["first_message_at"], r["agent"] or "-", STAGE_CN.get(r["service_stage"], ""),
                    VALID_CN.get(r["validity"], ""), r["lead_level"] or "",
                    str(score) if score is not None else "-",
                    "、".join(_reason_label(code) for code in r["reason_codes"][:3]), REVIEW_CN.get(r["review_status"], "待复核")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.review_table.setItem(row, c, item)
        self._review_pending = pending

    def _bulk_confirm_reviews(self):
        pending = list(getattr(self, "_review_pending", []))
        eligible = [r for r in pending if r.get("final_status") in ("合格", "不合格")]
        if not eligible:
            QMessageBox.information(
                self, "提示",
                "当前没有可直接确认的待复核会话（待AI质检/售后记录需先处理或会被跳过）。")
            return
        ret = QMessageBox.question(
            self, "一键复核",
            f"将按当前最终分数/状态确认 {len(eligible)} 条会话，"
            f"跳过 {len(pending) - len(eligible)} 条待AI/售后记录。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        info = self.runner.db.bulk_confirm_reviews(eligible, "质检员")
        self._refresh_all()
        QMessageBox.information(
            self, "复核完成",
            f"已确认 {info['confirmed']} 条；跳过 {info['skipped']} 条。")

    def _refresh_tele(self):
        if not hasattr(self, "tele_table"):
            return
        kind = self.f_tele_kind.currentText() if hasattr(self, "f_tele_kind") else "全部"
        merge_on = getattr(self, "f_merge", None) is not None and self.f_merge.isChecked()
        base = merge_consultations(self.records) if merge_on else self.records
        rows = []
        for r in base:
            ckind, cvalue = _contact_info(r)
            has = bool(ckind)
            if kind == "全部":
                pass
            elif kind == "有留资":
                if not has: continue
            elif kind == "空白":
                if has: continue
            elif kind != ckind:
                continue
            rows.append((r, ckind, cvalue))
        self.tele_table.setRowCount(0)
        for r, ckind, cvalue in rows:
            row = self.tele_table.rowCount()
            self.tele_table.insertRow(row)
            vals = [r["first_message_at"], r["store_id"], r["agent"] or "-", _customer_label(r),
                    _product_label(r), ckind or "—", cvalue or "—", _advice(r)[:46]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.tele_table.setItem(row, c, item)
        self._tele_rows = [r for r, _, _ in rows]
        total = len(base) or 1
        if hasattr(self, "tele_hint"):
            self.tele_hint.setText(f"共 {len(rows)} 条 / 全部 {len(base)} 条（{len(rows) / total * 100:.1f}%）")

    def _export_tele(self):
        from openpyxl import Workbook
        rows = getattr(self, "_tele_rows", [])
        if not rows:
            QMessageBox.information(self, "提示", "当前筛选下没有留资线索可导出。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出留资线索", str(Path.home() / "留资线索.xlsx"), "Excel (*.xlsx)")
        if not path:
            return
        wb = Workbook()
        ws = wb.active
        ws.title = "留资线索"
        ws.append(["时间", "店铺", "客服", "客户", "产品", "线索类型", "留资线索", "建议"])
        for r in rows:
            kind, value = _contact_info(r)
            ws.append([r["first_message_at"], r["store_id"], r["agent"], _customer_label(r),
                       _product_label(r), kind or "—", value or "—", _advice(r)])
        for col, width in zip("ABCDEFGH", [20, 20, 10, 16, 12, 10, 20, 45]):
            ws.column_dimensions[col].width = width
        wb.save(path)
        QMessageBox.information(self, "导出完成", f"已导出 {len(rows)} 条留资线索：\n{path}")

    # ---------- 操作 ----------

    def _pick_file(self, target: QLineEdit, flt: str):
        val, _ = QFileDialog.getOpenFileName(self, "选择文件", str(Path.home()), flt)
        if val:
            target.setText(val)

    def _do_import(self):
        log_p, xlsx_p = self.log_input.text().strip(), self.excel_input.text().strip()
        if not log_p or not xlsx_p:
            QMessageBox.warning(self, "缺少文件", "请同时选择 .log 和 .xlsx"); return
        self.import_status.setText("正在解析、匹配、规则初筛、评分并写入数据库……")
        QApplication.processEvents()
        try:
            info = self.runner.run(Path(log_p), Path(xlsx_p), self.store_combo.currentText())
            self.import_status.setText(info["message"])
            if not info.get("duplicated"):
                self._refresh_all()
                self._clear_filters()
                self.nav.setCurrentRow(1)
        except Exception as exc:
            repaired = 0
            try:
                repaired = self.runner.db.repair_batches().get("removed_empty", 0)
                self._refresh_all()
            except Exception:
                pass
            tip = "，已清理本次未完成的空批次，可直接重试" if repaired else ""
            self.import_status.setText(f"导入失败：{_exc_cn(exc)}{tip}")

    def _row_at(self, table: QTableWidget) -> dict | None:
        rows = table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if table is self.table:
            return self.filtered[idx] if idx < len(self.filtered) else None
        if table is self.review_table:
            return self._review_pending[idx] if idx < len(self._review_pending) else None
        if table is self.tele_table:
            return self._tele_rows[idx] if idx < len(self._tele_rows) else None
        return None

    def _open_detail(self):
        r = self._row_at(self.table)
        if r:
            DetailDialog(r, self.runner, self._save_review_cb, self._apply_ai_cb).exec()

    def _open_review_detail(self):
        r = self._row_at(self.review_table)
        if r:
            DetailDialog(r, self.runner, self._save_review_cb, self._apply_ai_cb).exec()

    def _open_tele_detail(self):
        r = self._row_at(self.tele_table)
        if r:
            DetailDialog(r, self.runner, self._save_review_cb, self._apply_ai_cb).exec()

    def _save_review_cb(self, row: dict, status: str, score, note: str, fatal: bool):
        self.runner.save_review(row, status, score, note, "质检员", fatal)
        self._refresh_all()

    def _apply_ai_cb(self, row: dict, service_stage: str | None, validity: str | None, note: str):
        self.runner.db.apply_ai_suggestion(row["id"], service_stage, validity, note, "质检员")
        self._refresh_all()

    # ---------- AI ----------

    def _ai_test(self):
        cfg = {**load_ai_config(),
               "base_url": self.ai_url.text().strip(), "model": self.ai_model.text().strip(),
               "api_key": self.ai_key.text().strip(), "api_type": self.ai_type.currentData() or "chat_completions",
               "timeout_seconds": 60}
        if hasattr(self, "ai_test_btn"):
            self.ai_test_btn.setEnabled(False)
        self.ai_status.setText("⏳ 正在测试连接（最长约 60 秒）…")
        self._ai_test_thread = AITestThread(cfg)
        self._ai_test_thread.finished_test.connect(self._ai_test_done)
        self._ai_test_thread.start()

    def _ai_test_done(self, ok: bool, msg: str):
        if hasattr(self, "ai_test_btn"):
            self.ai_test_btn.setEnabled(True)
        self.ai_status.setText(("✅ " if ok else "❌ ") + msg)

    def _ai_save(self):
        save_ai_config({
            "base_url": self.ai_url.text().strip(),
            "model": self.ai_model.text().strip(),
            "api_key": self.ai_key.text().strip(),
            "api_type": self.ai_type.currentData() or "chat_completions",
        })
        self.ai_status.setText("✅ 配置已保存到本地配置文件（密钥不写入代码）")

    def _make_client(self):
        from qc_engine.ai.client import AIClient
        return AIClient({**load_ai_config(), "timeout_seconds": 60}, self.runner.db)

    def _ai_summarize(self):
        if not self.filtered:
            QMessageBox.information(self, "提示", "当前筛选无数据"); return
        self.import_status.setText("智能总结中…")
        rows = self.filtered

        def work(progress):
            return {"summary": self.runner.ai_summarize(rows)}

        self._worker = Worker(work)
        self._worker.finished_ok.connect(self._show_summary)
        self._worker.start()

    def _show_summary(self, res):
        if res.get("error"):
            QMessageBox.warning(self, "智能总结失败", res["error"]); return
        dlg = QDialog(self); dlg.setWindowTitle("智能质检总结"); dlg.resize(680, 520)
        dlg.setObjectName("summaryDialog")
        dlg.setAutoFillBackground(True)
        dl = QVBoxLayout(dlg)
        t = QTextEdit(); t.setReadOnly(True)
        t.setHtml(self._format_summary_html(str(res.get("summary", ""))))
        dl.addWidget(t)
        dlg.exec()

    @staticmethod
    def _format_summary_html(text: str) -> str:
        """把 AI 返回的纯文本整理成白底、分点清晰的排版（标题加粗、分点缩进、去除 markdown 乱码符号）。"""
        def esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # 去掉 markdown 符号（#、**、- 等），保留可读文本
        lines = text.splitlines()
        out = []
        for line in lines:
            s = line.strip()
            if not s:
                out.append('<div style="height:8px;"></div>')
                continue
            # 去掉 markdown 标记
            s = s.replace("**", "").replace("##", "").replace("###", "")
            s = s.lstrip("# ").lstrip("- ").lstrip("• ").lstrip("* ")
            # 判断是否为标题（短且结尾是冒号，或包含"问题""建议""总结"等）
            is_title = (len(s) <= 24 and (s.endswith("：") or s.endswith(":"))) or \
                       s.startswith(("一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、")) or \
                       s.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8."))
            if is_title:
                out.append(f'<div style="font-size:15px;font-weight:600;color:#1f2329;margin-top:10px;">{esc(s)}</div>')
            else:
                out.append(f'<div style="font-size:13px;color:#3a3f47;line-height:1.7;margin:2px 0;">{esc(s)}</div>')
        body = "".join(out)
        return (
            '<div style="background:#ffffff;border:1px solid #e6e9ef;border-radius:12px;padding:20px 24px;">'
            + body + '</div>'
        )

    def _ai_ready(self) -> bool:
        cfg = load_ai_config()
        if not (cfg.get("base_url") and cfg.get("model") and cfg.get("api_key")):
            QMessageBox.warning(self, "提示", "尚未配置智能接口，请先到「智能设置」填写地址、模型与密钥并保存。")
            return False
        return True

    def _ai_review_batch(self):
        """只处理被规则标记为可疑、且尚未人工复核完成的会话。"""
        if not self.filtered:
            QMessageBox.information(self, "提示", "当前筛选无数据"); return
        targets = [
            r for r in self.filtered
            if r["review_status"] != "completed"
            and (r["review_status"] == "pending" or r["service_stage"] == "needs_review")
        ]
        if not targets:
            QMessageBox.information(self, "提示", "当前筛选内没有被标记为可疑的会话。\n如需对全部会话跑智能质检，请使用「全量智能质检」。")
            return
        if not self._ai_ready():
            return
        self._run_ai_batch(targets, "智能批量质检")

    def _ai_review_all(self):
        """对当前筛选内的全部会话（含规则已判定的）逐条做 AI 质检。"""
        if not self.filtered:
            QMessageBox.information(self, "提示", "当前筛选无数据"); return
        targets = [r for r in self.filtered if r["review_status"] != "completed"]
        if not targets:
            QMessageBox.information(self, "提示", "当前筛选内的会话都已完成人工复核，无需再跑智能质检。")
            return
        ret = QMessageBox.question(
            self, "全量智能质检",
            f"将对当前筛选的 {len(targets)} 条会话逐条调用 AI 质检（包含规则已判定的会话；已完成人工复核的会跳过）。\n\n"
            f"这会消耗较多接口调用并需要一定时间，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        if not self._ai_ready():
            return
        self._run_ai_batch(targets, "全量智能质检")

    @staticmethod
    def _ai_payload_messages(record: dict) -> list[dict]:
        """把会话消息转成 AI 质检载荷：跳过系统分隔消息（合并会话的「第 N 次咨询」没有 index）。"""
        messages: list[dict] = []
        for i, m in enumerate(record.get("messages") or [], start=1):
            if m.get("sender_role") == "system":
                continue
            messages.append({
                "message_ref": f"message:{m.get('index', i)}",
                "sender_role": m.get("sender_role") or "customer",
                "body_text": str(m.get("body_text") or ""),
            })
        return messages or [{"message_ref": "message:0", "sender_role": "system", "body_text": "（空会话）"}]

    def _run_ai_batch(self, targets: list[dict], title: str):
        client = self._make_client()
        dlg = QProgressDialog(f"{title}处理中…", "取消", 0, len(targets), self)
        dlg.setObjectName("progressDialog")
        dlg.setAutoFillBackground(True)
        dlg.setWindowTitle(title); dlg.setMinimumDuration(0); dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setLabelText(f"{title}：0/{len(targets)}")

        def work(progress):
            done = 0
            for r in targets:
                if dlg.wasCanceled():
                    break
                payload = {"conversation_id": r["id"], "messages": self._ai_payload_messages(r)}
                result = client.judge_conversation(payload)
                self.runner.db.update_ai_judgment(r["id"], result.get("status", "failed"),
                                                  result.get("judgment"), result.get("reason"), result.get("suggestion"),
                                                  result.get("evidence"))
                done += 1
                progress(done, len(targets))
            return {"processed": done}

        def on_progress(cur, total):
            dlg.setLabelText(f"{title}：{cur}/{total}")
            dlg.setValue(cur)

        def on_done(res):
            dlg.close()
            if res.get("error"):
                QMessageBox.warning(self, title + "失败", res["error"]); return
            QMessageBox.information(self, title + "完成", f"已处理 {res.get('processed', 0)} 条，结果已写回数据库（相同内容自动命中缓存）。")
            self._refresh_all()
            try:
                self._perform_rescore(confirm=False, title=f"{title}后重算评分")
            except Exception:
                pass

        self._worker = Worker(work)
        self._worker.progress.connect(on_progress)
        self._worker.finished_ok.connect(on_done)
        self._worker.start()

    # ---------- 导出 ----------

    def _export_excel(self):
        if not self.filtered:
            QMessageBox.information(self, "提示", "当前筛选无数据"); return
        import openpyxl
        path, _ = QFileDialog.getSaveFileName(self, "导出质检结果", "质检结果.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        wb = openpyxl.Workbook(); ws = wb.active; ws.title = "质检结果"
        ws.append(["时间", "店铺", "客服", "客户", "产品编号", "产品名称", "阶段", "有效", "商机", "电销线索",
                   "计算分", "最终状态", "复核状态", "智能判定", "智能建议", "复核说明", "扣分明细", "建议"])
        for r in self.filtered:
            dims = r["deductions"] or {}
            dim_txt = "；".join(f"{DIM_CN.get(k, k)}扣{v}分" for k, v in dims.items() if v)
            ws.append([r["first_message_at"], r["store_id"], r["agent"], _customer_label(r),
                       "、".join(r["product_ids"]), r["excel_labels"].get("product_name"),
                       STAGE_CN.get(r["service_stage"], "-"), VALID_CN.get(r["validity"], "-"), r["lead_level"],
                       "是" if r["tele_sales_lead"] else "否", r["calculated_score"],
                       FINAL_CN.get(r["final_status"], r["final_status"] or "-"),
                       REVIEW_CN.get(r["review_status"], "-"),
                       AI_CN.get(r.get("ai_judgment"), "-"), r.get("ai_suggestion") or "",
                       r["review_note"], dim_txt, _advice(r)])
        wb.save(path)
        QMessageBox.information(self, "导出完成", f"已导出 {len(self.filtered)} 条到 {path}")

    # ---------- 爆单一铲（质检总览内的子窗口） ----------

    # ---------- 评分标准（查看 / 切换 / 重算） ----------

    def _open_scoring_standard(self):
        """查看当前评分规则：每个维度、每个档位的详细标准。"""
        cfg = self.runner.scoring.config
        dims = cfg.get("dimensions", {}) or {}
        tier_labels = cfg.get("tier_labels") or {
            "excellent": "优秀", "good": "良好", "qualified": "合格", "fail": "不合格",
        }
        tiers = ["excellent", "good", "qualified", "fail"]
        rows = []
        for code in SCORE_DIM_ORDER:
            dim = dims.get(code) or {}
            mode = str(dim.get("mode") or "rule")
            if mode == "ai":
                mode_text = "AI 语义"
            elif dim.get("ai_assist"):
                mode_text = "规则 + AI 辅助"
            else:
                mode_text = "规则"
            total = float(dim.get("total", 0) or 0)
            levels = dim.get("levels", {}) or {}
            cells = []
            for tier in tiers:
                level = levels.get(tier)
                if not level:
                    cells.append("<td style='padding:8px 10px;border-bottom:1px solid #eef2f9;color:#b8bec9'>—</td>")
                    continue
                points = float(level.get("points", 0) or 0)
                pct = round(points / total * 100) if total else 0
                standard = html.escape(str(level.get("standard") or ""))
                cells.append(
                    "<td style='padding:8px 10px;border-bottom:1px solid #eef2f9;vertical-align:top'>"
                    f"<b style='color:#4c3f8f'>{tier_labels.get(tier, tier)} {points:g} 分（{pct}%）</b><br>"
                    f"<span style='color:#5d6780'>{standard}</span></td>"
                )
            rows.append(
                "<tr><td style='padding:8px 10px;border-bottom:1px solid #eef2f9;vertical-align:top'>"
                f"<b>{DIM_CN.get(code, code)}</b><br><span style='color:#7a8399;font-size:12px'>"
                f"满分 {total:g} · {mode_text}</span></td>{''.join(cells)}</tr>"
            )

        bands = cfg.get("rating_bands") or []
        band_txt = " ｜ ".join(f"{b.get('label')} ≥{b.get('min')}" for b in bands)
        html_text = f"""
        <html><body style="font-family:'Microsoft YaHei';font-size:13px;color:#1f2430;line-height:1.7">
        <h2 style="color:#4c3f8f;margin:2px 0 4px">{cfg.get('title') or '客服质检评分标准'}</h2>
        <p style="color:#64708a;margin:0 0 8px">{cfg.get('version','')} · 两个角色看板共用同一规则库</p>
        <p style="margin:0 0 8px">{cfg.get('description','')}</p>
        <div style="background:#F7F4FF;border:1px solid #E6DFFF;border-radius:6px;padding:9px 12px;margin:8px 0 12px">
          <b>档位规则：</b>每个维度按“优秀/良好/合格/不合格”给出对应分数（部分维度只有 2 档）。<br>
          <b>AI 维度：</b>话术匹配度、问题解决由大模型判断；AI 未完成时该维度显示「待AI质检」、暂不计分，AI 完成后自动重算。<br>
          <b>规则维度：</b>响应速度、售前必问、引导留资、优惠触达按关键词/时间/联系方式自动判定。
        </div>
        <table style="border-collapse:collapse;border:1px solid #e3e8f2;width:100%">
        <tr style="background:#f1edff;color:#4c3f8f">
          <th style="padding:8px 10px;text-align:left;width:120px">维度</th>
          <th style="padding:8px 10px;text-align:left">优秀</th>
          <th style="padding:8px 10px;text-align:left">良好</th>
          <th style="padding:8px 10px;text-align:left">合格</th>
          <th style="padding:8px 10px;text-align:left">不合格</th></tr>
        {''.join(rows)}
        </table>
        <p style="margin:12px 0 0"><b>总分：</b>6 个维度满分合计 {cfg.get('base_score', 100)} 分；及格线 {cfg.get('pass_score', 60)} 分；
        AI 维度未完成时只算规则维度，AI 完成后自动补齐。</p>
        <p style="margin:4px 0 0"><b>评级：</b>{band_txt}。</p>
        <p style="margin:4px 0 0"><b>致命项：</b>辱骂、私下交易、泄露敏感信息、虚假承诺、恶意推诿等，人工确认后按规则库判不合格。</p>
        </body></html>"""
        dlg = QDialog(self)
        dlg.setWindowTitle("评分规则 · 各档位详细标准")
        dlg.resize(1240, 800)
        lay = QVBoxLayout(dlg)
        browser = QTextBrowser()
        browser.setHtml(html_text)
        browser.setOpenExternalLinks(False)
        lay.addWidget(browser, 1)
        btn = QPushButton("知道了"); btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

    def _perform_rescore(self, confirm: bool = True, title: str = "重算评分") -> dict | None:
        if not self.records:
            QMessageBox.information(self, "提示", "还没有导入数据。")
            return None
        active_title = str(self.runner.scoring.config.get("title") or "当前评分标准")
        active_version = str(self.runner.scoring.config.get("version") or "")
        if confirm:
            answer = QMessageBox.question(
                self, title,
                f"将按「{active_title}」（{active_version}）重算 {len(self.records)} 条会话的分数与判定。\n\n"
                "AI 判定与已完成的人工复核会保留；未复核的会话状态会按该标准重置。\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
        before = {r["id"]: (r.get("final_score"), r.get("final_status")) for r in self.records}
        progress = QProgressDialog("正在重算评分…", None, 0, len(self.records), self)
        progress.setWindowTitle(title)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = self.runner.rescore(
                self.records,
                progress=lambda done, total: (progress.setValue(done), QApplication.processEvents()),
            )
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
        self._refresh_all()
        after = {r["id"]: (r.get("final_score"), r.get("final_status")) for r in self.records}
        changed_score = sum(1 for k, v in before.items() if k in after and after[k][0] != v[0])
        changed_status = sum(1 for k, v in before.items() if k in after and after[k][1] != v[1])
        if hasattr(self, "std_btn"):
            try:
                self.std_btn.setToolTip(f"查看/切换评分标准（当前：{active_title}）")
            except Exception:
                pass
        if not changed_score and not changed_status:
            QMessageBox.information(
                self, title + "完成",
                f"已按「{active_title}」重算完成，{len(after)} 条会话评分没有变化。\n\n"
                "说明：这批数据原本就是按该标准计算的；切换标准或修改配置后才会变化。")
        else:
            QMessageBox.information(
                self, title + "完成",
                f"已按「{active_title}」重算 {info['processed']} 条会话：\n"
                f"评分更新 {changed_score} 条，判定状态变化 {changed_status} 条。")
        return info

    def _open_deduction_dialog(self):
        rows = self.filtered if hasattr(self, "filtered") else self.records
        DeductionDialog(rows, self).exec()

    def _open_copilot(self):
        try:
            self._open_copilot_impl()
        except Exception as exc:
            _report_error(self, "打开爆单一铲失败", exc)

    def _open_copilot_impl(self):
        if getattr(self, "_copilot_dlg", None) is None:
            dlg = QDialog(None)
            dlg.setWindowFlag(Qt.WindowType.Window, True)
            dlg.setWindowModality(Qt.WindowModality.NonModal)
            dlg.setWindowTitle("爆单一铲 · AI 质检副驾")
            dlg.setObjectName("copilotDialog")
            dlg.resize(1180, 820)
            dlg.setSizeGripEnabled(True)
            container = QVBoxLayout(dlg)
            container.setContentsMargins(0, 0, 0, 0)
            container.addWidget(self._page_copilot())
            self._copilot_dlg = dlg
        self._refresh_copilot_context()
        self._copilot_dlg.show()
        self._copilot_dlg.raise_()
        self._copilot_dlg.activateWindow()

    def _page_copilot(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        t = QLabel("爆单一铲")
        t.setObjectName("title")
        sub = QLabel("AI 销售洞察与质检副驾")
        sub.setObjectName("pageHint")
        head.addWidget(t)
        head.addWidget(sub)
        head.addStretch(1)
        head.addWidget(QLabel("数据范围"))
        self._copilot_scope_combo = QComboBox()
        self._copilot_scope_combo.setObjectName("copilotScope")
        self._copilot_scope_combo.addItem("当前筛选")
        self._copilot_scope_combo.addItem("全部数据")
        self._copilot_scope_combo.setToolTip(
            "当前筛选 = 质检总览上筛选出来的会话（默认）；全部数据 = 数据库里所有会话"
        )
        self._copilot_scope_combo.currentIndexChanged.connect(self._refresh_copilot_context)
        head.addWidget(self._copilot_scope_combo)
        head.addSpacing(8)
        head.addWidget(QLabel("阅读方式"))
        self._copilot_read_combo = QComboBox()
        self._copilot_read_combo.setObjectName("copilotReadMode")
        self._copilot_read_combo.addItem("卡片摘要")
        self._copilot_read_combo.addItem("全文精读")
        self._copilot_read_combo.setToolTip(
            "卡片摘要：读每条会话的关键句（快、便宜）；全文精读：读完整对话原文（能发现联系方式、承诺细节，但更慢更贵）"
        )
        head.addWidget(self._copilot_read_combo)
        lay.addLayout(head)

        self._copilot_ctx = QLabel("")
        self._copilot_ctx.setObjectName("copilotContext")
        self._copilot_ctx.setWordWrap(True)
        lay.addWidget(self._copilot_ctx)

        body = QHBoxLayout()
        body.setSpacing(12)

        side = QFrame()
        side.setObjectName("copilotSide")
        side.setFixedWidth(212)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(10, 10, 10, 10)
        sl.setSpacing(8)
        new_btn = QPushButton("＋ 新建对话")
        new_btn.setObjectName("primary")
        new_btn.clicked.connect(self._copilot_new)
        sl.addWidget(new_btn)
        hist_row = QHBoxLayout()
        hist_row.setSpacing(6)
        hist_row.addWidget(QLabel("历史对话"))
        hist_row.addStretch(1)
        self._copilot_del_btn = QPushButton("删除")
        self._copilot_del_btn.setObjectName("copilotDelBtn")
        self._copilot_del_btn.setToolTip("删除选中的历史对话（也可以右键对话/按 Delete 键）")
        self._copilot_del_btn.clicked.connect(lambda: self._copilot_delete_history())
        hist_row.addWidget(self._copilot_del_btn)
        sl.addLayout(hist_row)
        self._copilot_history = QListWidget()
        self._copilot_history.setObjectName("copilotHistory")
        self._copilot_history.currentRowChanged.connect(self._copilot_open_history)
        self._copilot_history.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._copilot_history.customContextMenuRequested.connect(self._copilot_history_menu)
        sl.addWidget(self._copilot_history, 1)
        delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._copilot_history)
        delete_shortcut.activated.connect(lambda: self._copilot_delete_history())
        body.addWidget(side)

        main_f = QFrame()
        main_f.setObjectName("copilotMain")
        ml = QVBoxLayout(main_f)
        ml.setContentsMargins(12, 12, 12, 12)
        ml.setSpacing(8)
        self._copilot_chat = QScrollArea()
        self._copilot_chat.setObjectName("copilotChat")
        self._copilot_chat.setWidgetResizable(True)
        self._copilot_chat.setFrameShape(QFrame.Shape.NoFrame)
        self._copilot_chat_canvas = QWidget()
        self._copilot_chat_canvas.setObjectName("copilotChatCanvas")
        self._copilot_chat_lay = QVBoxLayout(self._copilot_chat_canvas)
        self._copilot_chat_lay.setContentsMargins(12, 12, 12, 12)
        self._copilot_chat_lay.setSpacing(10)
        self._copilot_chat_lay.addStretch(1)
        self._copilot_chat.setWidget(self._copilot_chat_canvas)
        ml.addWidget(self._copilot_chat, 1)

        cap_row = QHBoxLayout()
        cap_row.setSpacing(8)
        self._capsule_scroll = QScrollArea()
        self._capsule_scroll.setObjectName("capsuleBar")
        self._capsule_scroll.setWidgetResizable(True)
        self._capsule_scroll.setFixedHeight(48)
        self._capsule_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._capsule_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._capsule_host = QWidget()
        self._capsule_host.setObjectName("capsuleHost")
        self._capsule_lay = QHBoxLayout(self._capsule_host)
        self._capsule_lay.setContentsMargins(2, 6, 2, 6)
        self._capsule_lay.setSpacing(6)
        self._capsule_lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._capsule_scroll.setWidget(self._capsule_host)
        cap_row.addWidget(self._capsule_scroll, 1)
        manage = QPushButton("⚙️ 管理")
        manage.setToolTip("管理提示词胶囊：增删改、启用/禁用")
        manage.clicked.connect(self._manage_capsules)
        cap_row.addWidget(manage)
        ml.addLayout(cap_row)

        self._copilot_input = ChatInput()
        self._copilot_input.setObjectName("copilotInput")
        self._copilot_input.setPlaceholderText(
            "输入你的问题…（Enter 发送，Shift+Enter 换行；点上方胶囊可快速填入专业提问）"
        )
        self._copilot_input.setFixedHeight(112)
        self._copilot_input.send_requested.connect(self._copilot_send_safe)
        self._copilot_send_btn = QPushButton("发送")
        self._copilot_send_btn.setObjectName("primary")
        self._copilot_send_btn.setMinimumWidth(88)
        self._copilot_send_btn.clicked.connect(self._copilot_send_safe)
        self._copilot_stop_btn = QPushButton("停止")
        self._copilot_stop_btn.setMinimumWidth(72)
        self._copilot_stop_btn.setVisible(False)
        self._copilot_stop_btn.clicked.connect(self._copilot_stop)
        inp_row = QHBoxLayout()
        inp_row.setSpacing(8)
        inp_row.addWidget(self._copilot_input, 1)
        inp_row.addWidget(self._copilot_stop_btn)
        inp_row.addWidget(self._copilot_send_btn)
        ml.addLayout(inp_row)

        body.addWidget(main_f, 1)
        lay.addLayout(body, 1)

        self._copilot_page = page
        self._copilot_convos: list[dict] = load_history(COPILOT_HISTORY_PATH)
        self._copilot_current = -1
        self._copilot_items: list[dict] = []
        self._copilot_stream_item = None
        self._copilot_analysis_label = ""
        self._copilot_deep_total = 0
        self._copilot_deep_batches = 1
        self._copilot_running = False
        self._copilot_stopped = False
        self._copilot_thread = None
        self._copilot_timer = QTimer(self)
        self._copilot_timer.setInterval(80)
        self._copilot_timer.timeout.connect(self._copilot_flush_stream)
        for convo in self._copilot_convos:
            self._copilot_history.addItem(str(convo.get("title") or "未命名对话"))
        self.capsules = load_capsules()
        self._copilot_new()
        return page

    def _copilot_use_all(self) -> bool:
        combo = getattr(self, "_copilot_scope_combo", None)
        return combo is not None and combo.currentIndex() == 1

    def _copilot_read_mode(self) -> str:
        combo = getattr(self, "_copilot_read_combo", None)
        return "full" if (combo is not None and combo.currentIndex() == 1) else "card"

    def _copilot_rows(self) -> list[dict]:
        return self.records if self._copilot_use_all() else self.filtered

    def _filter_summary_text(self) -> str:
        if self._copilot_use_all():
            return f"全部数据（共 {len(self.records)} 条）"
        parts = []
        for label, combo in (("店铺", self.f_store), ("客服", self.f_agent), ("产品", self.f_product),
                             ("阶段", self.f_stage), ("商机", self.f_lead), ("有效", self.f_valid)):
            value = combo.currentText()
            if value and value != "全部":
                parts.append(f"{label}={value}")
        d1 = self.f_start.date().toString("yyyy-MM-dd")
        d2 = self.f_end.date().toString("yyyy-MM-dd")
        parts.append(f"日期={d1}~{d2}")
        parts.append(f"共 {len(self.filtered)} 条")
        return "，".join(parts)

    def _refresh_copilot_context(self):
        if not hasattr(self, "_copilot_ctx"):
            return
        self._copilot_ctx.setText("数据范围：" + self._filter_summary_text())
        self._rebuild_capsules()
        if len(getattr(self, "_copilot_items", [])) <= 1:
            self._copilot_new(keep_history=True)

    # ---------- 聊天气泡渲染 ----------

    def _copilot_welcome(self) -> dict:
        return {
            "role": "assistant",
            "content": (
                "### 爆单一铲 · AI 质检副驾\n\n"
                f"当前范围：**{self._filter_summary_text()}**\n\n"
                "**可以帮你做三件事**\n"
                "- **商机复盘**：找出最可能丢单的会话，指出错过推进的轮次\n"
                "- **应答检查**：质保、会议室场景、竞品对比是否说清\n"
                "- **话术生成**：给出可直接发客户、不超过 80 字的跟进话术\n\n"
                "右上角可选**数据范围**（当前筛选 / 全部数据）和**阅读方式**（卡片摘要 / 全文精读）。\n"
                "- **卡片摘要**：快、便宜，适合看整体共性问题；\n"
                "- **全文精读**：读完整对话，能发现联系方式、承诺细节等，较慢较贵；\n"
                "- **数量/占比/排名**类问题自动走全量 SQL 统计。"
            ),
            "thinking": [],
            "expanded": False,
            "streaming": False,
        }

    def _copilot_new(self, keep_history: bool = False):
        if self._copilot_running:
            self._copilot_stop()
        self._copilot_items: list[dict] = []
        self._copilot_current = -1
        self._copilot_stream_item = None
        if not keep_history:
            self._copilot_history.blockSignals(True)
            self._copilot_history.setCurrentRow(-1)
            self._copilot_history.blockSignals(False)
        self._copilot_clear_chat()
        self._copilot_add_item(self._copilot_welcome())
        if hasattr(self, "_copilot_input"):
            self._copilot_input.clear()
            self._copilot_input.setFocus()

    def _copilot_clear_chat(self):
        while self._copilot_chat_lay.count() > 1:
            item = self._copilot_chat_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _copilot_scroll_bottom(self):
        bar = self._copilot_chat.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _copilot_add_item(self, item: dict) -> dict:
        if not hasattr(self, "_copilot_items"):
            self._copilot_items = []
        self._copilot_items.append(item)
        row = self._copilot_build_row(item)
        self._copilot_chat_lay.insertWidget(self._copilot_chat_lay.count() - 1, row)
        QTimer.singleShot(0, self._copilot_scroll_bottom)
        return item

    def _copilot_build_row(self, item: dict) -> QWidget:
        me = item.get("role") == "user"
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        if me:
            avatar = QLabel("运")
            avatar.setObjectName("copilotAvatarMe")
        else:
            _detect_emoji_font()
            avatar = QLabel(SHOVEL_EMOJI if EMOJI_FONT_FAMILY else "铲")
            avatar.setObjectName("copilotAvatarAi")
            avatar.setFont(QFont(EMOJI_FONT_FAMILY or UI_FONT_FAMILY, 16))
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        col = QVBoxLayout()
        col.setSpacing(4)

        think_box = None
        think_btn = None
        think_body = None
        if not me:
            think_box = QFrame()
            think_box.setObjectName("copilotThinkBox")
            tb = QVBoxLayout(think_box)
            tb.setContentsMargins(10, 6, 10, 6)
            tb.setSpacing(3)
            think_btn = QPushButton("▸ 思考过程")
            think_btn.setObjectName("copilotThinkToggle")
            think_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            think_btn.clicked.connect(lambda _=False, it=item: self._copilot_toggle_think(it))
            think_body = QLabel()
            think_body.setObjectName("copilotThinkText")
            think_body.setWordWrap(True)
            think_body.setTextFormat(Qt.TextFormat.RichText)
            tb.addWidget(think_btn)
            tb.addWidget(think_body)
            col.addWidget(think_box)

        bubble = QLabel()
        bubble.setObjectName("copilotBubbleMe" if me else "copilotAiContent")
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.TextFormat.RichText)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        if me:
            bubble.setMaximumWidth(560)
        else:
            bubble.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        col.addWidget(bubble)

        item["_bubble"] = bubble
        item["_think_box"] = think_box
        item["_think_btn"] = think_btn
        item["_think_body"] = think_body

        if me:
            self._copilot_paint_user(item)
            h.addStretch(1)
            h.addLayout(col)
            h.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
        else:
            self._copilot_paint_ai(item)
            self._copilot_sync_think(item)
            h.addWidget(avatar, 0, Qt.AlignmentFlag.AlignTop)
            h.addLayout(col, 1)
        return row

    def _copilot_paint_user(self, item: dict):
        bubble = item.get("_bubble")
        if bubble is None:
            return
        text = _md_escape(str(item.get("content") or "")).replace("\n", "<br>")
        bubble.setText(text or "&nbsp;")

    def _copilot_paint_ai(self, item: dict):
        bubble = item.get("_bubble")
        if bubble is None:
            return
        content = str(item.get("content") or "")
        bubble.setText(_md_to_html(content) if content.strip() else "…")
        QTimer.singleShot(0, self._copilot_scroll_bottom)

    def _copilot_sync_think(self, item: dict):
        box = item.get("_think_box")
        btn = item.get("_think_btn")
        body = item.get("_think_body")
        if box is None or btn is None or body is None:
            return
        lines = item.get("thinking") or []
        if not lines:
            box.setVisible(False)
            return
        box.setVisible(True)
        body.setText("<br>".join(_md_escape(t) for t in lines))
        expanded = bool(item.get("expanded"))
        if item.get("streaming"):
            expanded = True
            btn.setText("▾ 思考过程（进行中）")
        else:
            btn.setText("▾ 思考过程（已完成）" if expanded else "▸ 思考过程（已完成）")
        body.setVisible(expanded)

    def _copilot_toggle_think(self, item: dict):
        item["expanded"] = not bool(item.get("expanded"))
        self._copilot_sync_think(item)

    def _copilot_think(self, item: dict, line: str):
        item.setdefault("thinking", []).append(str(line))
        self._copilot_sync_think(item)
        QTimer.singleShot(0, self._copilot_scroll_bottom)

    # ---------- 会话流程 ----------

    def _copilot_begin_user(self, text: str):
        self._copilot_add_item({"role": "user", "content": text, "thinking": []})
        self._register_conversation(text)
        convo = self._copilot_convos[self._copilot_current]
        convo.setdefault("messages", []).append({"role": "user", "content": text, "thinking": []})
        convo["filter"] = self._filter_summary_text()

    def _copilot_start_answer(self) -> dict:
        item = {"role": "assistant", "content": "", "thinking": [],
                "expanded": True, "streaming": True}
        self._copilot_add_item(item)
        self._copilot_stream_item = item
        return item

    def _copilot_finish_answer(self, item: dict, text: str = ""):
        self._copilot_timer.stop()
        content = (text or item.get("content") or "").strip()
        if self._copilot_stopped and content:
            content += "\n\n> （已停止生成）"
        item["content"] = content or "（没有生成内容）"
        item["streaming"] = False
        item["expanded"] = False
        item["streaming"] = False
        self._copilot_paint_ai(item)
        self._copilot_sync_think(item)
        self._copilot_stream_item = None
        self._copilot_thread = None
        self._copilot_set_running(False)
        convo = self._copilot_convos[self._copilot_current] if 0 <= self._copilot_current < len(self._copilot_convos) else None
        if convo is not None:
            convo["messages"] = self._copilot_serialize()
            save_history(COPILOT_HISTORY_PATH, self._copilot_convos)
        QTimer.singleShot(0, self._copilot_scroll_bottom)

    def _copilot_serialize(self) -> list[dict]:
        out = []
        for item in getattr(self, "_copilot_items", []):
            content = str(item.get("content") or "")
            thinking = list(item.get("thinking") or [])
            if not content and not thinking:
                continue
            out.append({"role": item.get("role", "assistant"), "content": content, "thinking": thinking})
        return out

    def _copilot_flush_stream(self):
        item = self._copilot_stream_item
        if item is None:
            return
        self._copilot_paint_ai(item)

    def _copilot_on_delta(self, chunk: str):
        item = self._copilot_stream_item
        if item is None:
            return
        item["content"] = str(item.get("content") or "") + chunk
        if not self._copilot_timer.isActive():
            self._copilot_timer.start()

    def _copilot_on_done(self, text: str):
        item = self._copilot_stream_item
        if item is None:
            return
        label = getattr(self, "_copilot_analysis_label", "")
        if label and getattr(self, "_copilot_deep_total", 0):
            self._copilot_think(
                item,
                f"{label}完成：覆盖 {self._copilot_deep_total} 条（分 {self._copilot_deep_batches} 批）",
            )
        self._copilot_finish_answer(item, text)

    def _copilot_on_failed(self, message: str):
        item = self._copilot_stream_item
        if item is None:
            return
        partial = str(item.get("content") or "").strip()
        item["content"] = (partial + "\n\n" if partial else "") + f"> ⚠️ 请求失败：{message}"
        self._copilot_finish_answer(item, item["content"])

    def _copilot_set_running(self, running: bool):
        self._copilot_running = running
        if hasattr(self, "_copilot_send_btn"):
            self._copilot_send_btn.setEnabled(not running)
        if hasattr(self, "_copilot_stop_btn"):
            self._copilot_stop_btn.setEnabled(True)
            self._copilot_stop_btn.setVisible(running)
        self._copilot_input.setReadOnly(running)

    def _copilot_stop(self):
        if self._copilot_thread is not None:
            self._copilot_stopped = True
            self._copilot_thread.stop()
            if hasattr(self, "_copilot_stop_btn"):
                self._copilot_stop_btn.setEnabled(False)

    # ---------- 路由 ----------

    @staticmethod
    def _copilot_is_stats_question(text: str) -> bool:
        low = (text or "").lower()
        return any(h in low for h in STATS_HINTS)

    # ---------- 发送 ----------

    def _copilot_send_safe(self):
        try:
            self._copilot_send()
        except Exception as exc:
            _report_error(self, "发送失败", exc)

    def _copilot_send(self):
        text = self._copilot_input.toPlainText().strip()
        if not text or self._copilot_running:
            return
        cfg = load_ai_config()
        if not (cfg.get("base_url") and cfg.get("model") and cfg.get("api_key")):
            parent = getattr(self, "_copilot_dlg", None) or self
            QMessageBox.warning(parent, "提示", "尚未配置智能接口：到「智能设置」填写地址、模型和密钥后保存。")
            return
        self._copilot_ctx.setText("数据范围：" + self._filter_summary_text())
        self._copilot_stopped = False
        self._copilot_input.clear()

        if self._copilot_is_stats_question(text):
            self._copilot_stats_send(text, cfg)
            return

        rows = self._copilot_rows()
        if self._copilot_read_mode() == "full":
            self._copilot_fulltext_send(text, cfg)
            return
        if len(rows) > 200:
            # 范围较大时不再弹阻塞窗口，直接按批自动分析（窗口内只显示一行提示，可随时停止）
            self._copilot_deep_send(text, cfg)
            return

        ctx = build_context(rows, 200)
        system = build_system_prompt(ctx, self._filter_summary_text())
        self._copilot_begin_user(text)
        ai_item = self._copilot_start_answer()
        self._copilot_think(ai_item, f"已读取当前范围 {ctx['total']} 条会话")
        self._copilot_think(ai_item, f"已注入 {ctx['included']} 条会话摘要（A 级优先）")
        if ctx["truncated"]:
            self._copilot_think(ai_item, f"另有 {ctx['truncated']} 条未注入")
        self._copilot_think(ai_item, "正在等待模型返回…")
        convo = self._copilot_convos[self._copilot_current]
        messages = self._copilot_messages(system, convo, text)
        self._copilot_set_running(True)
        self._copilot_thread = CopilotThread(cfg, messages)
        self._copilot_thread.delta.connect(self._copilot_on_delta)
        self._copilot_thread.finished_ok.connect(self._copilot_on_done)
        self._copilot_thread.failed.connect(self._copilot_on_failed)
        self._copilot_thread.start()

    def _copilot_stats_send(self, text: str, cfg: dict):
        if self._copilot_use_all():
            filters = {}
        else:
            filters = {
                "store": self.f_store.currentText(),
                "agent": self.f_agent.currentData() or self.f_agent.currentText(),
                "product": self.f_product.currentText(),
                "stage": self.f_stage.currentText(),
                "lead": self.f_lead.currentText(),
                "validity": self.f_valid.currentText(),
                "date_start": self.f_start.date().toString("yyyy-MM-dd"),
                "date_end": self.f_end.date().toString("yyyy-MM-dd"),
            }
        self._copilot_begin_user(text)
        ai_item = self._copilot_start_answer()
        self._copilot_think(ai_item, "识别为统计类问题，准备全量计算")
        self._copilot_think(ai_item, f"数据范围：{self._filter_summary_text()}")
        self._copilot_set_running(True)
        self._copilot_thread = StatsThread(cfg, text, filters, self._filter_summary_text(), self.runner.db.path)
        self._copilot_thread.sql_ready.connect(lambda sql, n: self._copilot_on_sql(ai_item, sql, n))
        self._copilot_thread.delta.connect(self._copilot_on_delta)
        self._copilot_thread.finished_ok.connect(self._copilot_on_done)
        self._copilot_thread.failed.connect(self._copilot_on_failed)
        self._copilot_thread.start()

    def _copilot_on_sql(self, item: dict, sql: str, row_count: int):
        self._copilot_think(item, f"已生成只读 SQL，命中 {row_count} 行")
        self._copilot_think(item, f"SQL：{sql}")
        self._copilot_think(item, "正在整理结论…")

    def _copilot_fulltext_send(self, text: str, cfg: dict):
        rows = self._copilot_rows()
        texts = [conversation_text(r) for r in rows]
        chars = sum(len(t) for t in texts)
        payloads = batch_texts(texts) or [""]
        self._copilot_analysis_label = "全文精读"
        self._copilot_deep_total = len(rows)
        self._copilot_deep_batches = len(payloads)
        self._copilot_begin_user(text)
        ai_item = self._copilot_start_answer()
        self._copilot_think(ai_item, f"全文精读：{len(rows)} 条 / {len(payloads)} 批（可随时停止）")
        self._copilot_set_running(True)
        self._copilot_thread = DeepAnalysisThread(cfg, text, self._filter_summary_text(), payloads,
                                                  mode="full", covered=len(rows))
        self._copilot_thread.progress.connect(
            lambda done, total, message: self._copilot_think(ai_item, f"第 {done}/{total} 批 · {message}")
        )
        self._copilot_thread.delta.connect(self._copilot_on_delta)
        self._copilot_thread.finished_ok.connect(self._copilot_on_done)
        self._copilot_thread.failed.connect(self._copilot_on_failed)
        self._copilot_thread.start()

    def _copilot_deep_send(self, text: str, cfg: dict):
        rows = self._copilot_rows()
        cards = [summary_line(r) for r in rows]
        payloads = ["\n".join(cards[i:i + BATCH_CARDS]) for i in range(0, len(cards), BATCH_CARDS)] or [""]
        self._copilot_analysis_label = "全量分析"
        self._copilot_deep_total = len(cards)
        self._copilot_deep_batches = len(payloads)
        self._copilot_begin_user(text)
        ai_item = self._copilot_start_answer()
        self._copilot_think(ai_item, f"范围较大（{len(cards)} 条），自动按 {BATCH_CARDS} 条/批分析，共 {len(payloads)} 批（可随时停止）")
        self._copilot_set_running(True)
        self._copilot_thread = DeepAnalysisThread(cfg, text, self._filter_summary_text(), payloads,
                                                  mode="card", covered=len(cards))
        self._copilot_thread.progress.connect(
            lambda done, total, message: self._copilot_think(ai_item, f"第 {done}/{total} 批 · {message}")
        )
        self._copilot_thread.delta.connect(self._copilot_on_delta)
        self._copilot_thread.finished_ok.connect(self._copilot_on_done)
        self._copilot_thread.failed.connect(self._copilot_on_failed)
        self._copilot_thread.start()

    @staticmethod
    def _copilot_messages(system: str, convo: dict, text: str) -> list[dict]:
        history = [{"role": m.get("role", "user"), "content": str(m.get("content") or "")}
                   for m in (convo.get("messages") or []) if m.get("content")]
        if history and history[-1]["role"] == "user" and history[-1]["content"] == text:
            history = history[:-1]
        history = history[-10:]
        return [{"role": "system", "content": system}] + history + [{"role": "user", "content": text}]

    # ---------- 历史 ----------

    def _register_conversation(self, text: str):
        if self._copilot_current >= 0:
            return
        title = text[:18] + ("…" if len(text) > 18 else "")
        convo = {
            "id": str(int(datetime.now().timestamp())),
            "title": title,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "filter": self._filter_summary_text(),
            "messages": [],
        }
        self._copilot_convos.append(convo)
        self._copilot_current = len(self._copilot_convos) - 1
        self._copilot_history.blockSignals(True)
        self._copilot_history.addItem(title)
        self._copilot_history.setCurrentRow(self._copilot_current)
        self._copilot_history.blockSignals(False)

    def _copilot_open_history(self, row: int):
        if self._copilot_running or not (0 <= row < len(self._copilot_convos)):
            return
        self._copilot_current = row
        convo = self._copilot_convos[row]
        self._copilot_clear_chat()
        self._copilot_items = []
        self._copilot_stream_item = None
        messages = convo.get("messages") or []
        if not messages:
            self._copilot_add_item(self._copilot_welcome())
            return
        for msg in messages:
            item = {
                "role": msg.get("role", "assistant"),
                "content": str(msg.get("content") or ""),
                "thinking": list(msg.get("thinking") or []),
                "expanded": False,
                "streaming": False,
            }
            self._copilot_add_item(item)
        QTimer.singleShot(0, self._copilot_scroll_bottom)

    def _copilot_history_menu(self, pos):
        item = self._copilot_history.itemAt(pos)
        menu = QMenu(self)
        delete_action = menu.addAction("删除此对话")
        delete_action.setEnabled(item is not None)
        menu.addSeparator()
        clear_action = menu.addAction("清空全部历史")
        clear_action.setEnabled(bool(self._copilot_convos))
        chosen = menu.exec(self._copilot_history.viewport().mapToGlobal(pos))
        if chosen is delete_action and item is not None:
            self._copilot_delete_history(self._copilot_history.row(item))
        elif chosen is clear_action:
            self._copilot_clear_history()

    def _copilot_delete_history(self, row: int | None = None):
        if self._copilot_running:
            QMessageBox.information(self, "提示", "正在生成回答，请先点「停止」再删除。")
            return
        if row is None:
            row = self._copilot_history.currentRow()
        if not (0 <= row < len(self._copilot_convos)):
            QMessageBox.information(self, "提示", "请先在左侧选中要删除的对话。")
            return
        title = str(self._copilot_convos[row].get("title") or "未命名对话")
        answer = QMessageBox.question(
            self, "删除对话",
            f"确定删除对话「{title}」吗？\n\n删除后不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        del self._copilot_convos[row]
        self._copilot_history.blockSignals(True)
        self._copilot_history.takeItem(row)
        self._copilot_history.blockSignals(False)
        if row == self._copilot_current:
            self._copilot_current = -1
            self._copilot_new(keep_history=True)
            self._copilot_history.blockSignals(True)
            self._copilot_history.setCurrentRow(-1)
            self._copilot_history.blockSignals(False)
        elif row < self._copilot_current:
            self._copilot_current -= 1
            self._copilot_history.blockSignals(True)
            self._copilot_history.setCurrentRow(self._copilot_current)
            self._copilot_history.blockSignals(False)
        save_history(COPILOT_HISTORY_PATH, self._copilot_convos)

    def _copilot_clear_history(self):
        if self._copilot_running:
            QMessageBox.information(self, "提示", "正在生成回答，请先点「停止」再清空。")
            return
        total = len(self._copilot_convos)
        if total == 0:
            QMessageBox.information(self, "提示", "当前没有历史对话。")
            return
        answer = QMessageBox.question(
            self, "清空历史",
            f"确定清空全部 {total} 条历史对话吗？\n\n删除后不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._copilot_convos.clear()
        self._copilot_history.blockSignals(True)
        self._copilot_history.clear()
        self._copilot_history.setCurrentRow(-1)
        self._copilot_history.blockSignals(False)
        self._copilot_current = -1
        self._copilot_new(keep_history=True)
        save_history(COPILOT_HISTORY_PATH, self._copilot_convos)

    def _capsule_filter_tags(self) -> set[str]:
        tags: set[str] = set()
        stage = self.f_stage.currentText()
        if stage in ("售前", "售后"):
            tags.add(stage)
        lead = self.f_lead.currentText()
        if lead in ("A", "B", "C"):
            tags.add(f"{lead}级")
        if self.f_valid.currentText() == "无效":
            tags.add("未成交")
        return tags

    def _rebuild_capsules(self):
        if not hasattr(self, "_capsule_lay"):
            return
        while self._capsule_lay.count():
            item = self._capsule_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        tags = self._capsule_filter_tags()
        caps = [c for c in self.capsules if c.get("enabled", True)]
        caps.sort(key=lambda c: 0 if (tags & set(c.get("default_tags") or [])) else 1)
        if not caps:
            hint = QLabel("暂无启用的胶囊，点右侧「管理胶囊」添加")
            hint.setObjectName("pageHint")
            self._capsule_lay.addWidget(hint)
        for c in caps:
            rec = bool(tags & set(c.get("default_tags") or []))
            btn = QPushButton(f"{c.get('icon', '')} {c.get('title', '')}".strip())
            btn.setObjectName("capsuleChip")
            btn.setProperty("recommended", "true" if rec else "false")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("点击填入提示词（不会直接发送）" + ("｜与当前筛选匹配" if rec else ""))
            btn.clicked.connect(lambda _=False, cap=c: self._fill_capsule(cap))
            self._capsule_lay.addWidget(btn)
        self._capsule_lay.addStretch(1)

    def _fill_capsule(self, cap: dict):
        prompt = str(cap.get("prompt") or "").strip()
        if not prompt:
            return
        current = self._copilot_input.toPlainText().strip()
        self._copilot_input.setPlainText(f"{current}\n\n{prompt}".strip() if current else prompt)
        cursor = self._copilot_input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._copilot_input.setTextCursor(cursor)
        self._copilot_input.setFocus()

    def _manage_capsules(self):
        dlg = CapsuleDialog(self.capsules, self)
        dlg.exec()
        self.capsules = dlg.capsules
        save_capsules(self.capsules)
        self._rebuild_capsules()

    def _switch_page(self, row):
        self.stack.setCurrentIndex(row)


def main() -> int:
    def _handle(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            (LOG_DIR / f"crash_{datetime.now():%Y%m%d_%H%M%S}.log").write_text(text, encoding="utf-8")
        except Exception:
            pass
        print(text, flush=True)

    sys.excepthook = _handle
    if hasattr(threading, "excepthook"):
        threading.excepthook = lambda args: _handle(args.exc_type, args.exc_value, args.exc_traceback)

    app = QApplication(sys.argv)
    # Qt 内置按钮/对话框汉化（是/否、确定/取消等），保证全中文
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    # 启动即套用浅色，避免窗口出现前闪一下黑底
    _detect_ui_font()
    app.setFont(QFont(UI_FONT_FAMILY, 10))
    app.setStyleSheet(_qss(LIGHT_QSS + COPILOT_QSS_LIGHT))
    try:
        win = MainWindow()
    except Exception as exc:
        _handle(type(exc), exc, exc.__traceback__)
        box = QMessageBox()
        box.setWindowTitle("启动失败")
        box.setIcon(QMessageBox.Icon.Critical)
        box.setText(f"程序启动失败：{type(exc).__name__}: {exc}")
        box.setInformativeText(f"错误详情已保存到：\n{LOG_DIR}")
        box.exec()
        return 1
    if "--selftest" in sys.argv:
        print("[自检] 程序目录：", APP_DIR, flush=True)
        print("[自检] 数据库：", win.runner.db.path, "| 已载入会话：", len(win.records), flush=True)
        win._page_copilot()
        print("[自检] 副驾页面构建成功，胶囊数：", len(win.capsules), flush=True)
        view_sql, params = stats_ai.build_view({})
        result = stats_ai.run_sql(win.runner.db.path, view_sql, params, "SELECT COUNT(*) AS c FROM v")
        print("[自检] 全量统计通道正常：", result["rows"], flush=True)
        print("[自检] 启动成功", flush=True)
        return 0
    win.show()
    win.showNormal()
    win.raise_()
    win.activateWindow()
    print("[启动] 窗口已显示", flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
