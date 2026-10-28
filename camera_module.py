"""Local webcam preview and mouth-motion speech detection."""

import sys
import time
from collections import deque
import os
import shutil
import tempfile
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


def _is_ascii_path(path: Path) -> bool:
    return all(ord(char) < 128 for char in str(path))


def resolve_face_model_path(model_path, cache_roots=None) -> Path:
    """OpenCV's Windows FileStorage cannot read cascade files through CJK paths."""
    model_path = Path(model_path)
    if not model_path.is_file():
        raise RuntimeError("OpenCV 人脸检测模型文件不存在，请重新安装 OpenCV。")
    if _is_ascii_path(model_path):
        return model_path

    if cache_roots is None:
        cache_roots = []
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            cache_roots.append(Path(local_app_data) / "Violet" / "OpenCV")
        cache_roots.extend((
            Path(tempfile.gettempdir()) / "Violet" / "OpenCV",
            Path(os.environ.get("WINDIR", r"C:\Windows")) / "Temp" / "Violet",
        ))

    seen = set()
    for root in cache_roots:
        root = Path(root)
        if not _is_ascii_path(root) or str(root).casefold() in seen:
            continue
        seen.add(str(root).casefold())
        try:
            root.mkdir(parents=True, exist_ok=True)
            cached_model = root / model_path.name
            if (not cached_model.is_file()
                    or cached_model.stat().st_size != model_path.stat().st_size):
                shutil.copyfile(model_path, cached_model)
            return cached_model
        except OSError:
            continue

    raise RuntimeError("OpenCV 无法读取中文路径，且找不到可写的英文路径缓存目录。")


def load_face_detectors(cv2):
    cascade_root = Path(cv2.data.haarcascades)

    def load(filename):
        model_path = cascade_root / filename
        if not model_path.is_file():
            return None
        classifier = cv2.CascadeClassifier(str(resolve_face_model_path(model_path)))
        return None if classifier.empty() else classifier

    frontal = [
        classifier
        for filename in (
            "haarcascade_frontalface_default.xml",
            "haarcascade_frontalface_alt2.xml",
        )
        if (classifier := load(filename)) is not None
    ]
    if not frontal:
        raise RuntimeError("人脸检测模型不可用，请重新安装 OpenCV。")

    return frontal, load("haarcascade_profileface.xml")


def detect_face(cv2, gray, frontal_cascades, profile_cascade):
    detection_options = {
        "scaleFactor": 1.08,
        "minNeighbors": 4,
        "minSize": (36, 36),
    }
    for cascade in frontal_cascades:
        faces = cascade.detectMultiScale(gray, **detection_options)
        if len(faces):
            return max(faces, key=lambda rect: rect[2] * rect[3]), "frontal"

    if profile_cascade is None:
        return None, None

    mirrored = cv2.flip(gray, 1)
    for image, is_mirrored in ((gray, False), (mirrored, True)):
        faces = profile_cascade.detectMultiScale(image, **detection_options)
        if len(faces):
            face = max(faces, key=lambda rect: rect[2] * rect[3])
            x, y, width, height = face
            if is_mirrored:
                x = gray.shape[1] - x - width
            return (x, y, width, height), "profile"

    return None, None


class MouthMotionDetector:
    """Small temporal filter that rejects broad head movement and short noise."""

    MOTION_THRESHOLD = 0.045
    CONTROL_MARGIN = 0.015
    CONTROL_MULTIPLIER = 1.35
    START_HITS = 3
    START_WINDOW = 0.8
    STOP_DELAY = 1.2

    def __init__(self):
        self._motion_times = deque()
        self._last_motion_at = None
        self.speaking = False

    def update(self, mouth_activity: float, control_activity: float, now=None) -> bool:
        now = time.monotonic() if now is None else now
        moving = (
            mouth_activity >= self.MOTION_THRESHOLD
            and mouth_activity > control_activity * self.CONTROL_MULTIPLIER + self.CONTROL_MARGIN
        )

        if moving:
            self._motion_times.append(now)
            self._last_motion_at = now

        while self._motion_times and now - self._motion_times[0] > self.START_WINDOW:
            self._motion_times.popleft()

        if not self.speaking:
            if (len(self._motion_times) >= self.START_HITS
                    and self._motion_times[-1] - self._motion_times[0] >= 0.18):
                self.speaking = True
        elif self._last_motion_at is None or now - self._last_motion_at >= self.STOP_DELAY:
            self.speaking = False
            self._motion_times.clear()
            self._last_motion_at = None

        return self.speaking


