"""启动自检：把「配好了没、服务起没起」一次性查清楚。

结果是一组 {level, title, detail}：
    ok    —— 正常
    warn  —— 能用，但有降级（例如识别服务还在加载）
    error —— 会导致功能不可用（例如参考音频丢了、API Key 没填）
"""

import json
import os
import shutil
import urllib.request
from pathlib import Path

from config_store import app_dir, read_config

DEFAULT_REF_AUDIO_HINT = "在 config.env 或设置页里指向一段 3~10 秒的人声"


def _get(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read(4096)
    except Exception:
        return None, b""


def _repo_root() -> Path:
    return app_dir().parent.parent


def _default_tts_dir() -> Path:
    return _repo_root() / "GPT-SoVITS-v5-20261005" / "GPT-SoVITS-v2pro-20261006"


def _resolve(value: str) -> Path:
    """配置里的相对路径按程序目录解析"""
    path = Path(value)
    return path if path.is_absolute() else (app_dir() / path)


def check_environment() -> list:
    cfg = read_config()

    def value(key: str, default: str = "") -> str:
        raw = cfg.get(key)
        if raw is None or raw == "":
            raw = os.environ.get(key, default)
        return (raw or "").strip()

    items = []

    def add(level: str, title: str, detail: str = ""):
        items.append({"level": level, "title": title, "detail": detail})

    # ---------- 大模型 ----------
    key = value("ARK_API_KEY")
    url = value("API_URL")
    model = value("LLM_MODEL_NAME")
    if not key:
        add("error", "没有填写 API Key", "聊天窗 ☰ →「设置…」→ 模型，填完保存即可")
    if not url:
        add("error", "没有填写接口地址", "例如 https://ark.cn-beijing.volces.com/api/v3/chat/completions")
    if not model:
        add("error", "没有填写模型 ID", "填服务商给的模型名")
    if key and url and model:
        add("ok", "模型配置完整", f"{model}")

    # ---------- 语音合成 ----------
    tts_url = value("TTS_API_URL", "http://127.0.0.1:9880").rstrip("/")
    if value("ENABLE_TTS", "true").lower() == "false":
        add("warn", "语音合成已关闭", "config.env 里 ENABLE_TTS=false，只会打字不出声")
    else:
        status, _ = _get(tts_url + "/docs")
        if status == 200:
            add("ok", "语音合成服务在线", tts_url)
        else:
            add("error", "语音合成服务没有响应", f"{tts_url} —— 看 %TEMP%\\violet\\gpt-sovits.log")

    ref = value("TTS_REF_AUDIO_PATH")
    if not ref:
        add("error", "没有配置参考音频", DEFAULT_REF_AUDIO_HINT)
    elif not _resolve(ref).exists():
        add("error", "参考音频不存在", str(_resolve(ref)))
    else:
        add("ok", "参考音频存在", str(_resolve(ref)))

    ffmpeg = value("TTS_FFMPEG_PATH")
    ffmpeg_path = _resolve(ffmpeg) if ffmpeg else None
    if ffmpeg_path is not None and ffmpeg_path.exists():
        add("ok", "ffmpeg 可用", str(ffmpeg_path))
    elif shutil.which("ffmpeg"):
        add("ok", "ffmpeg 可用", shutil.which("ffmpeg"))
    else:
        add("warn", "找不到 ffmpeg", "逐句响度统一会被跳过，声音会忽大忽小")

    # ---------- 语音识别 ----------
    asr_url = value("ASR_API_URL", "http://127.0.0.1:9881").rstrip("/")
    if value("ENABLE_ASR", "true").lower() == "false":
        add("warn", "FunASR 已关闭", "config.env 里 ENABLE_ASR=false，语音输入会退回 Vosk 小模型")
    else:
        status, body = _get(asr_url + "/health")
        if status == 200:
            try:
                ready = json.loads(body.decode("utf-8")).get("ready")
            except Exception:
                ready = False
            if ready:
                add("ok", "语音识别服务就绪（FunASR）", asr_url)
            else:
                add("warn", "语音识别服务正在加载", "首次约 15 秒，期间按空格会先用 Vosk")
        else:
            add("warn", "语音识别服务没有响应", f"{asr_url} —— 会退回 Vosk 小模型")

    # ---------- 目录 / 模型 ----------
    tts_value = value("GPT_SOVITS_DIR")
    tts_dir = _resolve(tts_value) if tts_value else _default_tts_dir()
    runtime_py = tts_dir / "runtime" / "python.exe"
    if runtime_py.exists():
        add("ok", "GPT-SoVITS 目录正确", str(tts_dir))
    else:
        add("error", "GPT-SoVITS 目录不存在", f"{tts_dir}\n在设置页「语音」里改 GPT_SOVITS_DIR")

    asr_value = value("ASR_MODEL_BASE")
    asr_base = _resolve(asr_value) if asr_value else (tts_dir / "tools" / "asr" / "models")
    paraformer = asr_base / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    if paraformer.is_dir():
        add("ok", "FunASR 识别模型存在", str(asr_base))
    else:
        add("warn", "找不到 FunASR 识别模型", f"{paraformer}")

    vosk_env = value("VOSK_MODEL_DIR")
    vosk_candidates = [_resolve(vosk_env)] if vosk_env else []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        vosk_candidates.append(Path(local) / "violet" / "vosk-model-small-cn-0.22")
    vosk_candidates.append(app_dir() / "vosk-model" / "vosk-model-small-cn-0.22")
    vosk_hit = next((p for p in vosk_candidates if p.is_dir() and str(p).isascii()), None)
    if vosk_hit:
        add("ok", "Vosk 回退模型可用", str(vosk_hit))
    else:
        add("warn", "没有可用的 Vosk 模型", "FunASR 不可用时语音输入会没反应")

    return items
