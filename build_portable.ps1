# 把当前这台机器上跑通的 Violet 组装成一个可搬移的文件夹。
#
#   .\build_portable.ps1                # 真实复制（约 12 GB，慢）
#   .\build_portable.ps1 -Link          # 用目录联接代替复制，只验证结构（秒级）
#
# 产出：dist_portable\Violet-便携版\   —— 拷给别人，双击 Violet.exe 即可。

param(
    [string]$Target = (Join-Path $PSScriptRoot "dist_portable\Violet-便携版"),
    [string]$TtsSource = $env:GPT_SOVITS_DIR,
    [string]$UvPython = $env:UV_PYTHON_HOME,
    [string]$SitePackages = (Join-Path (Split-Path -Parent $PSScriptRoot) ".venv\Lib\site-packages"),
    [switch]$Link
)

$ErrorActionPreference = "Stop"
$app = $PSScriptRoot
$workspace = Split-Path -Parent $app
$exe = Join-Path $app "Violet.exe"

function Step($text) { Write-Host "== $text" -ForegroundColor Cyan }
function Note($text) { Write-Host "   $text" }

function Ensure-Dir($path) { if (-not (Test-Path -LiteralPath $path)) { New-Item -ItemType Directory -Path $path -Force | Out-Null } }

function Copy-Tree($source, $dest, [string[]]$excludeDirs = @(), [string[]]$excludeFiles = @()) {
    Ensure-Dir $dest
    $robocopyArgs = @($source, $dest, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
    if ($excludeDirs.Count -gt 0) { $robocopyArgs += "/XD"; $robocopyArgs += $excludeDirs }
    if ($excludeFiles.Count -gt 0) { $robocopyArgs += "/XF"; $robocopyArgs += $excludeFiles }
    robocopy @robocopyArgs | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败：$source -> $dest (code $LASTEXITCODE)" }
}

function Link-Tree($source, $dest, $isDir = $true) {
    Ensure-Dir (Split-Path -Parent $dest)
    if (Test-Path -LiteralPath $dest) { Remove-Item -LiteralPath $dest -Recurse -Force }
    if ($isDir) { New-Item -ItemType Junction -Path $dest -Target $source | Out-Null }
    else { New-Item -ItemType HardLink -Path $dest -Target $source | Out-Null }
}

if (-not (Test-Path $exe)) { throw "缺少 Violet.exe，先运行 PyInstaller 打包" }

$buildInputs = @(
    @{ Name = "GPT-SoVITS source folder (use -TtsSource or GPT_SOVITS_DIR)"; Path = $TtsSource },
    @{ Name = "uv Python folder (use -UvPython or UV_PYTHON_HOME)"; Path = $UvPython },
    @{ Name = "site-packages folder (use -SitePackages)"; Path = $SitePackages }
)
foreach ($buildInput in $buildInputs) {
    if ([string]::IsNullOrWhiteSpace($buildInput.Path) -or
        -not (Test-Path -LiteralPath $buildInput.Path -PathType Container)) {
        throw "Required build folder not found: $($buildInput.Name)"
    }
}

Step "清理目标目录"
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Recurse -Force }
Ensure-Dir $Target

Step "复制应用文件"
Copy-Tree $app $Target @("logs", "tts_output", "cache", "dist", "build", "__pycache__", "dist_portable", ".git") @(
    "config.env", "*.bak*", "build_portable.ps1", "start-violet.*",
    "README.md", "requirements.txt", ".gitignore", "LICENSE",
    "violet_launcher.py", "violet.ico", "config.env.example"
)
Copy-Item -LiteralPath $exe -Destination (Join-Path $Target "Violet.exe") -Force
Ensure-Dir (Join-Path $Target "logs")
Ensure-Dir (Join-Path $Target "tts_output")

Step "包内 Python"
if ($Link) { Link-Tree $UvPython (Join-Path $Target "python") }
else { Copy-Tree $UvPython (Join-Path $Target "python") @("__pycache__", "Lib\test", "Lib\idlelib") }

Step "依赖库 site-packages"
if ($Link) { Link-Tree $SitePackages (Join-Path $Target "site-packages") }
else { Copy-Tree $SitePackages (Join-Path $Target "site-packages") @("__pycache__") }

