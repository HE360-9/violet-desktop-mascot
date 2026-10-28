import io
import json
import os
import shutil
import threading
import wave
from pathlib import Path

_BUNDLED_MODEL = Path(__file__).resolve().parent / "vosk-model" / "vosk-model-small-cn-0.22"
_model = None
_recording = False
_audio_buffer = []
_record_error = None
_record_thread_handle = None

# 优先走本机的 FunASR 服务（准确率高、能出标点）；
# 服务没起或还在加载模型时，自动回落到下面的 Vosk
ASR_API_URL = os.getenv("ASR_API_URL", "http://127.0.0.1:9881").rstrip("/")
SAMPLE_RATE = 16000


def _is_ascii_path(value: str) -> bool:
    return all(ord(ch) < 128 for ch in value)


def _resolve_model_path() -> Path:
    """
    Vosk 底层用的是窄字符路径，路径里带中文时它一律报
    “Folder ... does not contain model files”，哪怕文件一个不少。
    所以模型必须放在纯英文路径下：
      1. 优先 VOSK_MODEL_DIR（需为英文路径）
      2. 其次 %LOCALAPPDATA%\\violet\\<模型名>，不存在就从项目里复制一份过去
      3. 最后才用项目内路径（仅当它本身是英文路径）
    """
    env_dir = os.getenv("VOSK_MODEL_DIR", "").strip()
    if env_dir:
        candidate = Path(env_dir)
        if candidate.is_dir() and _is_ascii_path(str(candidate)):
            return candidate
        if env_dir:
            print(f"[语音输入] VOSK_MODEL_DIR 不可用（不存在或含中文）: {env_dir}")

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata and _is_ascii_path(local_appdata):
        target = Path(local_appdata) / "violet" / _BUNDLED_MODEL.name
        if target.is_dir():
            return target
        if _BUNDLED_MODEL.is_dir():
            print(f"[语音输入] 首次运行，把 Vosk 模型复制到英文路径: {target}")
            shutil.copytree(_BUNDLED_MODEL, target)
            return target

    if _BUNDLED_MODEL.is_dir() and _is_ascii_path(str(_BUNDLED_MODEL)):
        return _BUNDLED_MODEL

    raise FileNotFoundError(
        f"Vosk 模型不可用: {_BUNDLED_MODEL}\n"
        "Vosk 不支持含中文的路径，请把模型放到纯英文目录并用 VOSK_MODEL_DIR 指定"
    )


def _load_model():
    global _model
    if _model is None:
        import vosk

        _model = vosk.Model(str(_resolve_model_path()))
    return _model


def _record_thread():
    """后台持续收音，存入缓冲区"""
    global _recording, _audio_buffer, _record_error
    p = None
    stream = None
    try:
        import pyaudio

        p = pyaudio.PyAudio()
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=4096,
        )
        stream.start_stream()
        while _recording:
            _audio_buffer.append(stream.read(4096, exception_on_overflow=False))
    except Exception as exc:
        _record_error = str(exc)
        _recording = False
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        if p is not None:
            p.terminate()


def start_listening():
    """开始收音"""
    global _recording, _audio_buffer, _record_error, _record_thread_handle
    _recording = True
    _audio_buffer = []
    _record_error = None
    _record_thread_handle = threading.Thread(target=_record_thread, daemon=True)
    _record_thread_handle.start()


def cancel_listening():
    """停止收音，不执行语音识别"""
    global _recording, _record_thread_handle
    _recording = False
    if _record_thread_handle is not None:
        _record_thread_handle.join(timeout=2)
        _record_thread_handle = None


def _pcm_to_wav(chunks) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"".join(chunks))
    return buf.getvalue()


def _recognize_remote(chunks):
    """调用本机 FunASR 服务。返回 None 表示服务不可用，需要回落 Vosk"""
    import requests

    try:
        resp = requests.post(f"{ASR_API_URL}/asr", data=_pcm_to_wav(chunks), timeout=30)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json().get("text", "")
    except Exception:
        return None


def stop_and_recognize() -> str:
    """停止收音并识别"""
    cancel_listening()

    if _record_error:
        return f"语音输入初始化失败：{_record_error}"

    if not _audio_buffer:
        return "未检测到语音，请重试"

    chunks = list(_audio_buffer)

    # 优先 FunASR：识别质量明显好于 Vosk 小模型，而且能带标点
    remote_text = _recognize_remote(chunks)
    if remote_text is not None:
        text = remote_text.strip()
        print(f"[语音输入] FunASR 识别结果：{text}")
        return text if text else "未检测到语音，请重试"

    # 服务没起 / 还在加载模型时回落到 Vosk
    model = _load_model()

    import vosk

    recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    for chunk in chunks:
        recognizer.AcceptWaveform(chunk)
    result = json.loads(recognizer.FinalResult())
    text = result.get("text", "").strip().replace(" ", "")
    print(f"[语音输入] 识别结果：{text}")
    return text if text else "未检测到语音，请重试"


def voice_input_async(callback):
    def task():
        try:
            result = stop_and_recognize()
        except Exception as exc:
            result = f"语音识别失败：{exc}"
        callback(result)

    threading.Thread(target=task, daemon=True).start()