class CameraWorker(QThread):
    frame_ready = pyqtSignal(QImage)
    status_changed = pyqtSignal(str)
    speech_detected = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, camera_index=0, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self._running = True

    def stop(self):
        self._running = False
        self.requestInterruption()

    def _status(self, value):
        if value != getattr(self, "_last_status", None):
            self._last_status = value
            self.status_changed.emit(value)

    @staticmethod
    def _activity(cv2, previous, current):
        if previous is None or previous.shape != current.shape:
            return 0.0
        delta = cv2.absdiff(previous, current)
        _, changed = cv2.threshold(delta, 17, 255, cv2.THRESH_BINARY)
        return cv2.countNonZero(changed) / changed.size

    def run(self):
        capture = None
        detector = MouthMotionDetector()
        previous_mouth = None
        previous_control = None
        previous_speaking = False
        last_frame_at = 0.0

        try:
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError(
                    "缺少摄像头依赖，请安装 opencv-python-headless 后重启。"
                ) from exc

            backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
            capture = cv2.VideoCapture(self.camera_index, backend)
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                raise RuntimeError("无法打开摄像头，请检查设备占用或系统隐私权限。")

            frontal_cascades, profile_cascade = load_face_detectors(cv2)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

            self._status("正在监测人脸")
            failed_reads = 0
            while self._running and not self.isInterruptionRequested():
                ok, frame = capture.read()
                if not ok or frame is None:
                    failed_reads += 1
                    if failed_reads >= 20:
                        raise RuntimeError("摄像头画面读取失败，请检查设备连接。")
                    self.msleep(40)
                    continue

                failed_reads = 0
                frame = cv2.flip(frame, 1)
                height, width = frame.shape[:2]
                small_width = min(320, width)
                small_height = max(1, round(height * small_width / width))
                small = cv2.resize(frame, (small_width, small_height))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                detection_gray = clahe.apply(gray)
                face, face_pose = detect_face(
                    cv2, detection_gray, frontal_cascades, profile_cascade
                )

                mouth_activity = 0.0
                control_activity = 0.0
                if face is not None:
                    x, y, face_width, face_height = face
                    if face_pose == "frontal":
                        mouth = gray[
                            y + int(face_height * 0.60): y + int(face_height * 0.92),
                            x + int(face_width * 0.18): x + int(face_width * 0.82),
                        ]
                        control = gray[
                            y + int(face_height * 0.24): y + int(face_height * 0.46),
                            x + int(face_width * 0.20): x + int(face_width * 0.80),
                        ]
                        if mouth.size and control.size:
                            mouth = cv2.resize(mouth, (64, 32))
                            control = cv2.resize(control, (64, 24))
                            mouth = cv2.GaussianBlur(mouth, (5, 5), 0)
                            control = cv2.GaussianBlur(control, (5, 5), 0)
                            mouth_activity = self._activity(cv2, previous_mouth, mouth)
                            control_activity = self._activity(cv2, previous_control, control)
                            previous_mouth = mouth
                            previous_control = control
                    else:
                        previous_mouth = None
                        previous_control = None

                    scale_x = width / small_width
                    scale_y = height / small_height
                    left = round(x * scale_x)
                    top = round(y * scale_y)
                    right = round((x + face_width) * scale_x)
                    bottom = round((y + face_height) * scale_y)
                    color = (74, 180, 113) if detector.speaking else (190, 157, 226)
                    cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
                    face_status = (
                        "已捕捉人脸 · 等待讲话" if face_pose == "frontal"
                        else "检测到侧脸 · 请正对讲话"
                    )
                else:
                    previous_mouth = None
                    previous_control = None
                    face_status = "未检测到人脸"

                speaking = detector.update(mouth_activity, control_activity)
                if speaking != previous_speaking:
                    previous_speaking = speaking
                    self.speech_detected.emit(speaking)
                self._status("检测到讲话 · 正在录音" if speaking else face_status)

                now = time.monotonic()
                if now - last_frame_at >= 0.1:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = QImage(
                        rgb.data,
                        rgb.shape[1],
                        rgb.shape[0],
                        rgb.strides[0],
                        QImage.Format.Format_RGB888,
                    ).copy()
                    self.frame_ready.emit(image)
                    last_frame_at = now

        except Exception as exc:  # noqa: BLE001
            if self._running:
                self.error.emit(str(exc))
        finally:
            if capture is not None:
                capture.release()
            if previous_speaking:
                self.speech_detected.emit(False)
            self._status("摄像头已关闭")
