"""设置窗口：模型 / 语音 / 自检三个页签。

写回 config.env，所以手改和界面改两条路都通；能立即生效的设置会同步到内存。
"""

import os
from pathlib import Path

import requests
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import core.llm_api as llm_api
import core.tts as tts
import voice_input as voice
from config_store import read_config, update_config
from core.memory import MemoryStore, WorkingMemory

_FONT = "Microsoft YaHei UI"

FIELD_QSS = (
    "QLineEdit{background:#F7F4FB;border:1px solid #E2DAF0;border-radius:10px;"
    "padding:7px 12px;color:#3D3554;font-size:11px;}"
    "QLineEdit:focus{border:1px solid #B7A4DC;background:#FFFFFF;}"
)
SPIN_QSS = (
    "QSpinBox,QDoubleSpinBox{background:#F7F4FB;border:1px solid #E2DAF0;"
    "border-radius:10px;padding:6px 10px;color:#3D3554;font-size:11px;}"
    "QSpinBox:focus,QDoubleSpinBox:focus{border:1px solid #B7A4DC;background:#FFFFFF;}"
)
COMBO_QSS = (
    "QComboBox{background:#F7F4FB;border:1px solid #E2DAF0;border-radius:10px;"
    "padding:6px 12px;color:#3D3554;font-size:11px;}"
    "QComboBox::drop-down{border:none;width:18px;}"
    "QComboBox QAbstractItemView{background:#FFFFFF;border:1px solid #E2DAF0;"
    "selection-background-color:#EDE6F8;selection-color:#3D3554;outline:none;}"
)
TAB_QSS = (
    "QTabWidget::pane{border:none;}"
    "QTabBar::tab{background:transparent;color:#9A93AE;padding:6px 16px;"
    "font-size:11px;border-bottom:2px solid transparent;}"
    "QTabBar::tab:selected{color:#5B4B8A;border-bottom:2px solid #8B7AB8;}"
    "QTabBar::tab:hover{color:#6A579C;}"
)
LEVEL_COLORS = {"ok": "#3F7D5A", "warn": "#B07C2A", "error": "#B4544A"}


def _label(text: str, size: int = 8, color: str = "#8C81A6") -> QLabel:
    label = QLabel(text)
    label.setFont(QFont(_FONT, size))
    label.setStyleSheet(f"color:{color};background:transparent;")
    return label


class _TestWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, url, key, model, thinking, parent=None):
        super().__init__(parent)
        self.url, self.key, self.model, self.thinking = url, key, model, thinking

    def run(self):
        try:
            body = {
                "model": self.model,
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 32,
                "temperature": 0.7,
            }
            if self.thinking == "off":
                body["thinking"] = {"type": "disabled"}
            resp = requests.post(
                self.url,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.key}"},
                json=body,
                timeout=25,
            )
            if resp.status_code != 200:
                self.done.emit(False, f"HTTP {resp.status_code}：{resp.text[:160]}")
                return
            data = resp.json()
            content = (data["choices"][0]["message"].get("content") or "").strip()
            self.done.emit(True, f"连接成功：{content[:40] or '（模型返回空内容）'}")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, f"连接失败：{exc}")


class _CheckWorker(QThread):
    done = pyqtSignal(list)

    def run(self):
        try:
            from diagnostics import check_environment

            self.done.emit(check_environment())
        except Exception as exc:  # noqa: BLE001
            self.done.emit([{"level": "error", "title": "自检本身出错了", "detail": str(exc)}])


class CheckPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:transparent;")
        self._worker = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(_label("逐项检查配置和服务状态", 8))
        head.addStretch()
        self.refresh_btn = QPushButton("重新检测")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setStyleSheet(
            "QPushButton{background:#F1ECF8;border:1px solid #E2DAF0;border-radius:9px;"
            "padding:5px 12px;color:#6A579C;font-size:11px;}"
            "QPushButton:hover{background:#E9E1F5;}"
            "QPushButton:disabled{color:#B7AECB;}"
        )
        self.refresh_btn.clicked.connect(self.refresh)
        head.addWidget(self.refresh_btn)
        lay.addLayout(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:6px;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(150,135,185,0.45);"
            "border-radius:3px;min-height:24px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        self.rows = QVBoxLayout(holder)
        self.rows.setContentsMargins(2, 2, 6, 2)
        self.rows.setSpacing(7)
        self.rows.addStretch(1)
        self.scroll.setWidget(holder)
        lay.addWidget(self.scroll, 1)

        self.refresh()

    def refresh(self):
        self.refresh_btn.setEnabled(False)
        self._clear()
        self.rows.insertWidget(self.rows.count() - 1, _label("检测中…", 9))
        self._worker = _CheckWorker(self)
        self._worker.done.connect(self._apply)
        self._worker.start()

    def _clear(self):
        while self.rows.count() > 1:
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater 要等事件循环，先把旧的藏起来，免得和新内容叠在一起
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _apply(self, items):
        self.refresh_btn.setEnabled(True)
        self._clear()
        for item in items:
            self.rows.insertWidget(self.rows.count() - 1, self._row(item))
        # 新内容从顶部开始看，别停在上一轮的位置
        self.scroll.verticalScrollBar().setValue(0)

    def _row(self, item):
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)

        dot = QLabel("●")
        dot.setFont(QFont(_FONT, 9))
        dot.setStyleSheet(
            f"color:{LEVEL_COLORS.get(item.get('level'), '#8C81A6')};background:transparent;")
        dot.setFixedWidth(12)
        line.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(0)
        title = _label(item.get("title", ""), 9, "#4A3F6B")
        title.setWordWrap(True)
        col.addWidget(title)
        detail = item.get("detail") or ""
        if detail:
            sub = _label(detail, 8, "#9A93AE")
            sub.setWordWrap(True)
            col.addWidget(sub)
        line.addLayout(col, 1)
        return row


