"""Violet 启动器：双击即用，无控制台黑框。

做的事情和 start-violet.ps1 一样：
  1. 需要时后台拉起 GPT-SoVITS（语音合成，9880）
  2. 需要时后台拉起 FunASR（语音识别，9881）
  3. 启动桌面应用（venv 里的 pythonw.exe main.py）
  4. 应用退出后，停掉本启动器拉起的服务

打包成 exe 后只做「引导」，不把应用本体冻进去——应用要 import torch/transformers
做中日翻译，一起打包会有 2 GB 以上，得不偿失。
"""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from process_utils import stop_process_tree

TEMP_LOG_DIR = Path(os.environ.get("TEMP", ".")) / "violet"
CREATE_NO_WINDOW = 0x08000000

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
WORKSPACE_DIR = APP_DIR.parent
REPO_DIR = WORKSPACE_DIR.parent
CONFIG_PATH = APP_DIR / "config.env"

TTS_ROOT = REPO_DIR / "GPT-SoVITS-v5-20261005" / "GPT-SoVITS-v2pro-20261006"
APP_PYTHON = WORKSPACE_DIR / ".venv" / "Scripts" / "pythonw.exe"


def _tts_root() -> Path:
    """优先用 config.env 里的 GPT_SOVITS_DIR（相对路径按程序目录解析），
    其次找包内 GPT-SoVITS 目录，最后才回落到开发目录结构"""
    configured = os.environ.get("GPT_SOVITS_DIR", "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = APP_DIR / candidate
        if (candidate / "runtime" / "python.exe").exists():
            return candidate
    for candidate in (APP_DIR / "GPT-SoVITS", TTS_ROOT):
        if (candidate / "runtime" / "python.exe").exists():
            return candidate
    return Path(configured) if configured else TTS_ROOT


def _app_command():
    """返回 (解释器路径, 需要的额外环境变量)。

    便携包里是 python/ + site-packages/，开发目录里是 .venv，两种都支持。
    """
    bundled_python = APP_DIR / "python" / "pythonw.exe"
    bundled_site = APP_DIR / "site-packages"
    if bundled_python.exists() and bundled_site.is_dir():
        return str(bundled_python), {"PYTHONPATH": str(bundled_site)}

    venv_python = WORKSPACE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    return str(venv_python), {}


def _load_env():
    """读 config.env；打包后没有 python-dotenv 也可以，手写一个极简解析"""
    try:
        from dotenv import load_dotenv  # 源码运行时用官方实现
        load_dotenv(CONFIG_PATH)
        return
    except Exception:
        pass
    if not CONFIG_PATH.exists():
        return
    for raw in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _enabled(name: str) -> bool:
    return os.environ.get(name, "true").strip().lower() != "false"


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


def _start_service(args, cwd: Path, log_name: str):
    TEMP_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = TEMP_LOG_DIR / log_name
    log = open(log_path, "ab", buffering=0)
    log.write(f"\n\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} 启动 =====\n".encode("utf-8"))
    return subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
    )


def _wait_http(url: str, timeout: float, proc=None, tick=None) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        if _http_ok(url):
            return True
        if tick is not None:
            tick()
        time.sleep(1)
    return False


class Splash:
    """极简启动提示；没有 tkinter 时静默跳过"""

    def __init__(self, text: str):
        self.root = None
        try:
            import tkinter as tk

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg="#F7F4FB")
            w, h = 320, 96
            sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
            root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
            tk.Label(root, text="薇尔莉特", bg="#F7F4FB", fg="#4A3F6B",
                     font=("Microsoft YaHei UI", 13, "bold")).pack(pady=(16, 2))
            self.label = tk.Label(root, text=text, bg="#F7F4FB", fg="#8C81A6",
                                  font=("Microsoft YaHei UI", 9))
            self.label.pack()
            self.root = root
            self.pump()
        except Exception:
            self.root = None

    def set_text(self, text: str):
        if self.root is not None:
            try:
                self.label.config(text=text)
                self.pump()
            except Exception:
                pass

    def pump(self):
        if self.root is not None:
            try:
                self.root.update_idletasks()
                self.root.update()
            except Exception:
                self.root = None

    def close(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None


def main() -> int:
    _load_env()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    threads = os.environ.get("TTS_CPU_THREADS", "6")
    os.environ.setdefault("OMP_NUM_THREADS", threads)
    os.environ.setdefault("MKL_NUM_THREADS", threads)
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    # 路径要在读完 config.env 之后再算，这样换安装位置只改配置即可
    tts_root = _tts_root()
    tts_python = tts_root / "runtime" / "python.exe"
    asr_base = os.environ.get("ASR_MODEL_BASE", "").strip()
    if asr_base:
        asr_path = Path(asr_base)
        os.environ["ASR_MODEL_BASE"] = str(asr_path if asr_path.is_absolute() else (APP_DIR / asr_path))
    else:
        os.environ["ASR_MODEL_BASE"] = str(tts_root / "tools" / "asr" / "models")

    splash = Splash("正在准备语音服务…")
    started = []
    try:
        if _enabled("ENABLE_TTS") and tts_python.exists() and not _http_ok("http://127.0.0.1:9880/docs"):
            splash.set_text("正在启动语音合成…（首次约 15 秒）")
            started.append(_start_service(
                [str(tts_python), "-u", "api_v2.py"], tts_root, "gpt-sovits.log"))
            if not _wait_http("http://127.0.0.1:9880/docs", 180,
                              proc=started[-1], tick=splash.pump):
                splash.close()
                _message("语音合成服务启动失败，请查看日志：\n" + str(TEMP_LOG_DIR / "gpt-sovits.log"))
                return 1

        if _enabled("ENABLE_ASR") and (APP_DIR / "asr_server.py").exists() and not _http_ok("http://127.0.0.1:9881/health"):
            splash.set_text("正在启动语音识别…")
            started.append(_start_service(
                [str(tts_python), "-u", "asr_server.py"], APP_DIR, "asr.log"))

        splash.set_text("正在打开薇尔莉特…")
        app_python, extra_env = _app_command()
        if not Path(app_python).exists():
            splash.close()
            _message(f"找不到应用解释器：\n{app_python}")
            return 1

        app = subprocess.Popen(
            [app_python, "main.py"],
            cwd=str(APP_DIR),
            env={**os.environ, **extra_env},
        )
        # 应用起来了就收起启动提示，等它退出
        for _ in range(60):
            splash.pump()
            time.sleep(0.2)
        splash.close()
        return app.wait()
    finally:
        splash.close()
        for proc in started:
            stop_process_tree(proc)


def _message(text: str):
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("薇尔莉特", text)
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
