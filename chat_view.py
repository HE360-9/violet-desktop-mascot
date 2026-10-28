"""聊天窗口里的消息视图：气泡列表 + 打字机流式消息。

从 main.py 里拆出来单独维护，方便调样式而不碰业务逻辑。
用法：
    view.add_user("你好")
    view.add_assistant("……")
    view.add_system("正在识别语音…")
    view.stream_start(); view.stream_set("薇"); ...; view.stream_end()
"""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

USER_BG = "qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #8B7AB8,stop:1 #7461A6)"
ASSISTANT_BG = "#FFFFFF"
TEXT_DARK = "#3D3554"
TEXT_LIGHT = "#9A93AE"

_FONT = "Microsoft YaHei UI"


class Bubble(QFrame):
    """一个消息气泡；role 取 user / assistant"""

    MAX_TEXT_WIDTH = 268

    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role
        self.setObjectName("bubble")
        self.setMaximumWidth(self.MAX_TEXT_WIDTH + 30)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)

        box = QVBoxLayout(self)
        box.setContentsMargins(13, 9, 13, 10)
        box.setSpacing(2)

        if role == "assistant":
            name = QLabel("薇尔莉特")
            name.setFont(QFont(_FONT, 8))
            name.setStyleSheet(f"color:{TEXT_LIGHT}; background:transparent;")
            box.addWidget(name)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setFont(QFont(_FONT, 10))
        self.label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        box.addWidget(self.label)
        self._fit_width()

        if role == "user":
            self.setStyleSheet(
                f"QFrame#bubble{{background:{USER_BG};border:none;border-radius:13px;}}"
                f"QLabel{{color:#FFFFFF;background:transparent;}}"
            )
        else:
            self.setStyleSheet(
                f"QFrame#bubble{{background:{ASSISTANT_BG};border:1px solid #ECE6F4;"
                f"border-radius:13px;}}"
                f"QLabel{{color:{TEXT_DARK};background:transparent;}}"
            )

    def _fit_width(self):
        """QLabel 开了自动换行后宽度会塌成最小，这里按文本长度定一个合适的宽度"""
        text = self.label.text()
        if not text:
            width = 36
        else:
            width = min(self.MAX_TEXT_WIDTH, self.label.fontMetrics().horizontalAdvance(text) + 4)
        self.label.setFixedWidth(max(36, width))

    def set_text(self, text: str):
        self.label.setText(text)
        self._fit_width()


class ChatView(QScrollArea):
    """可滚动的消息列表，新消息自动贴底"""

    MAX_BUBBLES = 200

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stream_bubble = None
        self._rows = []

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:6px;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(150,135,185,0.45);border-radius:3px;"
            "min-height:24px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(150,135,185,0.75);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        )

        self._holder = QWidget()
        self._holder.setStyleSheet("background:transparent;")
        self._lay = QVBoxLayout(self._holder)
        self._lay.setContentsMargins(4, 4, 4, 4)
        self._lay.setSpacing(9)
        self._lay.addStretch(1)
        self.setWidget(self._holder)

    # ---------- 内部 ----------

    def _insert_widget(self, widget: QWidget, align_right: bool, expand: bool = False):
        row = QWidget()
        row.setStyleSheet("background:transparent;")
        line = QHBoxLayout(row)
        line.setContentsMargins(2, 0, 2, 0)
        if expand:
            line.addWidget(widget, 1)
        elif align_right:
            line.addStretch(1)
            line.addWidget(widget)
        else:
            line.addWidget(widget)
            line.addStretch(1)
        self._lay.insertWidget(self._lay.count() - 1, row)
        self._rows.append(row)
        self._trim()
        self._scroll_to_bottom()

    def _trim(self):
        while len(self._rows) > self.MAX_BUBBLES:
            row = self._rows.pop(0)
            self._lay.removeWidget(row)
            row.deleteLater()

    def _scroll_to_bottom(self):
        QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(
            self.verticalScrollBar().maximum()
        ))

    # ---------- 对外 ----------

    def add_user(self, text: str):
        self._insert_widget(Bubble(text, "user"), align_right=True)

    def add_assistant(self, text: str):
        self._insert_widget(Bubble(text, "assistant"), align_right=False)

    def add_system(self, text: str):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(QFont(_FONT, 9))
        label.setStyleSheet(f"color:{TEXT_LIGHT};background:transparent;")
        self._insert_widget(label, align_right=False, expand=True)

    def stream_start(self):
        """开始一条流式回复气泡（打字机用）"""
        self._stream_bubble = Bubble("…", "assistant")
        self._insert_widget(self._stream_bubble, align_right=False)

    def stream_set(self, text: str):
        if self._stream_bubble is None:
            self.stream_start()
        self._stream_bubble.set_text(text if text else "…")
        self._scroll_to_bottom()

    def stream_end(self):
        if self._stream_bubble is not None and self._stream_bubble.label.text() == "…":
            self._stream_bubble.set_text("……")
        self._stream_bubble = None
