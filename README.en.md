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

1. Copy `config.env.example` to `config.env`.
2. Fill in at least `ARK_API_KEY` (Volcengine Ark). For TTS, also set the
   GPT-SoVITS path, reference audio and timeout; otherwise keep `ENABLE_TTS=false`.
3. `prompt.txt` holds the character persona — tweak it lightly if you like.

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