$ttsOut = Join-Path $Target "GPT-SoVITS"
Step "GPT-SoVITS 运行环境（$([math]::Round(((Get-ChildItem (Join-Path $TtsSource 'runtime') -Recurse -File | Measure-Object Length -Sum).Sum)/1GB,2)) GB）"
if ($Link) {
    Link-Tree $TtsSource $ttsOut
} else {
    Ensure-Dir $ttsOut
    # 根目录只留运行必需的几个文件
    foreach ($f in @("api_v2.py", "config.py", "weight.json", "LICENSE")) {
        $src = Join-Path $TtsSource $f
        if (Test-Path $src) { Copy-Item -LiteralPath $src -Destination (Join-Path $ttsOut $f) -Force }
    }
    Copy-Tree (Join-Path $TtsSource "runtime") (Join-Path $ttsOut "runtime")

    Step "GPT_SoVITS 代码（跳过用不到的预训练模型）"
    Copy-Tree (Join-Path $TtsSource "GPT_SoVITS") (Join-Path $ttsOut "GPT_SoVITS") @("pretrained_models")

    $pm = Join-Path $TtsSource "GPT_SoVITS\pretrained_models"
    $pmOut = Join-Path $ttsOut "GPT_SoVITS\pretrained_models"
    Ensure-Dir $pmOut
    foreach ($dir in @("chinese-hubert-base", "chinese-roberta-wwm-ext-large", "fast_langdetect", "sv")) {
        Copy-Tree (Join-Path $pm $dir) (Join-Path $pmOut $dir)
    }
    foreach ($file in @("s1v3.ckpt")) {
        $src = Join-Path $pm $file
        if (Test-Path $src) { Copy-Item -LiteralPath $src -Destination (Join-Path $pmOut $file) -Force }
    }
    Ensure-Dir (Join-Path $pmOut "v2Pro")
    Copy-Item -LiteralPath (Join-Path $pm "v2Pro\s2Gv2Pro.pth") -Destination (Join-Path $pmOut "v2Pro\s2Gv2Pro.pth") -Force

    Step "tools（只留 i18n、便携运行时、识别模型、AP_BWE）"
    Copy-Tree (Join-Path $TtsSource "tools") (Join-Path $ttsOut "tools") @(
        "uvr5",
        "denoise-model",
        "__pycache__",
        "speech_UniASR_asr_2pass-cantonese-CHS-16k-common-vocab1468-tensorflow1-online",
        "._____temp"
    )
}

Step "写入便携版配置（相对路径 + 空 Key，强制对方填自己的）"
$config = Get-Content -LiteralPath (Join-Path $app "config.env.example") -Raw -Encoding UTF8
$overrides = @{
    "ARK_API_KEY"          = ""
    "GPT_SOVITS_DIR"       = "GPT-SoVITS"
    "ASR_MODEL_BASE"       = "GPT-SoVITS/tools/asr/models"
    "TTS_FFMPEG_PATH"      = "GPT-SoVITS/runtime/ffmpeg.exe"
    "TTS_REF_AUDIO_PATH"   = "ref/violet_ref.wav"
    "ENABLE_TTS"           = "true"
    "ENABLE_ASR"           = "true"
}
foreach ($key in $overrides.Keys) {
    $line = "$key=$($overrides[$key])"
    if ($config -match "(?m)^\s*$key\s*=.*$") {
        $config = [regex]::Replace($config, "(?m)^\s*$key\s*=.*$", $line)
    } else {
        $config = $config.TrimEnd() + "`r`n$line`r`n"
    }
}
$configPath = Join-Path $Target "config.env"
[System.IO.File]::WriteAllText($configPath, $config, (New-Object System.Text.UTF8Encoding($false)))

Step "写入使用说明"
$readme = @"
薇尔莉特 · 便携版
================

第一次使用（约 2 分钟）
  1. 如果 Windows 弹出「已保护你的电脑」，点「更多信息」→「仍要运行」
     （这是未签名程序的常规提示，不是病毒）
  2. 双击 Violet.exe
  3. 第一次会自动弹出设置窗口：把「API Key」粘进去，点「测试连接」确认能通，再点「保存」
     （没有 Key 就去服务商控制台申请，接口地址和模型 ID 已经填好）
  4. 开始聊天：直接打字回车；按住空格说话，松开自动发送
     摄像头默认关闭；点标题栏“视觉”按钮开启预览和自动录音，“×”只隐藏预览
     视觉检测保持运行；点击标题栏“视觉”按钮关闭，点击“预览”可重新显示画面
     隐藏聊天窗时视觉输入仍运行；可从托盘菜单关闭，退出应用时会自动关闭摄像头

文件说明
  Violet.exe      双击这个启动（不要删）
  config.env      所有配置；界面上改也一样
  GPT-SoVITS      日文语音引擎（不要改动里面的文件）
  python/         程序自带的运行环境，不需要另装 Python
  site-packages/  依赖库，同上
  static/ ref/    立绘和参考音频
  logs/           崩溃日志（出问题时看这里）

常见问题
  · 没有声音：确认 9880 端口没被占用；看 logs 目录或 %TEMP%\violet\gpt-sovits.log
  · 启动慢：第一次要加载语音模型，约 15 秒，属正常
  · 全部配置清空：删掉 config.env 重启即可（会重新弹设置）
"@
[System.IO.File]::WriteAllText((Join-Path $Target "使用说明.txt"), $readme, (New-Object System.Text.UTF8Encoding($true)))

$size = (Get-ChildItem $Target -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
Write-Host ""
Write-Host ("完成：" + $Target) -ForegroundColor Green
Write-Host ("体积：" + [math]::Round($size/1GB, 2) + " GB")
