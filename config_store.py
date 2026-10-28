"""读写 config.env：只改指定键，保留注释和其它配置。"""

import re
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return app_dir() / "config.env"


def read_config(path: Path = None) -> dict:
    """把 config.env 读成 dict（不污染 os.environ，供自检/界面回显用）"""
    path = Path(path) if path else config_path()
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _format_value(value: str) -> str:
    """带空格 / 井号的值要加引号，否则会被 dotenv 截断"""
    if value != value.strip() or any(ch in value for ch in ' #"\''):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def update_config(updates: dict, path: Path = None) -> Path:
    """按行替换键值；文件里没有的键追加到末尾。注释与顺序保持不变。"""
    path = Path(path) if path else config_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out = []
    seen = set()
    for line in lines:
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if match and match.group(1) in updates:
            key = match.group(1)
            out.append(f"{key}={_format_value(str(updates[key]))}")
            seen.add(key)
        else:
            out.append(line)

    missing = [k for k in updates if k not in seen]
    if missing:
        if out and out[-1].strip():
            out.append("")
        out.extend(f"{k}={_format_value(str(updates[k]))}" for k in missing)

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return path
