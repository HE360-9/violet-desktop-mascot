import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from crawler import search

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / "config.env")
API_KEY = os.getenv("ARK_API_KEY")
API_URL = os.getenv("API_URL")
MODEL_NAME = os.getenv("LLM_MODEL_NAME")
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", 150))

# 这个模型带“思考”过程（响应里的 reasoning_content），而 max_tokens 是
# 思考 + 正文的合计额度：思考就能把额度吃光，正文直接空掉或只剩半句。
# 角色闲聊不需要推理过程，默认关掉；填 auto 则不干预，填 on 显式要求思考。
LLM_THINKING = os.getenv("LLM_THINKING", "off").strip().lower()

# 最近一次调用的结束原因：正常是 "stop"，被长度上限截断则是 "length"。
# 上层据此提示用户，避免回答莫名其妙断在半句话上还找不到原因。
LAST_FINISH_REASON = None


def llm(
    user_input: str,
    system_prompt: str,
    history: list = None,
    memory_context: str = "",
) -> tuple[str, list]:
    global LAST_FINISH_REASON
    LAST_FINISH_REASON = None
    if history is None:
        history = []
    if len(history) > 8:
        history = history[-8:]

    if not API_KEY:
        return "API调用失败:请先在 config.env 中配置 ARK_API_KEY", history
    if not API_URL or not MODEL_NAME:
        return "API调用失败:请在 config.env 中配置 API_URL 和 LLM_MODEL_NAME", history

    realtime_data = search(user_input)
    if not realtime_data.startswith("无时效性实时资讯"):
        raw_prompt = f"""
用户提问：{user_input}
---实时网络资讯---
{realtime_data}
回答要求：以薇尔莉特温柔、文雅、细腻的语气回复，优先参考上方资料，资料不足依靠自身知识正常回答。
"""
        full_user_msg = raw_prompt[:1600]
    else:
        full_user_msg = user_input

    if memory_context.strip():
        # Memory stays user-scoped so it can inform, but never redefine, the fixed persona.
        full_user_msg = f"{full_user_msg}\n\n{memory_context}"

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": full_user_msg},
    ]
    post_json = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    if LLM_THINKING in ("off", "disabled", "false", "0"):
        post_json["thinking"] = {"type": "disabled"}
    elif LLM_THINKING in ("on", "enabled", "true", "1"):
        post_json["thinking"] = {"type": "enabled"}

    try:
        response = requests.post(
            url=API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}",
            },
            json=post_json,
            timeout=45,
        )
        response.raise_for_status()
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
        LAST_FINISH_REASON = result["choices"][0].get("finish_reason")
        history.extend([
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": answer},
        ])
        history[:] = history[-8:]
    except requests.HTTPError as err:
        response = err.response
        if response is not None:
            details = response.text.strip()[:1000]
            return f"API调用失败:HTTP {response.status_code}: {details}", history
        return f"API调用失败:{err}", history
    except Exception as err:
        return f"API调用失败:{err}", history

    return answer, history
