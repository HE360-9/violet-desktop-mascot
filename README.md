# Violet 薇尔莉特 AI 桌面人偶

[English](README.en.md) | 简体中文

> 项目主页：[he360-9.github.io/violet-desktop-mascot](https://he360-9.github.io/violet-desktop-mascot/) ·
> 更新日志：[CHANGELOG.md](CHANGELOG.md) · 打包说明：[docs/BUILD.md](docs/BUILD.md)

基于 PyQt6 开发的《紫罗兰永恒花园》主题桌面虚拟桌宠，实现 AI 对话、本地中日双语 TTS、离线语音输入、天气/热搜/汇率金价爬虫等完整功能。

---

## ⚠️ 重要前置说明

1. 仓库不包含角色立绘、参考音频和本地模型；请自行准备所需资源，并确认拥有相应使用和分发授权。
2. 本项目以 MIT License 发布，可自由使用、修改与分发；请保留原始版权声明，并遵守许可条款；
3. API 密钥、本地模型和语音服务均需自行配置。请勿提交包含密钥或个人路径的本地配置文件。
4. 本项目不提供预配置环境、打包好的 exe 或便携版；Python 环境、依赖与 GPT-SoVITS / Vosk 等服务由使用者自行部署。

---

## 来源与许可

本项目为个人学习复刻，基于 [moreandice](https://github.com/moreandice) 的 Violet 桌面人偶项目二次开发，
并在原作基础上做了自己的修改与练习。

- 原项目版权归 moreandice 所有，原始 MIT 许可与版权声明已完整保留，见 [LICENSE](LICENSE)；
- 本仓库的修改部分同样以 MIT License 发布；
- 本仓库不包含角色立绘、参考音频、Vosk 模型等资源，请自行准备并确认拥有相应授权。

---

## 一、环境要求

Python >= 3.10（建议使用 Python 3.11 或 3.12，以获得更好的 PyAudio / PyTorch 兼容性）

### Windows 安装与启动

在 PowerShell 中进入项目目录，创建独立环境并安装依赖：

```powershell
cd .\violet-desktop-mascot-main
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

若本机没有 `py` 命令，可用已安装的 Python 执行 `python -m venv .venv`。PowerShell 禁止脚本运行时，可先运行 `Set-ExecutionPolicy -Scope Process RemoteSigned`，或直接调用 `.venv\Scripts\python.exe` 安装和启动。

依赖清单（`requirements.txt`）：

```
PyQt6>=6.5.0
requests>=2.31.0
python-dotenv>=1.0.0
akshare>=1.10.0
torch>=2.0.0
transformers>=4.36.0
sentencepiece>=0.2.0
vosk>=0.3.45
pyaudio>=0.2.14
playsound3>=3.3.2
opencv-python-headless>=4.10.0.84,<5
```

### Windows pyaudio 安装失败备用方案

```bash
pip install pipwin
pipwin install pyaudio
```

---

## 二、必须自行准备资源（仓库不包含）

### 1. 角色图片 `static/prep_png`

需准备 8 张 PNG 图片：

| 文件名 | 用途 |
|--------|------|
| BgSub_站姿2.png | 正常待机立绘 |
| BgSub_speak.png | 正常说话立绘 |
| BgSub_think.png | 正常思考立绘 |
| BgSub_sleep.png | 正常休眠立绘 |
| BgSub_sick_idle.png | 下雨生病待机立绘 |
| BgSub_sick_speak.png | 生病说话立绘 |
| BgSub_sick_think.png | 生病思考立绘 |
| BgSub_sick_sleep.png | 生病休眠立绘 |

### 2. 离线语音识别模型

新建 `vosk-model` 文件夹，放入 `vosk-model-small-cn-0.22` 中文模型包。

### 3. GPT-SoVITS 语音服务

自行下载 GPT-SoVITS v2 程序，在配置文件填写 `api_v2.bat` 完整路径，用于本地音色合成。

### 4. 翻译模型 m2m100

仅在使用日语朗读中文回答时需要。

首次使用时从模型镜像自动下载；程序启动和中文朗读不需要预先加载它。

---

## 三、配置指南

> 最小可用 = 第 1～3 步（只聊天）。想要语音，再加第 4～5 步。

### 第 1 步：生成配置文件

```powershell
Copy-Item config.env.example config.env
```

`config.env` 已被 `.gitignore` 忽略，里面的 Key 不会被提交。

### 第 2 步：填大模型（必做）

1. 打开 [火山方舟控制台](https://console.volcengine.com/ark) →「API Key 管理」→ 创建并复制 Key；
2. 在「在线推理」里开通豆包系列模型、创建接入点，复制**接入点 ID**（形如 `ep-2024xxxx-xxxxx`）；
3. 编辑 `config.env`：

```env
ARK_API_KEY = "你的 API Key"
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
LLM_MODEL_NAME = "ep-2024xxxx-xxxxx"
TEMPERATURE = 0.7
MAX_TOKENS = 600
LLM_THINKING = off
```

| 变量 | 必填 | 说明 |
|---|---|---|
| `ARK_API_KEY` | ✅ | 火山方舟 API Key；一旦泄露请立即作废重建 |
| `API_URL` | ✅ | 兼容 OpenAI 格式的 `chat/completions` 地址 |
| `LLM_MODEL_NAME` | ✅ | 接入点 ID，或直接填模型 ID（如 `doubao-seed-2-0-lite-260428`） |
| `TEMPERATURE` | | 0～1，越低越稳定；角色闲聊 0.7 左右 |
| `MAX_TOKENS` | | 思考 + 正文合计上限，太小会把回答截断 |
| `LLM_THINKING` | | `off` / `on` / `auto`，闲聊建议 `off` |

> 换别的服务商？只要接口兼容 OpenAI 的 `chat/completions`，改 `API_URL` / `LLM_MODEL_NAME` / `ARK_API_KEY` 三项即可。

### 第 3 步：先跑起来验证

```powershell
python main.py
```

发一句「你好」，能正常回复就说明大模型通了。报错对照文末「常见错误」。

### 第 4 步：语音合成 TTS（可选）

不想用语音：设 `ENABLE_TTS = false`，直接跳过本节。

要用语音：

1. 下载 GPT-SoVITS v2，确认能正常启动 `api_v2.bat`；
2. 准备一段 3～10 秒、干净无伴奏的参考音频（`.wav`）；
3. `TTS_PROMPT_TEXT` 必须填**这段音频里实际说的话**，语言由 `TTS_PROMPT_LANG` 指定（中文 `zh`、日语 `ja`）；
4. 填好后启动程序，它会自动拉起 9880 服务。

```env
ENABLE_TTS = true
TTS_API_URL = http://127.0.0.1:9880
TTS_REF_AUDIO_PATH = "D:\voices\violet_ref.wav"
TTS_PROMPT_TEXT = 自動手記人形サービスバイオレットエヴァーガーデンです
TTS_PROMPT_LANG = ja
TTS_BAT_PATH = D:\GPT-SoVITS\api_v2.bat
TTS_TIMEOUT = 180
TTS_SPEED_FACTOR = 1.15
TTS_TARGET_LUFS = -20
TTS_TRUE_PEAK = -1.5
```

| 变量 | 说明 |
|---|---|
| `TTS_BAT_PATH` | `api_v2.bat` 的完整路径，程序用它启动服务 |
| `TTS_REF_AUDIO_PATH` | 参考音色音频，3～10 秒最佳 |
| `TTS_PROMPT_TEXT` | 参考音频的原文，**必须逐字一致**，否则音色会乱 |
| `TTS_PROMPT_LANG` | 参考音频语言：`zh` / `ja` / `en` |
| `TTS_SPEED_FACTOR` | 语速，1.0 原速，范围 0.5～2.0 |
| `TTS_TARGET_LUFS` / `TTS_TRUE_PEAK` | 逐句响度归一化目标与峰值上限 |
| `TTS_TIMEOUT` | 单句合成超时（秒），长句或慢机器可调大 |

### 第 5 步：语音识别 ASR（可选）

把 `vosk-model-small-cn-0.22` 整个文件夹放成：

```
vosk-model\vosk-model-small-cn-0.22\
```

缺模型时语音输入只会静默失效；装好后按住空格即可说话，松开自动识别。

### 第 6 步：人设（可选）

`prompt.txt` 是角色人格，可以微调语气，但不建议大改规则，否则容易答非所问。

### 常见错误

| 现象 | 多半是 | 处理 |
|---|---|---|
| `401 Unauthorized` | Key 错误 / 过期 | 重新复制 `ARK_API_KEY`，注意别把引号、空格带进去 |
| `404 model not found` | 模型或接入点 ID 不对 | 控制台确认接入点已开通，填 `ep-` 开头的 ID |
| 回复只有半句 | `MAX_TOKENS` 太小 | 调到 600～1000，或把 `LLM_THINKING` 设为 `off` |
| 没声音，日志报 9880 连接失败 | GPT-SoVITS 没起来 | 手动运行 `api_v2.bat`，浏览器打开 `http://127.0.0.1:9880/docs` 确认 |
| 语音是杂音 / 断句奇怪 | 参考音频与 `TTS_PROMPT_TEXT` 不一致 | 两者必须逐字对应；音频 3～10 秒、干净无伴奏 |
| 按住空格没反应 | Vosk 模型缺失或路径不对 | 检查 `vosk-model\vosk-model-small-cn-0.22` |
| 改了配置不生效 | 程序还在运行 | 关掉重开；设置页保存会立即生效 |

### 也可以不改文件

运行后点聊天窗 ☰（或托盘图标）→「设置…」，直接填 Key / 接口地址 / 模型 / 温度 / 长度，保存即写回 `config.env`。

> 作者提示：内置的「测试连接」按钮不太可靠，建议以实际发消息能否回复为准。

---

## 四、核心功能

### 1. AI 人设对话
严格遵循薇尔莉特温柔内敛人设，支持短句输出，可通过配置 `MAX_TOKENS` 控制回答长度；自动识别天气、热点、汇率类问题调取实时资讯。

### 2. 天气自动切换人设
每 18 分钟后台异步爬取天气，检测到降雨自动切换病弱感冒立绘，对话同步更新状态提示；网络异常自动回退正常立绘。

### 3. 资讯爬虫
- B 站全站热榜（取前 5 条）
- 美元 / 日元实时汇率
- 上海 Au9999 现货金价

爬虫内置 18 分钟冷却 + 全局 3 秒请求间隔，严格防 IP 封禁，网络请求放在子线程不卡顿窗口。

### 4. 本地双语言 TTS
`/zh` 中文 / `/ja` 日语切换朗读，长文本自动分句分段合成，解决接口 60s 读取超时问题；无云端语音费用。
中文一言难尽，直接调日语吧

### 5. 离线语音输入
按住空格说话，松开自动识别，ESC 取消收音，全程不需要联网语音接口。

### 6. 摄像头视觉输入
摄像头默认关闭，点击聊天窗口标题栏的“视觉”按钮后才会打开预览并启用自动麦克风录音。检测支持正脸和左右侧脸，局部对比度增强可改善光线不均时的定位；嘴部连续运动会触发录音，讲话停止后自动识别并发送。为避免侧脸下嘴部区域定位偏差，侧脸只用于定位，请正对摄像头讲话；预览、人脸框和运动检测都在本机完成，不保存或上传摄像头画面。点击预览面板的“×”只隐藏画面，视觉检测和讲话自动录音继续；点击标题栏的“预览”可重新显示画面，点击“视觉”按钮或托盘菜单中的“视觉输入”才会关闭视觉输入。隐藏聊天窗时视觉输入保持运行，退出程序时会关闭摄像头；托盘图标提示视觉输入状态。录音中按 ESC 可取消当前这一段。此功能使用人脸位置与嘴部运动作启发式判断，不做人脸身份识别；遮挡或背景运动仍可能影响判断。

### 7. 窗口交互
可置顶拖拽主小人窗口、独立聊天框、历史记录窗口；输入「再见」休眠对话、截断历史上下文；输入「退出」或点击聊天窗标题栏「×」会退出程序并关闭本次启动的后台服务。托盘菜单的「隐藏聊天框」只隐藏窗口，程序仍在后台运行。

### 8. 仿生记忆
- **核心人格**：`prompt.txt` 是独立的人格底层，记忆操作不会修改它。
- **短期记忆**：最近 4 轮对话只保留在当前运行期间。临时印象可以改变后续上下文，并在指定轮数后衰减；设置的「记忆」页可注入 1～12 轮的印象，也可清空短期记忆。
- **长期记忆**：只保存用户明确添加的情感或事实条目，不会自动归档所有聊天。可设置重要度，并在设置的「记忆」页逐条选择遗忘；情感线索约占 72% 的召回空间，事实线索约占 28%。
- **本地与请求**：长期记忆以 JSON 保存在 `data/long_term_memory.json`，并被 Git 忽略。记忆被召回时会随对话请求发送到 `config.env` 中配置的大模型服务。

---

## 五、操作指令

| 指令 | 效果 |
|------|------|
| `/zh` | 切换中文语音朗读 |
| `/ja` | 切换日语语音朗读 |
| `/记住情感 内容` | 明确保存一条情感记忆 |
| `/记住事实 内容` | 明确保存一条事实记忆 |
| `/遗忘 关键词` | 遗忘所有包含该关键词的长期记忆；也可在设置中逐条选择 |
| `/污染 内容` | 注入一条默认影响后续 4 次成功回复的短期印象 |
| `/清空短期` | 清空短期对话上下文和临时印象，不影响长期记忆 |
| 再见 | 进入休眠，暂停对话，保留窗口 |
| 退出 / 聊天窗标题栏「×」 | 完全关闭程序和本次启动的 TTS、ASR 服务；已在运行的外部服务不会被关闭 |
| 询问天气 / 热搜 / 金价 / 汇率 | 自动调取爬虫数据结合 AI 回答 |
| 按住空格 | 语音输入，松开识别文字 |
| 标题栏摄像头按钮 | 开启/关闭视觉输入与讲话自动录音 |
| ESC | 取消当前语音输入 |

---

## 六、启动方式

### 一键启动（Windows）

双击项目目录中的 `start-violet.bat`。启动器会以 CPU 模式启动 GPT-SoVITS、等待服务就绪，再打开桌面人偶；点击聊天窗标题栏「×」后，它会停止本次启动的 TTS 和 ASR 服务。若本地服务已在运行，启动器会复用且不会关闭这些外部服务。启动日志保存在 `%TEMP%\violet`。

默认 GPT-SoVITS 目录为启动器项目上两级目录中的 `GPT-SoVITS-v5-20261005\GPT-SoVITS-v2pro-20261006`。如果安装在其他位置，可在启动前设置 `GPT_SOVITS_DIR` 环境变量为包含 `api_v2.py` 的目录。

桌面人偶启动后，在聊天框输入 `/ja` 切换为日语朗读，输入 `/zh` 切回中文。

### 手动启动

打开终端，进入项目根目录执行：

```powershell
python main.py
```

如果立绘、Vosk 模型、摄像头依赖或 API 配置暂缺，程序仍可启动；缺失立绘会显示提示，缺失语音模型会在使用语音输入时提示，摄像头依赖只在开启视觉输入时提示，AI 对话则需先配置有效 API Key。

---

## 七、程序防护与优化

1. 所有网络请求、AI 推理、语音合成全部子线程运行，UI 永不卡死闪退；
2. 爬虫多级缓存、18 分钟冷却，降低访问频率避免站点拉黑；
3. TTS 音频本地缓存，重复对话无需重新生成；
4. 全部网络、模型、IO 操作增加异常捕获，报错仅文字提示，程序不会崩溃退出；
5. 上下文自动裁剪，最多保留最近 4 轮对话，并限制记忆注入长度，防止 prompt 过长、token 消耗过高。

---

## 八、常见问题

### 1. 无语音输出
检查 `config.env` 中 `TTS_BAT_PATH` 路径是否正确，确认 GPT-SoVITS 服务能正常启动。

### 2. 语音识别报错
`vosk-model` 文件夹缺失或模型文件不全，请确认模型目录结构正确。

### 3. 图片显示异常
`static/prep_png` 缺少对应命名图片，请检查文件名是否与文档一致。

### 4. LLM 回答失败
核对 `ARK_API_KEY` 密钥、接口地址是否有效，确认账户余额充足。

### 5. 爬虫获取失败
网络波动，等待冷却时间后自动重试；或检查本地网络是否能正常访问目标站点。

### 6. 语音回复期间视觉识别导致卡退（已修复）
检查发现，薇尔莉特仍在播放语音回复时，摄像头视觉输入可能同时触发自动录音和语音识别，造成音频任务并发并导致程序卡退。现在会等 TTS 音频播放结束后再允许视觉输入触发语音识别；播放期间摄像头预览与人脸检测仍继续运行。

---

## 九、仓库文件说明

| 文件 | 说明 |
|------|------|
| main.py | 主窗口、聊天、UI 逻辑 |
| crawler.py | 天气 / B 站热搜 / 汇率爬虫工具 |
| core/llm_api.py | 大模型接口调用 |
| core/memory.py | 本机长期记忆与短期印象管理 |
| core/tts.py | 翻译 + 语音合成工具 |
| voice_input.py | 离线语音识别 |
| prompt.txt | 薇尔莉特角色人设 |
| data/long_term_memory.json | 用户明确保存的长期记忆（运行时生成，不提交到 Git） |
| config.env.example | 配置模板（真实密钥自行创建 config.env） |
| .gitignore | 屏蔽密钥、本地记忆、缓存、音频、模型、图片等无关文件 |
| requirements.txt | 项目依赖清单 |

---

## 十、目录结构

```
violet/
├── main.py                 # 主程序入口
├── crawler.py              # 爬虫模块
├── core/                   # 核心模块目录
│   ├── llm_api.py          # 大模型接口
│   ├── memory.py           # 长期记忆与短期工作记忆
│   └── tts.py              # 翻译 + TTS 语音合成
├── voice_input.py          # 语音输入
├── camera_module.py        # 摄像头预览与讲话检测
├── prompt.txt              # 角色人设
├── config.env.example      # 配置模板
├── data/                   # 长期记忆文件（首次保存后生成，Git 忽略）
├── requirements.txt        # 依赖清单
├── .gitignore              # Git 忽略规则
├── README.md               # 项目说明
├── static/
│   └── prep_png/           # 立绘图片（自行放入）
├── vosk-model/             # 语音识别模型（自行放入）
├── cache/                  # 爬虫缓存（自动生成）
└── tts_output/             # TTS 音频输出（自动生成）
```
