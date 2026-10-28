import os
import sys
import subprocess
import threading
from pathlib import Path
from dotenv import load_dotenv

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root))
load_dotenv(root / "config.env")

# pythonw 没有控制台：Python 异常和原生崩溃都会被直接吞掉，进程“人间蒸发”。
# 这里把未捕获异常、线程异常、faulthandler 的原生崩溃栈统一写到 logs/crash.log，
# 下次再莫名退出时至少有据可查
import datetime
import faulthandler
import traceback

_log_dir = root / "logs"
_log_dir.mkdir(exist_ok=True)
_crash_fp = open(_log_dir / "crash.log", "a", encoding="utf-8", buffering=1)
faulthandler.enable(file=_crash_fp)


def _log_uncaught(exc_type, exc, tb):
    _crash_fp.write(f"\n[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] uncaught exception\n")
    traceback.print_exception(exc_type, exc, tb, file=_crash_fp)
    _crash_fp.flush()


sys.excepthook = _log_uncaught


def _log_thread_uncaught(args):
    _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)


threading.excepthook = _log_thread_uncaught

from core.llm_api import llm
import core.llm_api as llm_mod
from core.memory import MemoryStore, WorkingMemory
from core.tts import speak, check_api, translate_for_tts,clear_history_audio
import core.tts as tts_mod
from voice_input import cancel_listening, voice_input_async, start_listening
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QLabel, QPushButton, QMenu, QFrame,
    QGraphicsDropShadowEffect, QSystemTrayIcon
)
from PyQt6.QtCore import Qt, QTimer, QThread, QSignalBlocker, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont, QAction, QColor, QIcon
from chat_view import ChatView
from settings_dialog import SettingsDialog
from typing_sound import TypingSound
from crawler import weather
from camera_module import CameraWorker
from process_utils import stop_process_tree


_tts_proc = None
bat_path = os.getenv("TTS_BAT_PATH","").strip()
if os.path.exists(bat_path):
    _tts_proc = subprocess.Popen(bat_path, shell=True, cwd=root)
ENABLE_TTS = os.getenv("ENABLE_TTS", "false").lower() == "true"
with open(root / "prompt.txt", "r", encoding="utf-8") as f:
    system_prompt = f.read()

def get_full_prompt():
    global system_prompt, is_sick
    if is_sick:
        sick_tip = """
额外设定：当前薇尔莉特得了普通感冒，身体虚弱、容易乏力、声音略带沙哑，说话轻柔无力，
偶尔会轻微咳嗽、怕冷，情绪偏安静慵懒，回答时贴合感冒生病的状态，不要过于活泼。
"""
        return system_prompt + "\n" + sick_tip
    else:
        return system_prompt

is_sick = False
home = "襄阳"
_IMG_DIR = root / "static" / "prep_png"
RAIN_TAGS = ("🌦️", "🌧️", "⛈️")
NORMAL_IDLE_IMAGES = ("BgSub_站姿2.png", "BgSub_站姿3.png")
SICK_IDLE_IMAGES = ("BgSub_sick_idle.png",)
NORMAL_IMG = (NORMAL_IDLE_IMAGES[0], "BgSub_speak.png", "BgSub_sleep.png", "BgSub_think.png")
SICK_IMG = ("BgSub_sick_idle.png", "BgSub_sick_speak.png", "BgSub_sick_sleep.png", "BgSub_sick_think.png")
SICK_TEXT = """薇尔莉特得了普通感冒，身体虚弱、容易乏力、声音略带沙哑，说话轻柔无力，
                偶尔会轻微咳嗽、怕冷，情绪偏安静慵懒"""


def _img_paths(names):
    return tuple(str(_IMG_DIR / n) for n in names)


IMG_IDLE, IMG_TALK, IMG_SLEEP, IMG_THINK = _img_paths(NORMAL_IMG)
history = []
memory_store = MemoryStore(root / "data" / "long_term_memory.json")
working_memory = WorkingMemory()
tts_lang = "zh"
paused = False
clear_history_audio()

class AIWorker(QThread):
    reply_ready = pyqtSignal(str)
    error_ready = pyqtSignal(str)
    def __init__(self, user_text, memory_context=""):
        super().__init__()
        self.user_text = user_text
        self.memory_context = memory_context
        
    def run(self):
        global history
        full_sys_prompt = get_full_prompt()
        answer, new_history = llm(
            self.user_text,
            full_sys_prompt,
            history,
            memory_context=self.memory_context,
        )
        if answer.startswith("API调用失败"):
            self.error_ready.emit(answer)
            return
        history = new_history
        self.reply_ready.emit(answer)
