# Violet — AI Desktop Mascot

A PyQt6 desktop companion themed after *Violet Evergarden*, featuring LLM chat,
local bilingual TTS, offline speech input, and live-info crawlers
(weather / trending / FX / gold).

> This is a personal study fork of [moreandice](https://github.com/moreandice)'s
> Violet desktop mascot project, with my own modifications and practice.
> Original copyright belongs to moreandice; the original MIT license and
> copyright notice are retained (see [LICENSE](LICENSE)). My modifications are
> also released under the MIT License.

---

## ⚠️ Before you start

1. This repository does **not** include character artwork, reference audio, or
   local models. Prepare them yourself and make sure you have the rights to use
   and redistribute them.
2. Released under the MIT License — free to use, modify and distribute; keep the
   copyright notice and comply with the license.
3. API keys, local models and TTS services must be configured by you. Never
   commit a `config.env` containing real keys or personal paths.
4. No prebuilt environment, packaged exe or portable bundle is provided. Users
   deploy the Python environment, dependencies and services (GPT-SoVITS / Vosk)
   themselves.

---

## Requirements

- Python >= 3.10 (3.11 / 3.12 recommended for PyAudio / PyTorch compatibility)
- Windows 10/11

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If `pyaudio` fails to build:

```bash
pip install pipwin
pipwin install pyaudio
```

## Configuration

Minimum viable setup is steps 1–3 (chat only). Add 4–5 for voice.

### 1. Create the config file

```powershell
Copy-Item config.env.example config.env
```

`config.env` is git-ignored, so your key never gets committed.

### 2. LLM (required)

1. Open the [Volcengine Ark console](https://console.volcengine.com/ark) →
   **API Key management** → create and copy a key.
2. Under **Online inference**, activate a Doubao model and create an endpoint;
   copy the **endpoint ID** (`ep-2024xxxx-xxxxx`).
3. Edit `config.env`:

```env
ARK_API_KEY = "your API key"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
LLM_MODEL_NAME = "ep-2024xxxx-xxxxx"
TEMPERATURE = 0.7
MAX_TOKENS = 600
LLM_THINKING = off
```

| Variable | Required | Notes |
|---|---|---|
| `ARK_API_KEY` | ✅ | Ark API key; rotate it if leaked |
| `API_URL` | ✅ | Any OpenAI-compatible `chat/completions` endpoint |
| `LLM_MODEL_NAME` | ✅ | Endpoint ID or model ID |
| `TEMPERATURE` | | 0–1; lower = steadier, ~0.7 for role-play |
| `MAX_TOKENS` | | Thinking + reply budget; too small truncates answers |
| `LLM_THINKING` | | `off` / `on` / `auto`; `off` recommended |

### 3. Verify

```powershell
python main.py
```

Send "hello"; a reply means the LLM works.

### 4. TTS (optional)

Set `ENABLE_TTS = false` to skip. Otherwise:

1. Install GPT-SoVITS v2 and make sure `api_v2.bat` starts.
2. Prepare a clean 3–10 s reference `.wav`.
3. `TTS_PROMPT_TEXT` must be the **exact transcript** of that clip;
   set `TTS_PROMPT_LANG` (`zh` / `ja` / `en`).
4. Start the app — it launches the 9880 service automatically.

```env
ENABLE_TTS = true
TTS_API_URL = http://127.0.0.1:9880
TTS_REF_AUDIO_PATH = "D:\voices\violet_ref.wav"
TTS_PROMPT_TEXT = 自動手記人形サービスバイオレットエヴァーガーデンです
TTS_PROMPT_LANG = ja
TTS_BAT_PATH = D:\GPT-SoVITS\api_v2.bat
TTS_TIMEOUT = 180
TTS_SPEED_FACTOR = 1.15
```

### 5. ASR (optional)

Place the Vosk model at `vosk-model\vosk-model-small-cn-0.22\`. Without it,
voice input silently does nothing.

### 6. Persona (optional)

`prompt.txt` is the character persona — tweak lightly, don't rewrite the rules.

### Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` | bad/expired key | re-copy `ARK_API_KEY`, no quotes or trailing spaces |
| `404 model not found` | wrong endpoint/model ID | use the `ep-` endpoint ID from the console |
| Replies cut in half | `MAX_TOKENS` too small | raise to 600–1000, or `LLM_THINKING=off` |
| No audio, 9880 connection errors | GPT-SoVITS not running | start `api_v2.bat`, check `http://127.0.0.1:9880/docs` |
| Robotic/garbled voice | prompt text ≠ reference audio | make them match exactly; 3–10 s clean clip |
| Space does nothing | Vosk model missing | check the `vosk-model\...` path |

You can also configure everything in-app: ☰ → **Settings…**; saving writes back
to `config.env`.

## Resources you must provide

| Resource | Where | Notes |
|---|---|---|
| Character sprites (8 PNGs) | `static/prep_png/` | idle / speak / think / sleep, normal & sick |
| Vosk offline ASR model | `vosk-model/` | `vosk-model-small-cn-0.22` |
| GPT-SoVITS v2 | local install | set `TTS_BAT_PATH` to `api_v2.bat` |
| m2m100 translation model | auto-download | only needed for reading Chinese answers in Japanese |

## Features

- **Persona chat** — Violet-style gentle, short replies; real-time weather /
  trending / FX / gold lookups when relevant.
- **Weather-aware persona** — background weather polling every 18 min; switches
  to a "sick" sprite when it rains.
- **Info crawlers** — Bilibili trending top 5, USD/JPY rates, Shanghai Au9999
  spot gold, with 18-min cooldown and 3 s global request spacing.
- **Local bilingual TTS** — `/zh` / `/ja`; sentence-splitting to avoid 60 s
  timeouts; no cloud TTS fees.
- **Offline voice input** — hold Space to talk, release to transcribe, Esc to
  cancel; fully local.
- **Camera vision input** — off by default; face + mouth-motion heuristics, all
  processed on-device, nothing saved or uploaded.
- **Bionic memory** — short-term impressions + explicit long-term memories
  stored in `data/long_term_memory.json` (git-ignored).

## Commands

| Command | Effect |
|---|---|
| `/zh` | Read replies in Chinese |
| `/ja` | Read replies in Japanese |
| `/记住情感 <text>` | Save an emotional memory |
| `/记住事实 <text>` | Save a factual memory |
| `/遗忘 <keyword>` | Forget matching long-term memories |
| `/污染 <text>` | Inject a temporary impression |
| `/清空短期` | Clear short-term context |
| 再见 | Sleep (keep window) |
| 退出 / window × | Quit and stop services started by this run |
| hold Space | Voice input |

## License

MIT License. Original work © 2026 moreandice. See [LICENSE](LICENSE).
