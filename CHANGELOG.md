# Changelog

本项目所有值得记录的改动。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed

- README 配置指南重写为分步教程：必填/可选分离，补充配置项表格与常见错误对照。
- 英文 README 同步补充配置与排错章节。
- `config.env.example` 补齐 `LLM_THINKING`、`TTS_BAT_PATH`、`TTS_SPEED_FACTOR`、`TTS_TARGET_LUFS`、`TTS_TRUE_PEAK` 等配置项。

## [v0.1.0] - 2026-10-28

首个公开版本 / Initial public release。

### Added

- 完整源码：PyQt6 桌面人偶、LLM 对话、本地双语 TTS、离线语音输入、摄像头视觉输入、资讯爬虫、仿生记忆。
- `config.env.example` 配置模板（仅占位符，不含任何真实密钥）。
- 中文 `README.md` 与英文 `README.en.md`。
- 项目主页（GitHub Pages，`docs/`）。
- GitHub Actions 密钥扫描：阻止 `config.env` 被误提交，检测 `sk-` / `ark-` 密钥与私钥特征。
- 打包说明 `docs/BUILD.md`。

### Changed

- README 中的许可说明与 MIT License 对齐：可自由使用、修改、分发，保留版权声明。
- README 新增「来源与许可」小节，注明基于 [moreandice](https://github.com/moreandice) 的项目学习复刻。

### Notes

- 分发策略为「**源码 + 自行部署**」：Python 环境、依赖与相关插件/服务由使用者自行安装，仓库不提供预配置环境。
- 仓库**不包含**角色立绘、Vosk 模型、参考音频、GPT-SoVITS 运行时，也不包含打包好的 `Violet.exe` / 便携版（体积与密钥风险原因，见 `docs/BUILD.md`）。
- 便携版在本地构建约 12 GB，需自行打包。

[v0.1.0]: https://github.com/HE360-9/violet-desktop-mascot/releases/tag/v0.1.0