class DesktopMascot(QMainWindow):
    weather_changed = pyqtSignal(str, str)   # (天气文本, 错误信息)
    def __init__(self):
        super().__init__()
        self._drag_offset = None
        self.chat_win = None
        self.is_sleep = False
        self._pix_cache = {}
        self._weather_pending = False
        self.resize(294, 434)
        self.move(600, 125)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.idle_pose_index = 0
        self.idle_pose_images = [self._pixmap_for(path) for path in _img_paths(NORMAL_IDLE_IMAGES)]
        self.pix_idle = self.idle_pose_images[0]
        self._talk_timer = None
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._show_pixmap(self.pix_idle)
        self.setCentralWidget(self.img_label)
        self.pix_talk = self._pixmap_for(IMG_TALK, self.pix_idle)
        self.pix_exit = self._pixmap_for(IMG_SLEEP, self.pix_idle)
        self.pix_think = self._pixmap_for(IMG_THINK, self.pix_idle)
        self.weather_changed.connect(self._apply_weather)
        self.weather_timer = QTimer(self)
        self.weather_timer.setInterval(1800 * 1000)
        self.weather_timer.timeout.connect(self.check_weather)
        self.weather_timer.start()
        # 首次天气检查等窗口显示后再跑，避免启动瞬间卡住
        QTimer.singleShot(1500, self.check_weather)
    @staticmethod
    def _load_pixmap(path, fallback=None):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            if fallback is not None and not fallback.isNull():
                return fallback
            return QPixmap()
        return pixmap.scaled(
            420, 620, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    def _show_pixmap(self, pixmap):
        if pixmap.isNull():
            self.img_label.setPixmap(QPixmap())
            self.img_label.setText("立绘缺失\n请将 PNG 图片放入\nstatic/prep_png/")
        else:
            self.img_label.setText("")
            self.img_label.setPixmap(pixmap)
    def _pixmap_for(self, path, fallback=None):
        """同一张图只解码、缩放一次，之后直接复用，切换立绘不再重复吃 CPU。"""
        cached = self._pix_cache.get(path)
        if cached is not None:
            return cached
        pixmap = self._load_pixmap(path, fallback)
        if not pixmap.isNull():
            self._pix_cache[path] = pixmap
        return pixmap
    def reload_all_pixmap(self):
        idle_images = SICK_IDLE_IMAGES if is_sick else NORMAL_IDLE_IMAGES
        self.idle_pose_images = [
            pixmap for pixmap in (self._pixmap_for(path) for path in _img_paths(idle_images))
            if not pixmap.isNull()
        ]
        if not self.idle_pose_images:
            self.idle_pose_images = [self._pixmap_for(IMG_IDLE)]
        self.idle_pose_index = 0
        self.pix_idle = self.idle_pose_images[0]
        self.pix_talk = self._pixmap_for(IMG_TALK, self.pix_idle)
        self.pix_exit = self._pixmap_for(IMG_SLEEP, self.pix_idle)
        self.pix_think = self._pixmap_for(IMG_THINK, self.pix_idle)
        self.reset_idle()
    def check_weather(self):
        """联网查天气放到后台线程，查完用信号回到主线程换立绘，界面不卡。"""
        if self._weather_pending:
            return
        self._weather_pending = True
        threading.Thread(target=self._fetch_weather, daemon=True).start()
    def _fetch_weather(self):
        try:
            self.weather_changed.emit(weather(home), "")
        except Exception as exc:
            self.weather_changed.emit("", str(exc))
        finally:
            self._weather_pending = False
    def _apply_weather(self, text, error):
        global IMG_IDLE, IMG_TALK, IMG_SLEEP, IMG_THINK, is_sick
        if error:
            print(f"[天气检测失败] {error}，使用默认立绘")
        sick = (not error) and any(tag in text for tag in RAIN_TAGS)
        was_sick = is_sick
        if sick == was_sick:
            # 天气状态没变，立绘本来就是对的，不用重新解码和缩放图片
            return
        is_sick = sick
        IMG_IDLE, IMG_TALK, IMG_SLEEP, IMG_THINK = _img_paths(SICK_IMG if sick else NORMAL_IMG)
        self.reload_all_pixmap()
        if sick:
            print("[天气] 下雨天，切换病弱立绘")
            tip = SICK_TEXT
        else:
            print("[天气] 晴天，恢复正常立绘")
            tip = "薇尔莉特的感冒已经好转，身体恢复正常。"
        if self.chat_win:
            self.chat_win._log_history(tip)

    def closeEvent(self, event):
        self.weather_timer.stop()
        super().closeEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint()
            self._was_dragged = False
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event):
        if self._drag_offset is not None:
            self._was_dragged = True
            delta = event.globalPosition().toPoint() - self._drag_offset
            self.move(self.x() + delta.x(), self.y() + delta.y())
            if self.chat_win:
                self.chat_win.move(self.chat_win.x() + delta.x(), self.chat_win.y() + delta.y())
            self._drag_offset = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._was_dragged:
            self.cycle_idle_pose()
        self._drag_offset = None
        super().mouseReleaseEvent(event)
    def _stop_timer(self):
        if self._talk_timer is not None:
            if self._talk_timer.isActive():
                self._talk_timer.stop()
            try:
                self._talk_timer.timeout.disconnect()
            except Exception:
                pass
        self._talk_timer = None
    def switch_talk(self, text=""):
        self._stop_timer()
        self._show_pixmap(self.pix_talk)
        self._talk_timer = QTimer(self)
        self._talk_timer.setSingleShot(True)
        self._talk_timer.timeout.connect(self.reset_idle)
        self._talk_timer.start(60000)
    def switch_exit(self):
        self._stop_timer()
        self.is_sleep = True
        self._show_pixmap(self.pix_exit)
    def switch_think(self):
        self._stop_timer()
        self.is_sleep = False
        self._show_pixmap(self.pix_think)
    def cycle_idle_pose(self):
        if len(self.idle_pose_images) < 2:
            return
        self.idle_pose_index = (self.idle_pose_index + 1) % len(self.idle_pose_images)
        self.pix_idle = self.idle_pose_images[self.idle_pose_index]
        self._show_pixmap(self.pix_idle)
    def reset_idle(self):
        if self.is_sleep:
            return  
        self._show_pixmap(self.pix_idle)
class ChatHistoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._drag_offset = None
        self.resize(400, 400)
        self.move(1060, 550)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        central = QWidget()
        self.setCentralWidget(central)
        central.installEventFilter(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setFont(QFont("微软雅黑", 11))
        self.text_display.setStyleSheet(
            "QTextEdit{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(255,252,245,0.95),stop:1 rgba(240,235,225,0.88));"
            "border:1px solid rgba(180,170,140,0.4);border-radius:10px;"
            "padding:8px;color:#4a4038;}")
        # 只保留最近 400 条记录，聊天久了窗口也不会越来越吃内存和重绘
        self.text_display.document().setMaximumBlockCount(400)
        layout.addWidget(self.text_display)
    def append(self, msg):
        self.text_display.append(msg)
    def eventFilter(self, obj, event):
        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemMove()
            return True
        return super().eventFilter(obj, event)
class ChatWindow(QMainWindow):
    CAMERA_PANEL_HEIGHT = 230
    play_started = pyqtSignal(str)
    voice_result = pyqtSignal(str)
    tts_finished = pyqtSignal()
    def __init__(self, mascot_window):
        super().__init__()
        self.mascot_win = mascot_window
        self.memory_store = memory_store
        self.history_win = ChatHistoryWindow()
        self.history_win.show()
        self.play_started.connect(self._on_play_started)
        self.voice_result.connect(self._on_voice_result)
        self.tts_finished.connect(self._on_tts_finished)
        self._bind_tts_log()
        self._worker = None
        self.is_recording = False
        self._recording_source = None
        self._voice_recognition_pending = False
        self._tts_reply_active = False
        self.camera_worker = None
        self._latest_camera_status = "摄像头未开启"
        self._camera_base_height = 560
        # ==========关键修复1：开启键盘焦点接收==========
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # 屏幕缩放 125% 时逻辑分辨率只有 1228x768，窗口不能太高，否则底部会跑出屏幕
        self.resize(420, 560)
        self.move(150, 140)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        central_widget = QWidget()
        central_widget.setStyleSheet("background:transparent;")
        self.setCentralWidget(central_widget)

        outer = QVBoxLayout(central_widget)
        outer.setContentsMargins(12, 12, 12, 12)  # 留出投影空间

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "QFrame#card{background:rgba(253,251,255,0.97);"
            "border:1px solid rgba(186,174,212,0.55);border-radius:18px;}"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(70, 50, 110, 95))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---------- 标题栏（按住可拖动） ----------
        self._title_bar = QWidget()
        self._title_bar.setObjectName("titleBar")
        self._title_bar.setStyleSheet("QWidget#titleBar{background:transparent;}")
        self._title_bar.installEventFilter(self)
        tb = QHBoxLayout(self._title_bar)
        tb.setContentsMargins(18, 12, 12, 4)
        tb.setSpacing(6)

        title_col = QVBoxLayout()
        title_col.setSpacing(0)
        title_label = QLabel("薇尔莉特")
        title_label.setStyleSheet("color:#4A3F6B;background:transparent;")
        title_label.setFont(QFont("Microsoft YaHei UI", 12, QFont.Weight.DemiBold))
        subtitle = QLabel("Violet Evergarden")
        subtitle.setStyleSheet("color:#AA9FC4;background:transparent;")
        subtitle.setFont(QFont("Microsoft YaHei UI", 7))
        title_col.addWidget(title_label)
        title_col.addWidget(subtitle)
        tb.addLayout(title_col)
        tb.addStretch()

        # ==========关键修复2：按钮不抢占全局键盘焦点==========
        self.menu_btn = QPushButton("☰")
        self.camera_btn = QPushButton("◉ 视觉")
        self.camera_btn.setObjectName("cameraToggle")
        self.camera_btn.setCheckable(True)
        self.camera_btn.setToolTip("开启摄像头视觉输入")
        self.camera_btn.setAccessibleName("面部检测与自动录音")
        self.camera_btn.setFixedSize(68, 26)
        self.camera_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.camera_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.camera_btn.setStyleSheet(
            "QPushButton#cameraToggle{background:transparent;border:none;border-radius:13px;"
            "color:#8C81A6;font-size:10px;}"
            "QPushButton#cameraToggle:hover{background:rgba(140,125,180,0.15);color:#5B4B8A;}"
            "QPushButton#cameraToggle:checked{background:#EEE8F7;color:#5B4B8A;}"
        )
        self.preview_btn = QPushButton("预览")
        self.preview_btn.setFixedSize(40, 26)
        self.preview_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview_btn.setToolTip("重新显示摄像头预览")
        self.preview_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:10px;"
            "color:#6A579C;font-size:9px;}"
            "QPushButton:hover{background:#EEE8F7;}"
        )
        self.preview_btn.clicked.connect(self._show_camera_preview)
        self.preview_btn.hide()
        self.close_btn = QPushButton("✕")
        self.close_btn.setToolTip("退出 Violet 并关闭后台服务")
        for btn in (self.menu_btn, self.close_btn):
            btn.setFixedSize(26, 26)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{background:transparent;border:none;border-radius:13px;"
                "color:#8C81A6;font-size:13px;}"
                "QPushButton:hover{background:rgba(140,125,180,0.15);color:#5B4B8A;}"
            )
        self.menu_btn.clicked.connect(self.show_menu)
        self.camera_btn.toggled.connect(self._toggle_camera)
        self.close_btn.clicked.connect(QApplication.instance().quit)
        tb.addWidget(self.camera_btn)
        tb.addWidget(self.preview_btn)
        tb.addWidget(self.menu_btn)
        tb.addWidget(self.close_btn)
        layout.addWidget(self._title_bar)

        self.camera_panel = QFrame()
        self.camera_panel.setObjectName("cameraPanel")
        self.camera_panel.setFixedHeight(self.CAMERA_PANEL_HEIGHT)
        self.camera_panel.setStyleSheet(
            "QFrame#cameraPanel{background:rgba(245,241,250,0.8);"
            "border-bottom:1px solid #ECE6F4;}"
        )
        camera_layout = QVBoxLayout(self.camera_panel)
        camera_layout.setContentsMargins(12, 7, 12, 7)
        camera_layout.setSpacing(4)
        self.camera_preview = QLabel("摄像头未开启")
        self.camera_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_preview.setFixedHeight(174)
        self.camera_preview.setStyleSheet(
            "QLabel{background:#202026;border:1px solid #DCD4E9;border-radius:6px;"
            "color:#D4CDE0;font-size:10px;}"
        )
        camera_layout.addWidget(self.camera_preview)
        camera_status_row = QHBoxLayout()
        camera_status_row.setSpacing(8)
        self.camera_status = QLabel("摄像头未开启")
        self.camera_status.setStyleSheet(
            "QLabel{background:transparent;color:#6A579C;font-size:9px;}"
        )
        self.camera_privacy = QLabel("画面仅本机处理，不保存")
        self.camera_privacy.setStyleSheet(
            "QLabel{background:transparent;color:#9A93AE;font-size:8px;}"
        )
        self.camera_close_btn = QPushButton("×")
        self.camera_close_btn.setFixedSize(22, 22)
        self.camera_close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.camera_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.camera_close_btn.setToolTip("隐藏预览；视觉检测继续")
        self.camera_close_btn.setAccessibleName("隐藏预览")
        self.camera_close_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:11px;"
            "color:#8C81A6;font-size:13px;}"
            "QPushButton:hover{background:rgba(140,125,180,0.15);color:#5B4B8A;}"
        )
        self.camera_close_btn.clicked.connect(self._close_camera_preview)
        camera_status_row.addWidget(self.camera_status, 1)
        camera_status_row.addWidget(self.camera_privacy)
        camera_status_row.addWidget(self.camera_close_btn)
        camera_layout.addLayout(camera_status_row)
        layout.addWidget(self.camera_panel)
        self.camera_panel.hide()

        # ---------- 消息区 ----------
        self.chat_view = ChatView()
        self.chat_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view_wrap = QWidget()
        view_wrap.setStyleSheet("background:transparent;")
        vw = QVBoxLayout(view_wrap)
        vw.setContentsMargins(10, 2, 10, 0)
        vw.addWidget(self.chat_view)
        layout.addWidget(view_wrap, 1)

        # ---------- 输入区 ----------
        input_row = QWidget()
        input_row.setStyleSheet("background:transparent;")
        ir = QHBoxLayout(input_row)
        ir.setContentsMargins(12, 8, 12, 12)
        ir.setSpacing(8)

        self.input_box = QLineEdit()
        self.typing_sound = TypingSound(self)
        self.input_box.installEventFilter(self.typing_sound)
        self.input_box.setPlaceholderText("输入对话，/ja切换日语 /zh切换汉语")
        self.input_box.setFont(QFont("Microsoft YaHei UI", 10))
        self.input_box.setStyleSheet(
            "QLineEdit{background:#F5F1FA;border:1px solid #E2DAF0;border-radius:17px;"
            "padding:9px 15px;color:#3D3554;}"
            "QLineEdit:focus{border:1px solid #B7A4DC;background:#FFFFFF;}"
        )
        self.input_box.returnPressed.connect(self.send_message)
        ir.addWidget(self.input_box, 1)

        self.send_btn = QPushButton("➤")
        self.send_btn.setFixedSize(34, 34)
        self.send_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #8B7AB8,stop:1 #7461A6);border:none;border-radius:17px;"
            "color:#FFFFFF;font-size:13px;}"
            "QPushButton:hover{background:#6A579C;}"
            "QPushButton:pressed{background:#5E4C8D;}"
        )
        self.send_btn.clicked.connect(self.send_message)
        ir.addWidget(self.send_btn)
        layout.addWidget(input_row)

        self.chat_view.add_system("按住空格说话 · 松开发送 · 回车发送文字")
        QApplication.instance().installEventFilter(self)
        # 探测语音服务放后台，别让启动时多等几秒
        threading.Thread(target=check_api, daemon=True).start()
        self.setFocus()

    # ==========关键修复3：点击窗口空白自动获取焦点==========
    def mousePressEvent(self, event):
        # 点击空白区域强制获取键盘焦点
        self.setFocus()
        super().mousePressEvent(event)

    def _resize_for_camera(self, enabled):
        screen = self.screen()
        height = self._camera_base_height + (self.CAMERA_PANEL_HEIGHT if enabled else 0)
        if screen is not None:
            available = screen.availableGeometry()
            height = min(height, max(420, available.height() - 24))
            x = min(max(self.x(), available.left()), available.right() - self.width() + 1)
            y = min(max(self.y() - (height - self.height()) // 2, available.top()),
                    available.bottom() - height + 1)
            self.resize(self.width(), height)
            self.move(x, y)
        else:
            self.resize(self.width(), height)

    def _toggle_camera(self, enabled):
        if enabled:
            self.camera_btn.setToolTip("关闭摄像头视觉输入")
            self._resize_for_camera(True)
            self.camera_panel.show()
            self.preview_btn.hide()
            self.camera_preview.setPixmap(QPixmap())
            self.camera_preview.setText("正在连接摄像头…")
            self.camera_status.setText("正在申请摄像头权限")
            self._latest_camera_status = "正在申请摄像头权限"
            worker = CameraWorker(parent=self)
            self.camera_worker = worker
            worker.frame_ready.connect(self._show_camera_frame)
            worker.status_changed.connect(self._on_camera_status)
            worker.speech_detected.connect(self._on_camera_speaking)
            worker.error.connect(self._on_camera_error)
            worker.finished.connect(worker.deleteLater)
            worker.start()
            return

        self.camera_btn.setToolTip("开启摄像头视觉输入")
        self.camera_panel.hide()
        self.preview_btn.hide()
        self._stop_camera()
        self.camera_preview.setPixmap(QPixmap())
        self.camera_preview.setText("摄像头未开启")
        self.camera_status.setText("摄像头未开启")
        self._latest_camera_status = "摄像头未开启"
        self._resize_for_camera(False)

    def _show_camera_frame(self, image):
        if self.camera_panel.isHidden():
            return
        pixmap = QPixmap.fromImage(image).scaled(
            self.camera_preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.camera_preview.setText("")
        self.camera_preview.setPixmap(pixmap)

    def _on_camera_error(self, message):
        self._stop_camera()
        blocker = QSignalBlocker(self.camera_btn)
        self.camera_btn.setChecked(False)
        del blocker
        self.camera_btn.setToolTip("开启摄像头视觉输入")
        self.camera_panel.hide()
        self.preview_btn.hide()
        self._resize_for_camera(False)
        self.camera_preview.setPixmap(QPixmap())
        self.camera_preview.setText("摄像头不可用")
        self.camera_status.setText(message)
        self._latest_camera_status = message
        self.chat_view.add_system(f"视觉输入不可用：{message}")
        self._log_history(f"【视觉输入】{message}\n")

    def _on_camera_status(self, status):
        if not self.camera_btn.isChecked():
            return
        self._latest_camera_status = status
        if not self._voice_recognition_pending:
            self.camera_status.setText(status)

    def _close_camera_preview(self):
        if not self.camera_btn.isChecked():
            return
        self.camera_panel.hide()
        self.preview_btn.show()
        self._resize_for_camera(False)

    def _show_camera_preview(self):
        if not self.camera_btn.isChecked():
            return
        self._resize_for_camera(True)
        self.camera_panel.show()
        self.preview_btn.hide()
        self.camera_status.setText(self._latest_camera_status)

    def _stop_camera(self):
        if self.is_recording and self._recording_source == "camera":
            self._cancel_voice_recording()
        worker = self.camera_worker
        self.camera_worker = None
        if worker is not None and worker.isRunning():
            worker.stop()
            if not worker.wait(4000):
                self._log_history("【视觉输入】摄像头线程仍在关闭，请稍候。\n")

    def _begin_voice_recording(self, source):
        if self.is_recording or self._voice_recognition_pending:
            return False
        self.is_recording = True
        self._recording_source = source
        start_listening()
        return True

    def _finish_voice_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self._recording_source = None
        self._voice_recognition_pending = True
        self.chat_view.add_system("正在识别语音…")
        self._log_history("【语音】停止收音，识别中...\n")
        voice_input_async(self._voice_callback)

    def _cancel_voice_recording(self):
        if self.is_recording:
            cancel_listening()
        self.is_recording = False
        self._recording_source = None

    def _on_camera_speaking(self, speaking):
        if speaking:
            if self._tts_reply_active or tts_mod._IS_PLAYING:
                return
            if (self.camera_btn.isChecked() and self.input_box.isEnabled()
                    and self._begin_voice_recording("camera")):
                self.chat_view.add_system("检测到讲话，正在录音…")
                self._log_history("【视觉输入】检测到讲话，开始录音。\n")
            return

        if self.is_recording and self._recording_source == "camera":
            self.camera_status.setText("讲话结束 · 正在识别")
            self._finish_voice_recording()

    # 键盘按下事件
    def eventFilter(self, watched, event):
        if QApplication.activeWindow() is not self:
            return super().eventFilter(watched, event)

        # 标题栏按住可拖动整个窗口
        if (watched is getattr(self, "_title_bar", None)
                and event.type() == event.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            self.windowHandle().startSystemMove()
            return True

        if event.type() in (event.Type.KeyPress, event.Type.KeyRelease) and event.isAutoRepeat():
            return True

        if event.type() == event.Type.KeyRelease and event.key() == Qt.Key.Key_Space:
            if self.is_recording and self._recording_source == "keyboard":
                self._finish_voice_recording()
                return True
            return super().eventFilter(watched, event)

        if event.type() != event.Type.KeyPress:
            return super().eventFilter(watched, event)

        if QApplication.focusWidget() is self.input_box:
            return super().eventFilter(watched, event)

        if event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape and self.is_recording:
                self._cancel_voice_recording()
                self.chat_view.add_system("已取消语音输入")
                self._log_history("【语音】已取消本次语音输入\n")
                return True
            if (event.key() == Qt.Key.Key_Space
                    and self._begin_voice_recording("keyboard")):
                self.chat_view.add_system("按住空格说话，松开发送 · ESC 取消")
                self._log_history("【语音】开始收音...\n")
                return True

        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.isAutoRepeat():
            return
        # 输入框激活时完全跳过语音快捷键
        if self.input_box.hasFocus():
            super().keyPressEvent(event)
            return
        # ESC取消录音
        if event.key() == Qt.Key.Key_Escape and self.is_recording:
            self._cancel_voice_recording()
            self.chat_view.add_system("已取消语音输入")
            self._log_history("【语音】已取消本次语音输入\n")
            event.accept()
            return
        # 空格开始录音
        if event.key() == Qt.Key.Key_Space and self._begin_voice_recording("keyboard"):
            self.chat_view.add_system("按住空格说话，松开发送 · ESC 取消")
            self._log_history("【语音】开始收音...\n")
            event.accept()
            return
        # 其他按键交给默认逻辑
        super().keyPressEvent(event)


    def keyReleaseEvent(self, event):
        if event.isAutoRepeat():
            return
        if self.input_box.hasFocus():
            super().keyReleaseEvent(event)
            return

        if (event.key() == Qt.Key.Key_Space and self.is_recording
                and self._recording_source == "keyboard"):
            self._finish_voice_recording()
            event.accept()
            return
        super().keyReleaseEvent(event)

    
    def _voice_callback(self, text):
        self.voice_result.emit(text)

    def _on_voice_result(self, text):
        self._voice_recognition_pending = False
        if self.camera_btn.isChecked():
            self.camera_status.setText(self._latest_camera_status)
        fail_words = ["未检测到", "无法识别", "网络异常", "出错", "失败"]
        if any(w in text for w in fail_words):
            tip = f"语音识别失败：{text}"
            self.chat_view.add_system(tip)
            self._log_history(f"【语音失败】{text}\n")
            return
        self.input_box.setText(text)
        self.send_message()

    def open_settings(self, tab=0):
        dialog = SettingsDialog(
            self,
            tab=int(tab),
            memory_store=memory_store,
            working_memory=working_memory,
        )
        dialog.memory_page.short_term_cleared.connect(self._clear_short_term_memory)
        dialog.exec()

    def _clear_short_term_memory(self):
        global history
        history = []
        working_memory.clear()
        message = "短期对话与临时印象已清空。"
        self.chat_view.add_system(message)
        self._log_history(f"【记忆】{message}\n")

    def show_menu(self):
        menu = QMenu(self)
        settings_action = QAction("设置…", self)
        settings_action.triggered.connect(self.open_settings)
        menu.addAction(settings_action)
        menu.addSeparator()
        history_action = QAction("隐藏聊天记录", self)
        history_action.setCheckable(True)
        history_action.setChecked(not self.history_win.isVisible())
        history_action.triggered.connect(self.toggle_history)
        menu.addAction(history_action)
        chat_action = QAction("隐藏聊天框", self)
        chat_action.setCheckable(True)
        chat_action.setChecked(not self.isVisible())
        chat_action.triggered.connect(self.toggle_chat)
        menu.addAction(chat_action)
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))
    def toggle_history(self, hide):
        if hide:
            self.history_win.hide()
        else:
            self.history_win.show()
    def toggle_chat(self, hide):
        if hide:
            self.hide()
        else:
            self.show()

    def _bind_tts_log(self):
        win = self.history_win
        tts_mod._log = lambda *a: win.append(" ".join(str(x) for x in a))
    def _log_history(self, msg):
        self.history_win.append(msg)
    def send_message(self):
        global paused, tts_lang, history
        user_text = self.input_box.text().strip()
        if not user_text:
            return
        self.chat_view.add_user(user_text)
        self._log_history(f"你：{user_text}")
        self.input_box.clear()
        if user_text == "退出":
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        if user_text == "再见":
            self.mascot_win.switch_exit()
            self.chat_view.add_assistant("纸墨暂且收置一旁，愿思念伴你左右，再会。")
            self._log_history("【系统】AI 对话已暂停，窗口保留。随时可继续输入对话唤醒薇尔莉特。\n")
            paused = True
            if len(history) > 8:
                history = history[-8:]
    
            self.input_box.clear()
    
            return
        memory_command = self._handle_memory_command(user_text)
        if memory_command is not None:
            self.chat_view.add_system(memory_command)
            self._log_history(f"【记忆】{memory_command}\n")
            return
        if paused:
            self._log_history("【系统】薇尔莉特已唤醒，对话恢复。\n")
            paused = False
        if user_text == "/ja":
            tts_lang = "ja"
            self._log_history("【系统】朗读切换为日语\n")
            return
        if user_text == "/zh":
            tts_lang = "zh"
            self._log_history("【系统】朗读切换为汉语\n")
            return
        self.input_box.setEnabled(False)
        self.input_box.setPlaceholderText("薇尔莉特正在书写中...")
        self.mascot_win.switch_think()
        memory_context = "\n\n".join(
            part for part in (memory_store.build_context(), working_memory.build_context()) if part
        )
        self._worker = AIWorker(user_text, memory_context)
        self._worker.reply_ready.connect(self._on_reply)
        self._worker.error_ready.connect(self._on_error)
        self._worker.start()

    def _handle_memory_command(self, user_text):
        global history
        commands = (
            ("/记住情感", "emotion"),
            ("/记住事实", "fact"),
        )
        for command, kind in commands:
            if user_text == command or user_text.startswith(command + " "):
                text = user_text[len(command) :].strip(" ：:")
                if not text:
                    return "请在命令后写下要保存的内容。"
                try:
                    self.memory_store.add(text, kind)
                except Exception as exc:  # noqa: BLE001
                    return f"长期记忆保存失败：{exc}"
                label = "情感" if kind == "emotion" else "事实"
                return f"已将这条{label}线索加入长期记忆，可在设置的“记忆”页选择遗忘。"

        if user_text == "/遗忘" or user_text.startswith("/遗忘 "):
            phrase = user_text[len("/遗忘") :].strip()
            if not phrase:
                return "请在命令后写下记忆中的关键词；也可在设置的“记忆”页逐条选择遗忘。"
            try:
                removed = self.memory_store.forget_matching(phrase)
            except Exception as exc:  # noqa: BLE001
                return f"长期记忆遗忘失败：{exc}"
            return f"已遗忘 {removed} 条包含“{phrase}”的长期记忆。"

        if user_text == "/污染" or user_text.startswith("/污染 "):
            impression = user_text[len("/污染") :].strip()
            if not impression:
                return "请在命令后写下一条临时印象；默认持续 4 次成功回复。"
            try:
                working_memory.inject(impression, turns=4)
            except ValueError as exc:
                return f"临时印象未写入：{exc}"
            return "临时印象已加入短期记忆，默认持续 4 次成功回复；它可能有误，可用 /清空短期 移除。"

        if user_text == "/清空短期":
            history = []
            working_memory.clear()
            return "短期对话与临时印象已清空。"
        return None

    def _on_reply(self, answer):
        working_memory.advance()
        self._log_history(f"薇尔莉特：{answer}\n")
        if getattr(llm_mod, "LAST_FINISH_REASON", None) == "length":
            self._log_history("【系统】回复达到 MAX_TOKENS 上限被截断，可在 config.env 里调大\n")
        if ENABLE_TTS:                            
            global tts_lang
            if tts_lang == "ja" and not any('\u3040' <= c <= '\u30ff' for c in answer):
                text_speak, actual_lang = translate_for_tts(answer, tts_lang)
            else:
                text_speak, actual_lang = answer, tts_lang
            self._tts_reply_active = True
            speak(text_speak, lang=actual_lang,
                  on_play=lambda: self.play_started.emit(answer),
                  on_audio_finish=self.tts_finished.emit)
        else:
            self.chat_view.add_assistant(answer)
            self._restore_input()
    def _on_play_started(self, text):
        self.mascot_win.switch_talk(text)
        self.chat_view.stream_start()
        self._typewriter("", text, 0)
    def _typewriter(self, prefix, full, idx):
        self.chat_view.stream_set(full[:idx])
        if idx <= len(full):
            QTimer.singleShot(50, lambda: self._typewriter(prefix, full, idx + 1))
        else:
            self.chat_view.stream_end()
            self._restore_input()
    def _on_error(self, error_msg):
        self.chat_view.add_system(f"【异常】{error_msg}")
        self._log_history(f"【异常】{error_msg}\n")
        self._restore_input()
    def _restore_input(self):
        self.input_box.setEnabled(True)
        self.input_box.setPlaceholderText("输入对话，空格语音 | /ja日语 /zh汉语")
        self.setFocus()

    def _on_tts_finished(self):
        self._tts_reply_active = False
        self._restore_input()

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._stop_camera()
        self._cancel_voice_recording()
        super().closeEvent(event)

def _tray_icon():
    pix = QPixmap(str(_IMG_DIR / "BgSub_站姿2.png"))
    if pix.isNull():
        return QIcon()
    scaled = pix.scaled(
        64, 64,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(scaled)


def _setup_tray(app, mascot, chat_win):
    """右下角托盘图标：窗口被挡住或从菜单隐藏后，可从这里叫回来。"""
    tray = QSystemTrayIcon(_tray_icon(), app)
    tray.setToolTip("薇尔莉特 · Violet")

    menu = QMenu()

    chat_action = QAction("聊天窗口", menu)
    chat_action.setCheckable(True)
    chat_action.setChecked(chat_win.isVisible())
    chat_action.toggled.connect(lambda on: (chat_win.show(), chat_win.raise_(),
                                             chat_win.activateWindow()) if on else chat_win.hide())

    mascot_action = QAction("立绘", menu)
    mascot_action.setCheckable(True)
    mascot_action.setChecked(mascot.isVisible())
    mascot_action.toggled.connect(mascot.setVisible)

    camera_action = QAction("视觉输入", menu)
    camera_action.setCheckable(True)
    camera_action.setChecked(chat_win.camera_btn.isChecked())
    camera_action.toggled.connect(chat_win.camera_btn.setChecked)
    chat_win.camera_btn.toggled.connect(camera_action.setChecked)
    chat_win.camera_btn.toggled.connect(
        lambda on: tray.setToolTip("薇尔莉特 · 视觉输入开启" if on else "薇尔莉特 · Violet")
    )

    settings_action = QAction("设置…", menu)
    settings_action.triggered.connect(chat_win.open_settings)

    log_root = os.path.join(os.environ.get("TEMP", ""), "violet")
    log_action = QAction("打开日志文件夹", menu)
    log_action.triggered.connect(lambda: os.startfile(log_root) if os.path.isdir(log_root) else None)

    quit_action = QAction("退出 Violet", menu)
    quit_action.triggered.connect(app.quit)

    menu.addAction(chat_action)
    menu.addAction(mascot_action)
    menu.addSeparator()
    menu.addAction(camera_action)
    menu.addAction(settings_action)
    menu.addAction(log_action)
    menu.addSeparator()
    menu.addAction(quit_action)

    def sync():
        # 托盘菜单可以单独隐藏窗口，勾选状态随窗口显示状态同步。
        chat_action.setChecked(chat_win.isVisible())
        mascot_action.setChecked(mascot.isVisible())
        camera_action.setChecked(chat_win.camera_btn.isChecked())
        tray.setToolTip(
            "薇尔莉特 · 视觉输入开启" if chat_win.camera_btn.isChecked()
            else "薇尔莉特 · Violet"
        )

    menu.aboutToShow.connect(sync)
    tray.setContextMenu(menu)

    def on_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if chat_win.isVisible():
                chat_win.hide()
            else:
                chat_win.show()
                chat_win.raise_()
                chat_win.activateWindow()

    tray.activated.connect(on_activated)
    tray.show()
    return tray


class _EnvCheckWorker(QThread):
    done = pyqtSignal(list)

    def run(self):
        try:
            from diagnostics import check_environment

            self.done.emit(check_environment())
        except Exception as exc:  # noqa: BLE001
            self.done.emit([{"level": "error", "title": "自检本身出错了", "detail": str(exc)}])


def run():
    app = QApplication(sys.argv)
    # 托盘菜单可单独隐藏窗口；标题栏的关闭按钮会显式退出应用。
    app.setQuitOnLastWindowClosed(False)

    mascot = DesktopMascot()
    mascot.show()
    chat_win = ChatWindow(mascot)
    mascot.chat_win = chat_win
    chat_win.show()
    tray = _setup_tray(app, mascot, chat_win)

    shutdown_started = False

    def shutdown():
        nonlocal shutdown_started
        if shutdown_started:
            return
        shutdown_started = True
        tray.hide()
        chat_win.close()
        chat_win.history_win.close()
        mascot.close()
        stop_process_tree(_tts_proc)

    app.aboutToQuit.connect(shutdown)

    # 第一次给别人的机器跑时，配置多半是空的：直接弹出设置页，省得去翻 config.env
    if not (llm_mod.API_KEY and llm_mod.API_URL and llm_mod.MODEL_NAME):
        QTimer.singleShot(400, lambda: chat_win.open_settings(0))
    else:
        checker = _EnvCheckWorker()

        def _on_checks(items):
            errors = [i for i in items if i.get("level") == "error"]
            warns = [i for i in items if i.get("level") == "warn"]
            for item in errors:
                detail = item.get("detail") or ""
                chat_win.chat_view.add_system(
                    f"⚠ {item['title']}" + (f"：{detail}" if detail else ""))
            if warns:
                # 提醒不逐条刷屏，汇总一句，细节去「设置 → 自检」看
                chat_win.chat_view.add_system(f"· 有 {len(warns)} 项提醒，可在 设置 → 自检 查看")
            if errors:
                chat_win.open_settings(2)  # 直接停在「自检」页

        checker.done.connect(_on_checks)
        QTimer.singleShot(1200, checker.start)

    try:
        return app.exec()
    finally:
        shutdown()


if __name__ == "__main__":
    sys.exit(run())
