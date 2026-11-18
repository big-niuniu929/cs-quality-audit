from __future__ import annotations

import html
import math
import re
import sys
from pathlib import Path
from datetime import datetime, date

from PyQt6.QtCore import Qt, QTimer, QPointF, QThread, pyqtSignal, QSettings, QLibraryInfo, QTranslator
from PyQt6.QtGui import QPainter, QRadialGradient, QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget, QHeaderView, QListWidget, QListWidgetItem, QCheckBox, QProgressDialog,
    QSpinBox, QGraphicsDropShadowEffect,
)

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from qc_engine.services.runner import QCRunner, load_records, load_ai_config, save_ai_config


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
    """自绘柱状图（无额外依赖）。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self.labels: list[str] = []
        self.values: list[int] = []
        self.colors: list[str] = []
        self.light = False
        self.setMinimumHeight(170)

    def set_light(self, light: bool):
        self.light = light
        self.update()

    def set_data(self, labels: list[str], values: list[int], colors: list[str]):
        self.labels, self.values, self.colors = labels, values, colors
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        fg = QColor(30, 32, 40, 150) if self.light else QColor(255, 255, 255, 130)
        fg_label = QColor(30, 32, 40, 140) if self.light else QColor(255, 255, 255, 140)
        fg_val = QColor(30, 32, 40, 200) if self.light else QColor(255, 255, 255, 200)
        p.setPen(fg)
        f = QFont(); f.setPointSize(10)
        p.setFont(f)
        p.drawText(12, 20, self.title)
        if not self.values:
            return
        area_top, area_bottom = 36, h - 26
        max_v = max(self.values) or 1
        n = len(self.values)
        slot = (w - 24) / n
        bar_w = min(slot * 0.55, 90)
        for i, v in enumerate(self.values):
            bh = (area_bottom - area_top) * v / max_v
            x = 12 + i * slot + (slot - bar_w) / 2
            p.setBrush(QColor(self.colors[i] if i < len(self.colors) else "#7b5cff"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(int(x), int(area_bottom - bh), int(bar_w), int(bh), 4, 4)
            p.setPen(fg_val)
            p.drawText(int(x), max(44, int(area_bottom - bh - 6)), str(v))
            p.setPen(fg_label)
            p.drawText(int(x), area_bottom + 16, self.labels[i] if i < len(self.labels) else "")


class ChatView(QScrollArea):
    """微信风格聊天重现：浅灰会话底、绿/白圆角气泡、头像、系统消息居中。

    时间规则参照微信官方：
    - 当天消息每 5 分钟为一个跨度显示一次时间；
    - 超过 1 天、小于 1 周显示「星期几 时间」；
    - 超过 1 周显示「月日 时间」；
    - 点击时间标签可在简洁/完整格式间切换（如 2026年10月2日 星期五 15:30）。
    """

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("chatScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._full_time = False
        self._time_btns: list[tuple[QPushButton, str, str]] = []

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

        # 锚点取最后一条消息时间，作为「今天/昨天/一周内」的参照
        anchor = None
        for m in reversed(msgs):
            try:
                anchor = datetime.fromisoformat(str(m.get("sent_at") or ""))
                break
            except (ValueError, TypeError):
                continue

        last_day = None
        last_bucket = None
        first_of_day = True
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

            # 日期分隔线
            day_key = dt.date() if dt else None
            if dt and day_key != last_day:
                lay.addLayout(self._day_line(dt, anchor))
                last_day = day_key
                last_bucket = None
                first_of_day = True

            # 时间分组（当天 5 分钟跨度）
            if dt:
                bucket = (dt.hour, dt.minute // 5)
                if bucket != last_bucket:
                    lay.addLayout(self._time_line(dt, anchor, first_of_day))
                    last_bucket = bucket
                    first_of_day = False

            if role == "bot":
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
            who = str(row.get("agent") or "客服") if me else "客户"
            caption = f"{who} · {dt:%H:%M}" if dt else who
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
        cap.setAlignment(Qt.AlignmentFlag.AlignRight if me else Qt.AlignmentFlag.AlignLeft)
        bub = QLabel(text)
        bub.setObjectName("bubbleMe" if me else "bubbleOther")
        bub.setWordWrap(True)
        bub.setMaximumWidth(500)
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

    def _day_line(self, dt: datetime, anchor) -> QHBoxLayout:
        if anchor is None:
            text = f"{dt.year}年{dt.month}月{dt.day}日 {WEEK_CN[dt.weekday()]}"
        else:
            days = (anchor.date() - dt.date()).days
            if days == 0:
                text = "今天"
            elif days == 1:
                text = "昨天"
            else:
                text = f"{dt.month}月{dt.day}日 {WEEK_CN[dt.weekday()]}"
        pill = QLabel(text)
        pill.setObjectName("dayPill")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wrap = QHBoxLayout(); wrap.setContentsMargins(0, 12, 0, 2)
        wrap.addStretch(1); wrap.addWidget(pill, 0); wrap.addStretch(1)
        return wrap

    def _time_line(self, dt: datetime, anchor, first_of_day: bool = False) -> QHBoxLayout:
        compact, full = self._time_texts(dt, anchor)
        if first_of_day and compact != f"{dt:%H:%M}":
            compact = f"{dt:%H:%M}"
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
    def _time_texts(dt: datetime, anchor) -> tuple[str, str]:
        full = f"{dt.year}年{dt.month}月{dt.day}日 {WEEK_CN[dt.weekday()]} {dt:%H:%M}"
        hm = f"{dt:%H:%M}"
        if anchor is None:
            return f"{dt.month}月{dt.day}日 {hm}", full
        days = (anchor.date() - dt.date()).days
        if days == 0:
            compact = hm
        elif days == 1:
            compact = f"昨天 {hm}"
        elif days < 7:
            compact = f"{WEEK_CN[dt.weekday()]} {hm}"
        else:
            compact = f"{dt.month}月{dt.day}日 {hm}"
        return compact, full

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
QLabel#detailEvidence { background: #e7f5f6; border: 1px solid #c8e5e7; border-radius: 10px; padding: 9px; color: #285b63; }
QWidget#chatCanvas { background: #ededed; }
QFrame#chatHeader { background: #f7f7f7; border-bottom: 1px solid #e3e3e3; }
QScrollArea#chatScroll { background: #ededed; border: 1px solid #dce3ec; border-radius: 12px; }
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
QCalendarWidget { background: #ffffff; color: #1f2937; }
QCalendarWidget QToolButton { color: #334155; background: transparent; }
QCalendarWidget QAbstractItemView { background: #ffffff; color: #1f2937; selection-background-color: #6d4bff; selection-color: #ffffff; }
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
QLabel#detailEvidence { background: #e7f5f6; border: 1px solid #c8e5e7; border-radius: 10px; padding: 9px; color: #285b63; }
QWidget#chatCanvas { background: #ededed; }
QFrame#chatHeader { background: #f7f7f7; border-bottom: 1px solid #e3e3e3; }
QScrollArea#chatScroll { background: #ededed; border: 1px solid #dce3ec; border-radius: 12px; }
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
QCalendarWidget { background: #ffffff; color: #1f2937; }
QCalendarWidget QToolButton { color: #334155; background: transparent; }
QCalendarWidget QAbstractItemView { background: #ffffff; color: #1f2937; selection-background-color: #6d4bff; selection-color: #ffffff; }
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
          "problem_resolution": "问题解决", "lead_capture": "引导留资"}
FINAL_CN = {"合格": "合格", "不合格": "不合格", "needs_review": "待复核", "after_sale_record_only": "售后仅记录"}
WEEK_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
EXC_CN = {
    "FileNotFoundError": "找不到文件，请检查所选文件路径",
    "PermissionError": "文件被占用或无读取权限，请关闭占用它的程序后重试",
    "ValueError": "数据格式不正确，请确认选择的是同一时期导出的文件",
    "KeyError": "表格缺少必要字段",
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


def _extract_phone(r: dict) -> str:
    """从会话消息里提取电话号码（用于电销跟进列）。"""
    for m in r.get("messages", []):
        found = _phone_in_text(m.get("body_text", ""))
        if found:
            return found
    return ""


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

    def __init__(self, row: dict, runner: QCRunner | None, on_review=None, light: bool = False):
        super().__init__()
        self.setWindowTitle("会话详情")
        self.resize(880, 680)
        self.setObjectName("detailDialog")
        self.setAutoFillBackground(True)
        self.row = row
        self.runner = runner
        self.on_review = on_review
        self.light = light
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        dims = row.get("deductions") or {}
        dim_lines = "    ".join(f"{DIM_CN.get(k, k)} -{v}分" for k, v in dims.items() if v) or "无扣分项"
        ai_line = f"智能判定：{AI_CN.get(row.get('ai_judgment') or row.get('ai_status'), '待复核')}"
        if row.get("ai_reason"):
            ai_line += f"（{row['ai_reason'][:60]}）"
        fatal = row.get("fatal_candidates") or []
        fatal_line = f"｜ 致命候选 {len(fatal)} 项" if fatal else ""
        head = QLabel(
            f"客服 {row['agent'] or '-'} ｜ 客户 {row['customer'] or '-'} ｜ 店铺 {row['store_id'] or '-'} ｜ 时间 {row['first_message_at']} ｜ 型号 {(row['excel_labels'].get('model') or '').strip() or '-'}\n"
            f"阶段 {STAGE_CN.get(row['service_stage'], '-')} ｜ {VALID_CN.get(row['validity'], '-')} ｜ 商机 {row['lead_level'] or '-'} ｜ "
            f"电销 {'是' if row['tele_sales_lead'] else '否'} ｜ 计算分 {row['calculated_score'] if row['calculated_score'] is not None else '-'} ｜ 最终分 {_display_score(row) if _display_score(row) is not None else '-'} ｜ 复核 {REVIEW_CN.get(row['review_status'], '待复核')}{fatal_line}\n"
            f"扣分明细：{dim_lines}\n{ai_line}"
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

        # 微信风格聊天重现：浅灰底、绿/白气泡、头像与时间分组
        chat = ChatView(row)
        lay.addWidget(chat, 1)

        advice = QLabel(f"跟进建议：{row['follow_up_advice']}")
        advice.setObjectName("detailAdvice")
        advice.setWordWrap(True)
        lay.addWidget(advice)

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
            btn_fatal = QPushButton("确认致命项(59分)")
            btn_pass.clicked.connect(lambda: self._review("合格", self.score_input.value(), False))
            btn_fail.clicked.connect(lambda: self._review("不合格", self.score_input.value(), False))
            btn_fatal.clicked.connect(lambda: self._review("不合格", 59, True))
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
                self.score_input.setValue(59)
                score = 59
            else:
                score = self.score_input.value()
            self.on_review(self.row, status, score, self.note_input.text().strip() or "人工复核", fatal)
            self.accept()
        else:
            QMessageBox.information(self, "提示", "当前会话不支持人工复核。")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("品牌A 客服质检系统 4.0")
        self.resize(1360, 840)
        self.setMinimumSize(1080, 680)
        self.config_dir = Path(__file__).resolve().parent / "config"
        self.runner = QCRunner(self.config_dir)
        self.records: list[dict] = load_records(self.runner.db)
        self.filtered: list[dict] = []
        self._review_pending: list[dict] = []
        self._tele_rows: list[dict] = []
        self._settings = QSettings("品牌A", "QCQualityConsole")
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
        brand = QLabel("品牌A 质检控制台"); brand.setObjectName("brand")
        brand_meta = QLabel("客服会话 · 规则、智能与人工复核工作台"); brand_meta.setObjectName("brandMeta")
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
        qss = LIGHT_QSS if self.light else DARK_QSS
        QApplication.instance().setStyleSheet(qss)
        self._central_bg.set_light(self.light)
        self.chart_lead.set_light(self.light)
        self.chart_score.set_light(self.light)
        self._theme_btn.setText("☾" if self.light else "☼")
        self._theme_btn.setToolTip("切换到深色主题" if self.light else "切换到浅色主题")

    # ---------- 页面构建 ----------

    def _card(self) -> QFrame:
        return GlassCard()

    def _page_import(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(30, 30, 30, 30); lay.setSpacing(12)
        t = QLabel("数据导入"); t.setObjectName("title"); lay.addWidget(t)
        hint = QLabel("选择同期导出的一对文件：聊天记录 .log + 会话记录 .xlsx。数据按店铺累积保存，重复导入自动去重。")
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
        self.store_combo.setEditable(True)  # 允许直接输入新店铺名
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
        lay.addWidget(QLabel("历史批次"))
        batch_btn_row = QHBoxLayout()
        del_batch = QPushButton("删除选中批次"); del_batch.clicked.connect(self._delete_batch)
        batch_btn_row.addWidget(del_batch); batch_btn_row.addStretch()
        lay.addLayout(batch_btn_row)
        self.batch_table = QTableWidget(0, 6)
        self.batch_table.setHorizontalHeaderLabels(["批次", "店铺", "导入时间", "数据范围", "会话数", "匹配数"])
        self.batch_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 140), (1, 170), (2, 172), (4, 80), (5, 80)]:
            self.batch_table.setColumnWidth(col, w)
        self.batch_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.batch_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.batch_table.setAlternatingRowColors(True)
        self.batch_table.verticalHeader().setDefaultSectionSize(34)
        lay.addWidget(self.batch_table, 1)
        return page

    def _page_overview(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(24, 24, 24, 24); lay.setSpacing(10)
        t = QLabel("质检总览"); t.setObjectName("title"); lay.addWidget(t)
        stat_row = QHBoxLayout(); self.stat_labels = {}
        for key, name in [("total", "总会话"), ("pre", "售前"), ("post", "售后"), ("valid", "有效"),
                          ("a", "A 级"), ("b", "B 级"), ("c", "C 级"), ("tele", "电销线索"), ("avg", "售前平均分")]:
            card = self._card(); cl = QVBoxLayout(card); cl.setContentsMargins(12, 10, 12, 10)
            lab = QLabel(name); lab.setObjectName("statLabel")
            val = QLabel("-"); val.setObjectName("statValue")
            cl.addWidget(lab); cl.addWidget(val)
            stat_row.addWidget(card, 1); self.stat_labels[key] = val
        lay.addLayout(stat_row)

        fc = self._card(); fc.setObjectName("filterCard"); fl = QHBoxLayout(fc); fl.setContentsMargins(12, 8, 12, 8); fl.setSpacing(6)
        self.f_store = QComboBox(); self.f_agent = QComboBox(); self.f_product = QComboBox()
        self.f_stage = QComboBox(); self.f_lead = QComboBox(); self.f_valid = QComboBox()
        for combo, label, items in [
            (self.f_store, "店铺", ["全部"]), (self.f_agent, "客服", ["全部"]), (self.f_product, "产品", ["全部"]),
            (self.f_stage, "阶段", ["全部", "售前", "售后", "待复核"]),
            (self.f_lead, "商机", ["全部", "A", "B", "C", "无"]),
            (self.f_valid, "有效", ["全部", "有效", "无效", "待复核"]),
        ]:
            fl.addWidget(QLabel(label)); combo.addItems(items)
            combo.currentIndexChanged.connect(self._refresh_view)
            fl.addWidget(combo)
        self.f_start = QDateEdit(); self.f_start.setCalendarPopup(True)
        self.f_end = QDateEdit(); self.f_end.setCalendarPopup(True)
        for d in (self.f_start, self.f_end):
            d.setDisplayFormat("yyyy-MM-dd"); d.dateChanged.connect(self._refresh_view)
        fl.addWidget(QLabel("开始")); fl.addWidget(self.f_start)
        fl.addWidget(QLabel("结束")); fl.addWidget(self.f_end)
        lay.addWidget(fc)

        chart_row = QHBoxLayout()
        self.chart_lead = BarChart("商机等级分布")
        self.chart_score = BarChart("售前评分分布")
        for c in (self.chart_lead, self.chart_score):
            card = self._card(); cl = QVBoxLayout(card); cl.setContentsMargins(8, 8, 8, 8); cl.addWidget(c)
            chart_row.addWidget(card, 1)
        lay.addLayout(chart_row)

        btn_row = QHBoxLayout()
        ai_run = QPushButton("智能批量质检可疑会话"); ai_run.clicked.connect(self._ai_review_batch)
        ai_btn = QPushButton("智能总结当前筛选"); ai_btn.clicked.connect(self._ai_summarize)
        exp = QPushButton("导出 Excel"); exp.clicked.connect(self._export_excel)
        btn_row.addWidget(ai_run); btn_row.addWidget(ai_btn); btn_row.addStretch()
        btn_row.addWidget(exp)
        lay.addLayout(btn_row)

        self.table = QTableWidget(0, 11)
        self.table.setHorizontalHeaderLabels(["时间", "店铺", "客服", "产品", "阶段", "有效", "商机", "分数", "智能判定", "电话", "跟进建议"])
        self.table.horizontalHeader().setSectionResizeMode(10, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 168), (1, 168), (2, 74), (3, 78), (4, 60), (5, 64), (6, 54), (7, 56), (8, 90), (9, 114)]:
            self.table.setColumnWidth(col, w)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.doubleClicked.connect(self._open_detail)
        lay.addWidget(self.table, 1)
        return page

    def _page_review(self) -> QWidget:
        page = QWidget(); lay = QVBoxLayout(page); lay.setContentsMargins(24, 24, 24, 24); lay.setSpacing(10)
        t = QLabel("人工复核"); t.setObjectName("title"); lay.addWidget(t)
        hint = QLabel("规则初筛标记为可疑的会话在此确认或改判；双击行进入会话详情，可直接修改最终分并保存，保存后总览立即更新。致命项经人工确认后计 59 分并判不合格，所有操作写入审计日志。")
        hint.setObjectName("pageHint"); hint.setWordWrap(True); lay.addWidget(hint)
        btn_row = QHBoxLayout()
        refresh = QPushButton("刷新队列"); refresh.clicked.connect(self._refresh_all)
        btn_row.addWidget(refresh); btn_row.addStretch()
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
        self.tele_table = QTableWidget(0, 7)
        self.tele_table.setHorizontalHeaderLabels(["时间", "店铺", "客服", "客户", "产品", "电话号码", "跟进建议"])
        self.tele_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for col, w in [(0, 168), (1, 168), (2, 74), (3, 104), (4, 84), (5, 118)]:
            self.tele_table.setColumnWidth(col, w)
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

    def _refresh_all(self):
        if self.runner:
            self.records = load_records(self.runner.db)
        self._refresh_filters()
        self._refresh_view()
        self._refresh_batches()
        self._refresh_review()
        self._refresh_tele()

    def _refresh_filters(self):
        stores = sorted({r["store_id"] for r in self.records if r["store_id"]})
        agents = sorted({r["agent"] for r in self.records if r["agent"]})
        products = sorted({(r["excel_labels"].get("model") or "").strip() for r in self.records} - {"", "-"})
        for combo, items in [(self.f_store, stores), (self.f_agent, agents), (self.f_product, products)]:
            cur = combo.currentText()
            combo.blockSignals(True); combo.clear(); combo.addItem("全部"); combo.addItems(items)
            if cur:
                idx = combo.findText(cur)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.blockSignals(False)
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

    def _apply_filter(self) -> list[dict]:
        store = self.f_store.currentText()
        agent = self.f_agent.currentText()
        prod = self.f_product.currentText()
        stage = self.f_stage.currentText()
        lead = self.f_lead.currentText()
        valid = self.f_valid.currentText()
        d_start = self.f_start.date().toPyDate()
        d_end = self.f_end.date().toPyDate()
        out = []
        for r in self.records:
            if store != "全部" and r["store_id"] != store:
                continue
            if agent != "全部" and r["agent"] != agent:
                continue
            if prod != "全部" and (r["excel_labels"].get("model") or "").strip() != prod:
                continue
            if stage != "全部" and STAGE_CN.get(r["service_stage"]) != stage:
                continue
            if lead != "全部" and (r["lead_level"] or "无") != lead:
                continue
            if valid != "全部" and VALID_CN.get(r["validity"]) != valid:
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
        self.filtered = self._apply_filter()
        n = len(self.filtered)
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
        self.chart_lead.set_data(["A 级", "B 级", "C 级"], [lead["A"], lead["B"], lead["C"]],
                                 ["#b79bff", "#38e8ff", "#888780"])
        buckets = {"90-100": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
        for s in scores:
            k = "90-100" if s >= 90 else "80-89" if s >= 80 else "70-79" if s >= 70 else "60-69" if s >= 60 else "<60"
            buckets[k] += 1
        self.chart_score.set_data(list(buckets.keys()), list(buckets.values()),
                                  ["#38e8ff", "#7b5cff", "#b79bff", "#ff5c9d", "#e24b4a"])
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
            phone = _extract_phone(r)
            vals = [r["first_message_at"], r["store_id"], r["agent"] or "-",
                    _product_label(r),
                    STAGE_CN.get(r["service_stage"], ""), VALID_CN.get(r["validity"], ""), r["lead_level"] or "",
                    str(_display_score(r)) if _display_score(r) is not None else "-",
                    ai_label, phone, r["follow_up_advice"][:36]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.table.setItem(row, c, item)
            # AI 列着色：AI 有结果的标蓝色，规则标灰色
            if ai_label.startswith("智能"):
                self.table.item(row, 8).setForeground(QColor("#2972F4"))
            else:
                self.table.item(row, 8).setForeground(QColor("#8a9099"))

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
                    str(b["session_count"]), str(b["matched_count"])]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.batch_table.setItem(row, c, item)

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

    def _refresh_tele(self):
        if not hasattr(self, "tele_table"):
            return
        tele = [r for r in self.records if r["tele_sales_lead"]]
        self.tele_table.setRowCount(0)
        for r in tele:
            row = self.tele_table.rowCount()
            self.tele_table.insertRow(row)
            vals = [r["first_message_at"], r["store_id"], r["agent"] or "-", r["customer"],
                    _product_label(r), _extract_phone(r) or "—", r["follow_up_advice"][:46]]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                item.setToolTip(str(v))
                self.tele_table.setItem(row, c, item)
        self._tele_rows = tele

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
                self.nav.setCurrentRow(1)
        except Exception as exc:
            self.import_status.setText(f"导入失败：{_exc_cn(exc)}")

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
            DetailDialog(r, self.runner, self._save_review_cb).exec()

    def _open_review_detail(self):
        r = self._row_at(self.review_table)
        if r:
            DetailDialog(r, self.runner, self._save_review_cb).exec()

    def _open_tele_detail(self):
        r = self._row_at(self.tele_table)
        if r:
            DetailDialog(r, self.runner, self._save_review_cb).exec()

    def _save_review_cb(self, row: dict, status: str, score, note: str, fatal: bool):
        self.runner.save_review(row, status, score, note, "质检员", fatal)
        self._refresh_all()

    # ---------- AI ----------

    def _ai_test(self):
        from qc_engine.ai.client import AIClient
        cfg = {**load_ai_config(),
               "base_url": self.ai_url.text().strip(), "model": self.ai_model.text().strip(),
               "api_key": self.ai_key.text().strip(), "api_type": self.ai_type.currentData() or "chat_completions",
               "timeout_seconds": 60}
        ok, msg = AIClient(cfg).test_connection()
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

    def _ai_review_batch(self):
        if not self.filtered:
            QMessageBox.information(self, "提示", "当前筛选无数据"); return
        targets = self.filtered
        client = self._make_client()
        dlg = QProgressDialog("正在逐条质检可疑会话…", "取消", 0, len(targets), self)
        dlg.setObjectName("progressDialog")
        dlg.setAutoFillBackground(True)
        dlg.setWindowTitle("智能批量质检"); dlg.setMinimumDuration(0); dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setLabelText("质检处理中：0/" + str(len(targets)))

        def work(progress):
            done = 0
            for r in targets:
                if dlg.wasCanceled():
                    break
                if r["review_status"] == "completed" or (r["review_status"] != "pending" and r["service_stage"] != "needs_review"):
                    continue
                payload = {"conversation_id": r["id"], "messages": [
                    {"message_ref": f"message:{m['index']}", "sender_role": m["sender_role"], "body_text": m["body_text"]}
                    for m in r["messages"]]}
                result = client.judge_conversation(payload)
                self.runner.db.update_ai_judgment(r["id"], result.get("status", "failed"),
                                                  result.get("judgment"), result.get("reason"), result.get("suggestion"),
                                                  result.get("evidence"))
                done += 1
                progress(done, len(targets))
            return {"processed": done}

        def on_progress(cur, total):
            dlg.setLabelText(f"质检处理中：{cur}/{total}")
            dlg.setValue(cur)

        def on_done(res):
            dlg.close()
            if res.get("error"):
                QMessageBox.warning(self, "智能质检失败", res["error"]); return
            QMessageBox.information(self, "质检完成", f"已处理 {res.get('processed', 0)} 条，结果已写回数据库（相同内容自动命中缓存）。")
            self._refresh_all()

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
                   "计算分", "最终状态", "复核状态", "复核说明", "扣分明细", "跟进建议"])
        for r in self.filtered:
            dims = r["deductions"] or {}
            dim_txt = "；".join(f"{DIM_CN.get(k, k)}扣{v}分" for k, v in dims.items() if v)
            ws.append([r["first_message_at"], r["store_id"], r["agent"], r["customer"],
                       "、".join(r["product_ids"]), r["excel_labels"].get("product_name"),
                       STAGE_CN.get(r["service_stage"], "-"), VALID_CN.get(r["validity"], "-"), r["lead_level"],
                       "是" if r["tele_sales_lead"] else "否", r["calculated_score"],
                       FINAL_CN.get(r["final_status"], r["final_status"] or "-"),
                       REVIEW_CN.get(r["review_status"], "-"), r["review_note"], dim_txt, r["follow_up_advice"]])
        wb.save(path)
        QMessageBox.information(self, "导出完成", f"已导出 {len(self.filtered)} 条到 {path}")

    def _switch_page(self, row):
        self.stack.setCurrentIndex(row)


def main() -> int:
    app = QApplication(sys.argv)
    # Qt 内置按钮/对话框汉化（是/否、确定/取消等），保证全中文
    translator = QTranslator(app)
    if translator.load("qtbase_zh_CN", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    # 启动即套用浅色，避免窗口出现前闪一下黑底
    app.setStyleSheet(LIGHT_QSS)
    win = MainWindow()
    win.show()
    win.showNormal()
    win.raise_()
    win.activateWindow()
    print("[启动] 窗口已显示", flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
