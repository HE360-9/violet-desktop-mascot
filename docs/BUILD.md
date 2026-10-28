# 打包说明 / Build Guide

> 仓库**不提供**打包好的 `Violet.exe` 或便携版压缩包，原因见下。本文说明如何在本机安全地自行打包。

## 为什么仓库里没有 exe

1. **`Violet.exe` 只是启动器。** 它由 `violet_launcher.py` 经 PyInstaller 打包，负责拉起 GPT-SoVITS / FunASR 和主程序，本身不含 PyQt6、Torch、模型等依赖。单独一个 exe 无法运行。
2. **完整便携版约 12 GB。** `build_portable.ps1` 会把 `python/`、`site-packages/`（含 Torch）、GPT-SoVITS 运行时一起复制进去，远超 GitHub Release 单文件 2 GB 的上限。
3. **打包容易夹带密钥。** 便携版的 `config.env` 若直接复制本机配置，会把你的 `ARK_API_KEY` 一起发出去。

因此 Release 只提供源码（GitHub 自动生成 zip / tar.gz）。

## 在本机构建

### 1. 准备环境

- Windows 10/11，Python 3.11 或 3.12
- 已按 README 装好依赖，项目能 `python main.py` 正常启动
- 本地已安装 GPT-SoVITS（`runtime/python.exe` 可用）

### 2. 打包启动器 exe

```powershell
pip install pyinstaller
pyinstaller --onefile --noconsole --icon violet.ico violet_launcher.py
```

产物在 `dist\Violet.exe`。若已有 `build\Violet.spec`，也可以：

```powershell
pyinstaller build\Violet.spec
```

### 3. 构建便携版目录

```powershell
$env:GPT_SOVITS_DIR = "E:\你的路径\GPT-SoVITS-v5-20261005\GPT-SoVITS-v2pro-20261006"
$env:UV_PYTHON_HOME = "C:\Users\你\AppData\Roaming\uv\python\cpython-3.12.x-windows-x86_64-none"
.\build_portable.ps1
```

产物：`dist_portable\Violet-便携版\`（约 12 GB），拷给别人双击 `Violet.exe` 即可。

> `build_portable.ps1` 会写入一份**空 `ARK_API_KEY`** 的 `config.env`，并要求对方首次启动时自己填写，这是刻意设计，请勿改成复制本机配置。

### 4. 分发前自检

```powershell
# 确认便携目录里没有真实密钥
Select-String -Path "dist_portable\Violet-便携版\config.env" -Pattern "ARK_API_KEY"
# 应输出：ARK_API_KEY =
```

再全局搜一遍你自己的 key 前缀，确认没有出现在任何文件里，然后才上传网盘或分发。

## 关于 Release

如果你想要预编译版本，建议：

- 用网盘 / 对象存储分发 12 GB 便携包（分卷或直链），并在 Release 说明里附链接；
- 或只分发源码 + 本说明，让使用者自行构建。

无论哪种，都不要把带密钥的 `config.env` 打进包里。
