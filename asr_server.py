"""
本地中文语音识别服务（FunASR paraformer-large）。

必须用 GPT-SoVITS 自带的 runtime python 运行，因为 funasr 装在那个环境里：
    runtime\\python.exe asr_server.py

接口：
    GET  /health   -> {"ready": true/false, "error": "..."}
    POST /asr      -> 请求体是 16k 单声道 16bit 的 WAV 字节，返回 {"text": "..."}

模型在启动时后台加载，/health 立刻可用；没加载完时 /asr 返回 503，
调用方（voice_input.py）会自动回落到 Vosk。
"""

import io
import json
import os
import sys
import tempfile
import threading
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Python 3.12 移除了 distutils，而 funasr 依赖它；
# setuptools 会补一个兼容层，所以必须在 import funasr 之前导入
import setuptools  # noqa: F401

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TTS_ROOT = os.getenv("GPT_SOVITS_DIR") or os.path.abspath(
    os.path.join(
        APP_DIR,
        "..",
        "..",
        "GPT-SoVITS-v5-20261005",
        "GPT-SoVITS-v2pro-20261006",
    )
)
DEFAULT_MODEL_BASE = os.path.join(DEFAULT_TTS_ROOT, "tools", "asr", "models")
MODEL_BASE = os.getenv("ASR_MODEL_BASE", DEFAULT_MODEL_BASE)
HOST = os.getenv("ASR_HOST", "127.0.0.1")
PORT = int(os.getenv("ASR_PORT", "9881"))
SAMPLE_RATE = 16000

_state = {"model": None, "ready": False, "error": None}
_lock = threading.Lock()


def _log(*args):
    print(*args, file=sys.stderr, flush=True)


def _load_model():
    try:
        from funasr import AutoModel

        asr_dir = os.path.join(
            MODEL_BASE, "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        )
        punc_dir = os.path.join(
            MODEL_BASE, "punc_ct-transformer_zh-cn-common-vocab272727-pytorch"
        )
        kwargs = {
            "model": asr_dir,
            "device": "cpu",
            "disable_update": True,
        }
        if os.path.isdir(punc_dir):
            kwargs["punc_model"] = punc_dir
        _log(f"[ASR] 加载模型: {asr_dir}")
        model = AutoModel(**kwargs)
        with _lock:
            _state["model"] = model
            _state["ready"] = True
        _log("[ASR] 模型就绪")
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _state["error"] = f"{exc}"
        _log(f"[ASR] 模型加载失败: {exc}")
        traceback.print_exc()


def _wav_to_array(data: bytes):
    """把 WAV 字节转成 funasr 需要的 float32 numpy 数组"""
    import numpy as np

    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        width = wf.getsampwidth()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if width != 2:
        raise ValueError(f"只支持 16bit PCM，收到 {width * 8}bit")
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE:
        raise ValueError(f"只支持 {SAMPLE_RATE}Hz，收到 {rate}Hz")
    return audio


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静音默认访问日志
        pass

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.rstrip("/") in ("/health", "/"):
            with _lock:
                self._json(
                    200,
                    {
                        "ready": _state["ready"],
                        "error": _state["error"],
                    },
                )
        else:
            self._json(404, {"message": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path.rstrip("/") != "/asr":
            self._json(404, {"message": "not found"})
            return
        with _lock:
            ready = _state["ready"]
            model = _state["model"]
            err = _state["error"]
        if not ready:
            self._json(503, {"message": "model loading" if not err else f"model failed: {err}"})
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json(400, {"message": "empty body"})
            return
        data = self.rfile.read(length)

        tmp_path = None
        try:
            audio = _wav_to_array(data)
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp_path = tmp.name
            tmp.close()
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes((audio * 32768.0).astype("int16").tobytes())
            result = model.generate(input=tmp_path, batch_size_s=300)
            text = result[0]["text"] if result else ""
            self._json(200, {"text": text})
        except Exception as exc:  # noqa: BLE001
            _log(f"[ASR] 识别失败: {exc}")
            traceback.print_exc()
            self._json(500, {"message": str(exc)})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def main():
    threading.Thread(target=_load_model, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    _log(f"[ASR] 监听 http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
