import sys
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
import requests
import uuid
import threading
import re
import base64
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path
from functools import lru_cache

TTS_SESSION = requests.Session()
MODEL_NAME = "facebook/m2m100_418M"
PROJECT_DIR = Path(__file__).resolve().parent.parent
from dotenv import load_dotenv

load_dotenv(PROJECT_DIR / "config.env")


TTS_API_URL = os.getenv("TTS_API_URL", "http://127.0.0.1:9880").rstrip("/")


def _resolve(value: str) -> str:
    """配置里的相对路径按项目目录解析，整个文件夹换位置也不用改配置"""
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    return str(path)


REF_AUDIO = _resolve(os.getenv("TTS_REF_AUDIO_PATH", ""))
TTS_FFMPEG_PATH = _resolve(os.getenv("TTS_FFMPEG_PATH", ""))
PROMPT_TEXT = os.getenv("TTS_PROMPT_TEXT", "")
PROMPT_LANG = os.getenv("TTS_PROMPT_LANG", "ja")
OUTPUT_DIR = Path(os.getenv("TTS_OUTPUT_DIR", "./tts_output"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = PROJECT_DIR / OUTPUT_DIR
OUTPUT_DIR = str(OUTPUT_DIR)
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", "180"))
# 中日翻译模型（m2m100-418M）跑在 CPU 上，线程数不设限会瞬间吃满所有核心，
# 这里默认限制到 4 个线程，翻译慢一点但整机不卡、不狂转风扇
TTS_TORCH_THREADS = int(os.getenv("TTS_TORCH_THREADS", "4"))
# 每次最多朗读几句：句子越少，CPU 合成时间越短（0 表示不限制，整段都读）
TTS_MAX_SENTENCES = int(os.getenv("TTS_MAX_SENTENCES", "0"))
# 逐句响度统一：一句话一个请求，模型每次出来的电平能差 6~8 dB，
# 连续播放就会忽高忽低。这里把每句都拉到同一个响度（EBU R128）
def _env_float(name: str, default: float) -> float:
    """配置里写了非法值时不崩，退回默认值并尽量留一句提示"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        try:
            if sys.stderr is not None:
                print(f"[TTS] 配置 {name}={raw!r} 不是数字，改用默认值 {default}", file=sys.stderr, flush=True)
        except Exception:
            pass
        return default


TTS_TARGET_LUFS = _env_float("TTS_TARGET_LUFS", -20.0)
TTS_TRUE_PEAK = _env_float("TTS_TRUE_PEAK", -1.5)
# 语速：1.0 = 模型原始速度，越大越快。GPT-SoVITS 支持 0.5 ~ 2.0，超出会自动夹回
TTS_SPEED_FACTOR = max(0.5, min(2.0, _env_float("TTS_SPEED_FACTOR", 1.15)))
os.makedirs(OUTPUT_DIR, exist_ok=True)

tokenizer = None
model = None
DEVICE = None


def _load_translation_model():
    global tokenizer, model, DEVICE
    if tokenizer is None or model is None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, M2M100Tokenizer

        if TTS_TORCH_THREADS > 0:
            torch.set_num_threads(TTS_TORCH_THREADS)
        DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        tokenizer = M2M100Tokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            MODEL_NAME,
            torch_dtype=torch.float16 if DEVICE == "cuda" else torch.float32,
            device_map="auto" if DEVICE == "cuda" else None,
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
        )
        if DEVICE == "cpu":
            model.to(DEVICE)
        model.eval()
    import torch
    return tokenizer, model, DEVICE, torch


# ===== 线程锁（日志防乱序） =====
_stderr_lock = threading.Lock()
_ffmpeg_lock = threading.Lock()


def _log(*args):
    with _stderr_lock:
        print(*args, file=sys.stderr, flush=True)


def _run_ffmpeg(cmd, **kwargs):
    """Serialize ffmpeg startup and retry the intermittent Windows DLL init failure once."""
    with _ffmpeg_lock:
        proc = subprocess.run(cmd, **kwargs)
        if proc.returncode & 0xFFFFFFFF == 0xC0000142:
            time.sleep(0.2)
            proc = subprocess.run(cmd, **kwargs)
        return proc


def check_api():
    try:
        requests.get(f"{TTS_API_URL}/", timeout=3)
        print(f"[TTS] API 连接正常 -> {TTS_API_URL}")
        return True
    except Exception:
        print(f"[TTS] 无法连接 {TTS_API_URL}")
        return False

# ===== 中日翻译模型 =====
@lru_cache(maxsize=1500)
def local_zh2ja(text: str) -> str:
    if not text.strip():
        return ""
    tokenizer, model, device, torch = _load_translation_model()
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512).to(device)
    forced_bos_token_id = tokenizer.get_lang_id("ja")
    with torch.inference_mode():
        outputs = model.generate(
            **inputs,
            forced_bos_token_id=forced_bos_token_id,
            max_new_tokens=200,
            num_beams=2,
            repetition_penalty=1.2,
            early_stopping=True,
            use_cache=True
        )
    ja_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
    ja_text = re.sub(r'\s+', ' ', ja_text).strip()
    ja_text = ja_text.replace("先生", "おきゃくさま")
    ja_text = ja_text.replace("センセイ", "おきゃくさま")
    ja_text = ja_text.replace("ゲスト", "おきゃくさま")
    ja_text = ja_text.replace("大佐", "少佐")
    return ja_text

def _split_sentences(text: str) -> list:
    parts = re.split(r'(?<=[。！？])', text)
    return [p.strip() for p in parts if p.strip()]

def _translate_zh_to_ja(raw_text: str):
    raw_text_fix = raw_text
    try:
        raw_text_fix = raw_text_fix.replace("少佐", "少佐（しょうさ）")
        raw_text_fix = raw_text_fix.replace("自动手记人偶", "自動手記人形")

        parts = _split_sentences(raw_text_fix)
        if len(parts) <= 1:
            translated = local_zh2ja(raw_text_fix)
        else:
            translated = "".join(local_zh2ja(p) for p in parts)
        translated = re.sub(r"[.…・、。！？\s]+$","",translated)
        sentence_list = [s.strip() for s in _split_sentences(translated) if len(s.strip())>3]
        return translated, "ja"
    except Exception as e:
        _log(f"[TTS翻译失败，降级为中文] {e}")
        return raw_text, "zh"


CACHE_DIR = os.path.join(OUTPUT_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# 缓存键里带上版本号：改动响度处理方式后旧缓存自然失效，不会被误用
CACHE_VERSION = "loudnorm1"

def _tts_cache_path(text: str, lang: str) -> str:
    # 语速也进缓存键：改了 TTS_SPEED_FACTOR 之后不会拿到旧速度的音频
    key = hashlib.md5(
        f"{text}|{lang}|{PROMPT_TEXT}|{REF_AUDIO}|{CACHE_VERSION}|{TTS_SPEED_FACTOR:.2f}".encode()
    ).hexdigest()
    return os.path.join(CACHE_DIR, f"{key}.wav")


def _ffmpeg_exe() -> str:
    """优先用 config.env 指定的 ffmpeg，其次 PATH 里的；都找不到就返回空串"""
    for candidate in (TTS_FFMPEG_PATH, shutil.which("ffmpeg") or ""):
        if candidate and os.path.isfile(candidate):
            return candidate
    return ""


def _measure_loudness(path: str):
    """用 EBU R128 量一遍，返回 (integrated_lufs, true_peak_db)；量不出来返回 (None, None)"""
    ffmpeg = _ffmpeg_exe()
    if not ffmpeg:
        return None, None
    cmd = [
        ffmpeg, "-hide_banner", "-nostats", "-i", path,
        "-af", "loudnorm=I=-16:TP=-1.5:print_format=json",
        "-f", "null", "-",
    ]
    try:
        proc = _run_ffmpeg(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
    except Exception as e:
        _log(f"[TTS响度测量失败] {e}")
        return None, None
    match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', proc.stderr or "", re.S)
    if not match:
        return None, None
    try:
        data = json.loads(match.group(0))
        return float(data["input_i"]), float(data["input_tp"])
    except Exception:
        return None, None


def normalize_loudness(path: str):
    """
    把单句音频统一到 TTS_TARGET_LUFS。
    只做整体增益（不做动态压缩），所以不会把句子内部的高低起伏压平。
    返回 None 表示这段基本是静音/失败片段，应当丢弃。
    """
    if not path or not os.path.exists(path):
        return None
    lufs, peak = _measure_loudness(path)
    if lufs is None:
        if not _ffmpeg_exe():
            _log("[TTS响度统一已跳过] 未找到 ffmpeg，可在 config.env 设置 TTS_FFMPEG_PATH")
        return path
    # 数字静音：放大只会得到底噪，直接当失败处理
    if lufs < -50:
        _log(f"[TTS丢弃静音片段] {os.path.basename(path)} 响度 {lufs:.1f} LUFS")
        return None
    gain = TTS_TARGET_LUFS - lufs
    # 别让增益把峰值顶过 -1.5 dBTP
    if peak is not None and peak + gain > TTS_TRUE_PEAK:
        gain = TTS_TRUE_PEAK - peak
    if abs(gain) < 0.3:
        return path
    ffmpeg = _ffmpeg_exe()
    tmp = path + ".norm.wav"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", path,
        "-af", f"volume={gain:.2f}dB", "-c:a", "pcm_s16le", tmp,
    ]
    try:
        proc = _run_ffmpeg(cmd, capture_output=True, timeout=60)
        if proc.returncode:
            status = proc.returncode & 0xFFFFFFFF
            stderr = proc.stderr or b""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            detail = f"exit={proc.returncode} (0x{status:08X})"
            if stderr.strip():
                detail += f"; ffmpeg: {stderr.strip()[-1000:]}"
            if status == 0xC0000142:
                detail += "; Windows DLL initialization failed"
            _log(f"[TTS响度统一失败] {os.path.basename(path)}: {detail}")
        else:
            os.replace(tmp, path)
    except Exception as e:
        _log(f"[TTS响度统一失败] {os.path.basename(path)}: {e}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
    return path

def synthesize(text: str, lang: str) -> str | None:
    cached = _tts_cache_path(text, lang)
    if os.path.exists(cached):
        _log(f"[TTS缓存命中] {text[:10]}...")
        return cached
    save_path = os.path.join(OUTPUT_DIR, f"{uuid.uuid4().hex[:8]}.wav")
    payload = {
        "text": text,
        "text_lang": lang,
        "ref_audio_path": REF_AUDIO,
        "prompt_text": PROMPT_TEXT,
        "prompt_lang": PROMPT_LANG,
        "top_k": 10,
        "top_p": 0.7,
        "temperature": 0.6,
        "text_split_method": "cut2",
        "speed_factor": TTS_SPEED_FACTOR,
        "media_type": "wav",
    }
    try:
        resp = TTS_SESSION.post(f"{TTS_API_URL}/tts", json=payload, timeout=TTS_TIMEOUT)
        if resp.status_code == 200:
            ct = resp.headers.get("Content-Type", "")

            def _store_audio(raw: bytes):
                # 先落盘，再统一响度，最后才写缓存：缓存里永远只有处理好的音频
                with open(save_path, "wb") as f:
                    f.write(raw)
                if normalize_loudness(save_path) is None:
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                    return None
                shutil.copyfile(save_path, cached)
                return save_path

            if "audio" in ct or "octet-stream" in ct or len(resp.content) > 500:
                result = _store_audio(resp.content)
                if result is not None:
                    _log(f"[TTS生成新音频] {text[:10]}...")
                return result
            try:
                data = resp.json()
                b64 = data.get("audio") or data.get("data")
                if b64:
                    result = _store_audio(base64.b64decode(b64))
                    if result is not None:
                        return result
            except Exception:
                pass
            # 200 但既不是音频、也没有 base64 音频字段，同样需要留下线索
            _log(
                f"[TTS返回内容异常] status=200 content-type={ct or '空'} "
                f"长度={len(resp.content)} 响应={resp.text[:200]}"
            )
        else:
            # 非 200 时 GPT-SoVITS 会用 JSON 说明原因（例如参考音频不存在、
            # 参考音频不在 3~10 秒范围内），这里必须打出来，否则只会看到
            # “所有音频合成失败”，完全无法定位
            _log(f"[TTS接口错误] status={resp.status_code} 响应={resp.text[:300]}")
    except Exception as e:
        _log(f"[TTS合成异常 {text[:10]}: {e}")
    return None


def play_audio(file_path: str):
    if not file_path or not os.path.exists(file_path):
        return
    try:
        from playsound3 import playsound

        playsound(file_path)
        return
    except Exception:
        pass
    try:
        from playsound import playsound

        playsound(file_path)
        return
    except Exception:
        pass
    try:
        import winsound

        winsound.PlaySound(file_path, winsound.SND_FILENAME | winsound.SND_SYNC)
    except Exception:
        pass

def translate_for_tts(text: str, target_lang: str):
    
    if target_lang == "ja" and not any('\u3040' <= c <= '\u30ff' for c in text):
        ja_text, lang = _translate_zh_to_ja(text)
        _log(f"[TTS翻译] {ja_text[:60]}...")
        return ja_text, lang
    return text, target_lang

# 全局互斥锁，放在文件靠前位置（不要写在函数里面）
_IS_PLAYING = False


def speak(text: str, lang: str = "zh", on_play=None, on_audio_finish=None):
    global _IS_PLAYING
    # 如果正在播放，直接忽略新语音，同时执行回调防止UI卡死
    if _IS_PLAYING:
        _log("[TTS] 忙，忽略本次语音请求")
        if on_audio_finish:
            on_audio_finish()
        return

    def _run_task():
        global _IS_PLAYING
        _IS_PLAYING = True
        try:
            # 参考音频缺失时 GPT-SoVITS 必然对每个分句返回 400，且翻译本身很吃 CPU，
            # 这里提前拦住并给出可操作的提示，不再白跑一遍翻译
            if not REF_AUDIO or not os.path.exists(REF_AUDIO):
                _log(f"[TTS] 参考音频不存在: {REF_AUDIO or '(未配置 TTS_REF_AUDIO_PATH)'}")
                _log("[TTS] 请把参考音频放回该路径，或修改 config.env 里的 TTS_REF_AUDIO_PATH（3~10 秒人声）")
                return
            # 翻译处理
            target_text, actual_lang = translate_for_tts(text, lang)
            sentence_list = [s.strip() for s in _split_sentences(target_text) if len(s.strip())>3]
            if not sentence_list:
                _log("[TTS]过滤之后没有有效句子，跳过合成")
                return
            if TTS_MAX_SENTENCES > 0 and len(sentence_list) > TTS_MAX_SENTENCES:
                _log(f"[TTS]只朗读前 {TTS_MAX_SENTENCES} 句（共 {len(sentence_list)} 句）")
                sentence_list = sentence_list[:TTS_MAX_SENTENCES]
            audio_order = [None] * len(sentence_list)

            def _synthesize_segment(index, segment):
                try:
                    audio_order[index] = synthesize(segment, actual_lang)
                except Exception as exc:  # noqa: BLE001
                    _log(f"[TTS片段合成异常] {exc}")

            for start in range(0, len(sentence_list), 2):
                workers = [
                    threading.Thread(
                        target=_synthesize_segment,
                        args=(idx, sentence_list[idx]),
                        daemon=True,
                    )
                    for idx in range(start, min(start + 2, len(sentence_list)))
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()

            audio_list = [p for p in audio_order if p is not None]
            if not audio_list:
                _log("[TTS] 所有音频合成失败")
                return
            # 触发立绘说话动画
            if on_play is not None:
                on_play()
            # 连贯顺序播放，一段播完才下一段，增加异常捕获
            for audio_path in audio_list:
                try:
                    play_audio(audio_path)
                except Exception as e:
                    _log(f"[TTS片段播放异常] {e}")
            _log("[TTS] 全部音频播放完成")
        finally:
            # 无论成功/报错，一定释放锁，执行结束回调切回待机立绘
            _IS_PLAYING = False
            if on_audio_finish is not None:
                on_audio_finish()

    # 后台守护线程运行，不阻塞UI
    threading.Thread(target=_run_task, daemon=True).start()

def clear_history_audio():
    if not os.path.isdir(OUTPUT_DIR):
        return
    all_files = os.listdir(OUTPUT_DIR)
    for fname in all_files:
        full_path = os.path.join(OUTPUT_DIR, fname)
        # 跳过缓存文件夹，永久音频不删除
        if os.path.isdir(full_path) and fname == "cache":
            continue
        if os.path.isfile(full_path) and full_path.endswith(".wav"):
            try:
                os.remove(full_path)
            except Exception as err:
                _log(f"[TTS清理临时音频失败 {fname}: {err}")
    _log("[TTS启动清理：临时音频已删除，持久缓存保留")