class MemoryPage(QWidget):
    short_term_cleared = pyqtSignal()

    def __init__(self, memory_store: MemoryStore, working_memory: WorkingMemory, parent=None):
        super().__init__(parent)
        self.memory_store = memory_store
        self.working_memory = working_memory
        self.setStyleSheet("background:transparent;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(5)

        intro = _label(
            "核心人格独立于记忆；只保存你明确添加的内容。命令：/记住情感 内容、"
            "/记住事实 内容、/遗忘 关键词。",
            8,
        )
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.memory_list = QListWidget()
        self.memory_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.memory_list.setMinimumHeight(90)
        self.memory_list.setMaximumHeight(152)
        self.memory_list.setStyleSheet(
            "QListWidget{background:#FAF8FC;border:1px solid #E2DAF0;border-radius:8px;"
            "color:#4A3F6B;font-size:10px;padding:3px;}"
            "QListWidget::item{padding:5px;border-bottom:1px solid #EEE9F4;}"
            "QListWidget::item:selected{background:#EDE6F8;color:#3D3554;}"
        )
        lay.addWidget(self.memory_list, 1)

        self.memory_status = _label("", 8)
        self.memory_status.setWordWrap(True)
        lay.addWidget(self.memory_status)

        memory_row = QHBoxLayout()
        self.memory_kind = QComboBox()
        self.memory_kind.addItem("情感", "emotion")
        self.memory_kind.addItem("事实", "fact")
        self.memory_kind.setStyleSheet(COMBO_QSS)
        self.memory_kind.setFixedWidth(76)
        memory_row.addWidget(self.memory_kind)

        self.memory_edit = QLineEdit()
        self.memory_edit.setMaxLength(500)
        self.memory_edit.setPlaceholderText("明确添加一条长期记忆")
        self.memory_edit.setStyleSheet(FIELD_QSS)
        self.memory_edit.returnPressed.connect(self._add_memory)
        memory_row.addWidget(self.memory_edit, 1)

        self.importance_spin = QSpinBox()
        self.importance_spin.setRange(1, 5)
        self.importance_spin.setValue(3)
        self.importance_spin.setSuffix(" / 5")
        self.importance_spin.setFixedWidth(70)
        self.importance_spin.setToolTip("这条记忆的主观重要程度")
        self.importance_spin.setStyleSheet(SPIN_QSS)
        memory_row.addWidget(self.importance_spin)

        self.add_memory_btn = QPushButton("记下")
        self.add_memory_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_memory_btn.setStyleSheet(
            "QPushButton{background:#F1ECF8;border:1px solid #E2DAF0;border-radius:8px;"
            "padding:6px 10px;color:#6A579C;font-size:10px;}"
            "QPushButton:hover{background:#E9E1F5;}"
        )
        self.add_memory_btn.clicked.connect(self._add_memory)
        memory_row.addWidget(self.add_memory_btn)
        lay.addLayout(memory_row)

        action_row = QHBoxLayout()
        self.forget_btn = QPushButton("遗忘选中")
        self.forget_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forget_btn.setStyleSheet(
            "QPushButton{background:transparent;border:1px solid #E2DAF0;border-radius:8px;"
            "padding:5px 10px;color:#8B514F;font-size:10px;}"
            "QPushButton:hover{background:#F8EEEE;}"
        )
        self.forget_btn.clicked.connect(self._forget_selected)
        self.forget_btn.setEnabled(False)
        self.memory_list.itemSelectionChanged.connect(
            lambda: self.forget_btn.setEnabled(bool(self.memory_list.selectedItems()))
        )
        action_row.addWidget(self.forget_btn)
        action_row.addStretch()
        lay.addLayout(action_row)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color:#E8E1F0;background:transparent;")
        lay.addWidget(divider)

        short_label = _label("短期记忆", 9, "#4A3F6B")
        lay.addWidget(short_label)
        short_hint = _label(
            "最近对话只保留在本次运行。命令：/污染 内容、/清空短期。",
            8,
        )
        short_hint.setWordWrap(True)
        lay.addWidget(short_hint)

        injection_row = QHBoxLayout()
        self.impression_edit = QLineEdit()
        self.impression_edit.setMaxLength(500)
        self.impression_edit.setPlaceholderText("注入一条可能有误的临时印象")
        self.impression_edit.setStyleSheet(FIELD_QSS)
        self.impression_edit.returnPressed.connect(self._inject_impression)
        injection_row.addWidget(self.impression_edit, 1)

        self.turns_spin = QSpinBox()
        self.turns_spin.setRange(1, 12)
        self.turns_spin.setValue(4)
        self.turns_spin.setSuffix(" 轮")
        self.turns_spin.setToolTip("这条临时印象还会参与多少次成功回复")
        self.turns_spin.setStyleSheet(SPIN_QSS)
        injection_row.addWidget(self.turns_spin)

        self.inject_btn = QPushButton("注入")
        self.inject_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.inject_btn.setStyleSheet(
            "QPushButton{background:#E9F2EF;border:1px solid #D3E4DD;border-radius:8px;"
            "padding:6px 10px;color:#3F755F;font-size:10px;}"
            "QPushButton:hover{background:#DDECE6;}"
        )
        self.inject_btn.clicked.connect(self._inject_impression)
        injection_row.addWidget(self.inject_btn)
        lay.addLayout(injection_row)

        self.short_term_status = _label("", 8)
        self.short_term_status.setWordWrap(True)
        lay.addWidget(self.short_term_status)

        self.clear_short_btn = QPushButton("清空短期记忆")
        self.clear_short_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_short_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:8px;"
            "padding:4px 8px;color:#8C81A6;font-size:10px;}"
            "QPushButton:hover{background:rgba(140,125,180,0.12);}"
        )
        self.clear_short_btn.clicked.connect(self._clear_short_term)
        lay.addWidget(self.clear_short_btn, 0, Qt.AlignmentFlag.AlignLeft)

        self.refresh()

    def refresh(self):
        self.memory_list.clear()
        entries = sorted(
            self.memory_store.list_memories(),
            key=lambda item: item.get("updated_at", ""),
            reverse=True,
        )
        entries.sort(key=lambda item: item["kind"] != "emotion")
        for entry in entries:
            kind = "情感" if entry["kind"] == "emotion" else "事实"
            item = QListWidgetItem(
                f"{kind} · {entry.get('importance', 3)}/5　{entry['text']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, entry.get("id"))
            self.memory_list.addItem(item)

        if self.memory_store.load_error:
            self.memory_status.setStyleSheet("color:#B4544A;background:transparent;")
            self.memory_status.setText(
                f"记忆文件无法读取，已保护原文件：{self.memory_store.load_error}"
            )
            self.add_memory_btn.setEnabled(False)
            self.forget_btn.setEnabled(False)
        else:
            self.memory_status.setStyleSheet("color:#8C81A6;background:transparent;")
            self.memory_status.setText(
                f"{len(entries)} 条长期记忆 · 情感召回约 72%，事实约 28%"
            )
            self.add_memory_btn.setEnabled(True)
        self._refresh_short_term()

    def _refresh_short_term(self):
        entries = self.working_memory.list_impressions()
        if entries:
            display = "；".join(
                f"{entry['text']}（{entry['turns_left']} 轮）" for entry in entries
            )
            self.short_term_status.setText(f"当前临时印象：{display}")
        else:
            self.short_term_status.setText("当前没有临时印象")

    def _add_memory(self):
        try:
            self.memory_store.add(
                self.memory_edit.text(),
                self.memory_kind.currentData(),
                self.importance_spin.value(),
            )
        except Exception as exc:  # noqa: BLE001
            self.memory_status.setStyleSheet("color:#B4544A;background:transparent;")
            self.memory_status.setText(f"无法保存记忆：{exc}")
            return
        self.memory_edit.clear()
        self.refresh()

    def _forget_selected(self):
        ids = [item.data(Qt.ItemDataRole.UserRole) for item in self.memory_list.selectedItems()]
        try:
            self.memory_store.forget_many(ids)
        except Exception as exc:  # noqa: BLE001
            self.memory_status.setStyleSheet("color:#B4544A;background:transparent;")
            self.memory_status.setText(f"无法遗忘记忆：{exc}")
            return
        self.refresh()

    def _inject_impression(self):
        try:
            self.working_memory.inject(self.impression_edit.text(), self.turns_spin.value())
        except ValueError as exc:
            self.short_term_status.setText(str(exc))
            return
        self.impression_edit.clear()
        self._refresh_short_term()

    def _clear_short_term(self):
        self.working_memory.clear()
        self.short_term_cleared.emit()
        self._refresh_short_term()


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        tab: int = 0,
        memory_store: MemoryStore | None = None,
        working_memory: WorkingMemory | None = None,
    ):
        super().__init__(parent)
        self._worker = None
        self._drag_from = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(492, 590)

        cfg = read_config()

        def cfg_value(key):
            return cfg.get(key) or os.environ.get(key) or ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "QFrame#card{background:rgba(253,251,255,0.99);"
            "border:1px solid rgba(186,174,212,0.6);border-radius:16px;}"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(70, 50, 110, 90))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 16)
        lay.setSpacing(8)

        # ---- 标题 ----
        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title = QLabel("设置")
        title.setFont(QFont(_FONT, 12, QFont.Weight.DemiBold))
        title.setStyleSheet("color:#4A3F6B;background:transparent;")
        title_col.addWidget(title)
        title_col.addWidget(_label("模型 · 语音 · 自检 · 记忆", 8, "#AA9FC4"))
        head.addLayout(title_col)
        head.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:13px;"
            "color:#8C81A6;font-size:13px;}"
            "QPushButton:hover{background:rgba(140,125,180,0.15);color:#5B4B8A;}"
        )
        close_btn.clicked.connect(self.reject)
        head.addWidget(close_btn)
        lay.addLayout(head)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(TAB_QSS)
        self.tabs.addTab(self._build_model_tab(), "模型")
        self.tabs.addTab(self._build_voice_tab(cfg, cfg_value), "语音")
        self.check_page = CheckPage()
        self.tabs.addTab(self.check_page, "自检")
        self.memory_page = MemoryPage(
            memory_store or MemoryStore(Path(__file__).resolve().parent / "data" / "long_term_memory.json"),
            working_memory or WorkingMemory(),
            self,
        )
        self.tabs.addTab(self.memory_page, "记忆")
        self.tabs.setCurrentIndex(max(0, min(3, tab)))
        lay.addWidget(self.tabs, 1)

        # ---- 状态 ----
        self.status = _label("", 9)
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        # ---- 按钮 ----
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.setStyleSheet(
            "QPushButton{background:#F1ECF8;border:1px solid #E2DAF0;border-radius:10px;"
            "padding:7px 16px;color:#6A579C;font-size:11px;}"
            "QPushButton:hover{background:#E9E1F5;}"
            "QPushButton:disabled{color:#B7AECB;}"
        )
        self.test_btn.clicked.connect(self._test)
        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:10px;"
            "padding:7px 14px;color:#8C81A6;font-size:11px;}"
            "QPushButton:hover{background:rgba(140,125,180,0.12);}"
        )
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("保存")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #8B7AB8,stop:1 #7461A6);border:none;border-radius:10px;"
            "padding:7px 22px;color:#FFFFFF;font-size:11px;}"
            "QPushButton:hover{background:#6A579C;}"
        )
        save_btn.clicked.connect(self._save)
        buttons.addWidget(self.test_btn)
        buttons.addStretch()
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)
        lay.addLayout(buttons)

    # ---------------- 页签 ----------------

    def _build_model_tab(self):
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(6)

        def make_edit(value, placeholder="", password=False):
            edit = QLineEdit(value)
            edit.setStyleSheet(FIELD_QSS)
            edit.setPlaceholderText(placeholder)
            if password:
                edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setCursorPosition(0)  # 长路径默认显示开头（盘符），而不是结尾
            return edit

        lay.addWidget(_label("API Key"))
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.key_edit = make_edit(llm_api.API_KEY or "", "ark-xxxxxxxx", password=True)
        key_row.addWidget(self.key_edit, 1)
        self.show_key = QCheckBox("显示")
        self.show_key.setStyleSheet("QCheckBox{color:#8C81A6;font-size:11px;background:transparent;}")
        self.show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row.addWidget(self.show_key)
        lay.addLayout(key_row)

        lay.addWidget(_label("接口地址"))
        self.url_edit = make_edit(
            llm_api.API_URL or "",
            "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        lay.addWidget(self.url_edit)

        lay.addWidget(_label("模型 ID"))
        self.model_edit = make_edit(
            llm_api.MODEL_NAME or "", "例如 deepseek-v4-1-flash-economy-261017")
        lay.addWidget(self.model_edit)

        two_col = QHBoxLayout()
        two_col.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(_label("温度（越高越活泼）"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(1)
        self.temp_spin.setValue(float(llm_api.TEMPERATURE))
        self.temp_spin.setStyleSheet(SPIN_QSS)
        left.addWidget(self.temp_spin)
        two_col.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(4)
        right.addWidget(_label("回复长度上限（token）"))
        self.tokens_spin = QSpinBox()
        self.tokens_spin.setRange(50, 8000)
        self.tokens_spin.setSingleStep(50)
        self.tokens_spin.setValue(int(llm_api.MAX_TOKENS))
        self.tokens_spin.setStyleSheet(SPIN_QSS)
        right.addWidget(self.tokens_spin)
        two_col.addLayout(right, 1)
        lay.addLayout(two_col)

        lay.addWidget(_label("思考过程（会占用回复长度）"))
        self.thinking_combo = QComboBox()
        self.thinking_combo.addItem("关闭（推荐：回答更长更快）", "off")
        self.thinking_combo.addItem("打开", "on")
        self.thinking_combo.addItem("不干预", "auto")
        current = (llm_api.LLM_THINKING or "off").lower()
        self.thinking_combo.setCurrentIndex(
            {"off": 0, "disabled": 0, "on": 1, "enabled": 1}.get(current, 2))
        self.thinking_combo.setStyleSheet(COMBO_QSS)
        lay.addWidget(self.thinking_combo)

        lay.addStretch()
        lay.addWidget(_label("保存后立即生效，无需重启。", 8, "#B0A8C4"))
        return page

    def _build_voice_tab(self, cfg, cfg_value):
        from pathlib import Path

        from config_store import app_dir

        default_tts_dir = str(
            app_dir().parent.parent / "GPT-SoVITS-v5-20261005" / "GPT-SoVITS-v2pro-20261006")
        default_asr_base = str(Path(default_tts_dir) / "tools" / "asr" / "models")

        page = QWidget()
        page.setStyleSheet("background:transparent;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:6px;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(150,135,185,0.45);"
            "border-radius:3px;min-height:24px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        form = QVBoxLayout(holder)
        form.setContentsMargins(0, 8, 6, 0)
        form.setSpacing(6)

        def add_line(label_text, attr, key, placeholder="", default=""):
            form.addWidget(_label(label_text))
            edit = QLineEdit(cfg_value(key) or default)
            edit.setStyleSheet(FIELD_QSS)
            edit.setPlaceholderText(placeholder)
            edit.setCursorPosition(0)
            setattr(self, attr, edit)
            form.addWidget(edit)
            return edit

        add_line("语音合成服务地址", "tts_url_edit", "TTS_API_URL",
                 "http://127.0.0.1:9880", "http://127.0.0.1:9880")
        add_line("语音识别服务地址", "asr_url_edit", "ASR_API_URL",
                 "http://127.0.0.1:9881", "http://127.0.0.1:9881")
        add_line("参考音频路径（3~10 秒人声）", "ref_edit", "TTS_REF_AUDIO_PATH",
                 "D:/voices/violet.wav")
        add_line("GPT-SoVITS 目录", "tts_dir_edit", "GPT_SOVITS_DIR",
                 "内含 runtime\\python.exe 的目录", default_tts_dir)
        add_line("FunASR 识别模型目录", "asr_base_edit", "ASR_MODEL_BASE",
                 "内含 speech_paraformer-large... 的 models 目录", default_asr_base)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(10)
        speed_col = QVBoxLayout()
        speed_col.setSpacing(4)
        speed_col.addWidget(_label("语速（1.0 原速）"))
        self.speed_spin = QDoubleSpinBox()
        self.speed_spin.setRange(0.5, 2.0)
        self.speed_spin.setSingleStep(0.05)
        self.speed_spin.setDecimals(2)
        self.speed_spin.setValue(float(cfg_value("TTS_SPEED_FACTOR") or 1.15))
        self.speed_spin.setStyleSheet(SPIN_QSS)
        speed_col.addWidget(self.speed_spin)
        speed_row.addLayout(speed_col, 1)

        vol_col = QVBoxLayout()
        vol_col.setSpacing(4)
        vol_col.addWidget(_label("目标响度（LUFS）"))
        self.lufs_spin = QDoubleSpinBox()
        self.lufs_spin.setRange(-30.0, -10.0)
        self.lufs_spin.setSingleStep(0.5)
        self.lufs_spin.setDecimals(1)
        self.lufs_spin.setValue(float(cfg_value("TTS_TARGET_LUFS") or -20))
        self.lufs_spin.setStyleSheet(SPIN_QSS)
        vol_col.addWidget(self.lufs_spin)
        speed_row.addLayout(vol_col, 1)
        form.addLayout(speed_row)

        form.addStretch()
        hint = _label("服务地址、语速、响度保存后立即生效；目录类改动需要重启 Violet。",
                      8, "#B0A8C4")
        hint.setWordWrap(True)
        form.addWidget(hint)

        scroll.setWidget(holder)
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        return page

    # ---------------- 交互 ----------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 70:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_from is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_from = None
        super().mouseReleaseEvent(event)

    def _model_values(self):
        return {
            "ARK_API_KEY": self.key_edit.text().strip(),
            "API_URL": self.url_edit.text().strip(),
            "LLM_MODEL_NAME": self.model_edit.text().strip(),
            "TEMPERATURE": f"{self.temp_spin.value():.1f}",
            "MAX_TOKENS": str(self.tokens_spin.value()),
            "LLM_THINKING": self.thinking_combo.currentData(),
        }

    def _voice_values(self):
        return {
            "TTS_API_URL": self.tts_url_edit.text().strip() or "http://127.0.0.1:9880",
            "ASR_API_URL": self.asr_url_edit.text().strip() or "http://127.0.0.1:9881",
            "TTS_REF_AUDIO_PATH": self.ref_edit.text().strip(),
            "GPT_SOVITS_DIR": self.tts_dir_edit.text().strip(),
            "ASR_MODEL_BASE": self.asr_base_edit.text().strip(),
            "TTS_SPEED_FACTOR": f"{self.speed_spin.value():.2f}",
            "TTS_TARGET_LUFS": f"{self.lufs_spin.value():.1f}",
        }

    def _set_status(self, ok, message):
        color = "#8C81A6" if ok is None else ("#3F7D5A" if ok else "#B4544A")
        self.status.setStyleSheet(f"color:{color};background:transparent;")
        self.status.setText(message)

    def _test(self):
        values = self._model_values()
        if not values["ARK_API_KEY"] or not values["API_URL"] or not values["LLM_MODEL_NAME"]:
            self._set_status(False, "API Key / 地址 / 模型 ID 都不能为空")
            return
        self.test_btn.setEnabled(False)
        self._set_status(None, "正在连接…")
        self._worker = _TestWorker(values["API_URL"], values["ARK_API_KEY"],
                                   values["LLM_MODEL_NAME"], values["LLM_THINKING"], self)
        self._worker.done.connect(self._on_test_done)
        self._worker.start()

    def _on_test_done(self, ok, message):
        self.test_btn.setEnabled(True)
        self._set_status(ok, message)

    def _save(self):
        model_values = self._model_values()
        if not model_values["ARK_API_KEY"] or not model_values["API_URL"] or not model_values["LLM_MODEL_NAME"]:
            self.tabs.setCurrentIndex(0)
            self._set_status(False, "API Key / 地址 / 模型 ID 都不能为空")
            return

        voice_values = self._voice_values()
        values = {**model_values, **voice_values}
        try:
            update_config(values)
        except Exception as exc:  # noqa: BLE001
            self._set_status(False, f"写入 config.env 失败：{exc}")
            return

        for key, value in values.items():
            os.environ[key] = value

        # 大模型：立即生效
        llm_api.API_KEY = model_values["ARK_API_KEY"]
        llm_api.API_URL = model_values["API_URL"]
        llm_api.MODEL_NAME = model_values["LLM_MODEL_NAME"]
        llm_api.TEMPERATURE = float(model_values["TEMPERATURE"])
        llm_api.MAX_TOKENS = int(model_values["MAX_TOKENS"])
        llm_api.LLM_THINKING = model_values["LLM_THINKING"]

        # 语音：地址/参考音频/语速/响度也都能当场生效
        tts.TTS_API_URL = voice_values["TTS_API_URL"].rstrip("/")
        tts.REF_AUDIO = voice_values["TTS_REF_AUDIO_PATH"]
        tts.TTS_SPEED_FACTOR = max(0.5, min(2.0, float(voice_values["TTS_SPEED_FACTOR"])))
        tts.TTS_TARGET_LUFS = float(voice_values["TTS_TARGET_LUFS"])
        voice.ASR_API_URL = voice_values["ASR_API_URL"].rstrip("/")

        self.accept()
