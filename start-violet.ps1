$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$workspaceRoot = Split-Path -Parent $projectRoot
$repositoryRoot = Split-Path -Parent $workspaceRoot
$appPython = Join-Path $workspaceRoot ".venv\Scripts\pythonw.exe"
$appEntry = Join-Path $projectRoot "main.py"
$appConfig = Join-Path $projectRoot "config.env"
$ttsRoot = if ($env:GPT_SOVITS_DIR) {
    $env:GPT_SOVITS_DIR
} else {
    Join-Path $repositoryRoot "GPT-SoVITS-v5-20261005\GPT-SoVITS-v2pro-20261006"
}
$ttsPython = Join-Path $ttsRoot "runtime\python.exe"
$ttsEntry = Join-Path $ttsRoot "api_v2.py"
$ttsConfig = Join-Path $ttsRoot "GPT_SoVITS\configs\tts_infer.yaml"
$ttsProcess = $null

# 语音转文字用的本地识别服务（FunASR），跑在 GPT-SoVITS 的 runtime python 里
$asrProcess = $null
$asrEntry = Join-Path $projectRoot "asr_server.py"
$asrUri = "http://127.0.0.1:9881/health"

function Stop-ManagedProcessTree($managedProcess) {
    if ($null -eq $managedProcess) { return }
    try {
        $managedProcess.Refresh()
        if ($managedProcess.HasExited) { return }
    } catch {
        return
    }

    $taskkill = Get-Command "taskkill.exe" -ErrorAction SilentlyContinue
    if ($taskkill) {
        & $taskkill.Source /PID $managedProcess.Id /T /F 2>$null | Out-Null
    }
    try {
        $managedProcess.Refresh()
        if (-not $managedProcess.HasExited) {
            Stop-Process -Id $managedProcess.Id -Force -ErrorAction SilentlyContinue
        }
        $managedProcess.WaitForExit(5000) | Out-Null
    } catch {
    }
}

# 语音服务开关：config.env 里写 ENABLE_TTS=false 时，启动器不再拉起 GPT-SoVITS，
# 平时不朗读就完全不占那几个 GB 内存和 CPU
$enableTts = $true
if (Test-Path -LiteralPath $appConfig) {
    $appConfigText = Get-Content -LiteralPath $appConfig -Raw
    if ($appConfigText -match '(?m)^\s*ENABLE_TTS\s*=\s*["'']?false') {
        $enableTts = $false
    }
}

# 语音合成是 CPU 推理，不设上限会吃满 16 个线程、整机发烫；
# 默认限制到 6 个线程，合成稍慢一点但不影响你同时用电脑
$ttsThreads = if ($env:TTS_CPU_THREADS) { $env:TTS_CPU_THREADS } else { "6" }
$env:TTS_CPU_THREADS = $ttsThreads
$env:OMP_NUM_THREADS = $ttsThreads
$env:MKL_NUM_THREADS = $ttsThreads
$env:TOKENIZERS_PARALLELISM = "false"

# GPT-SoVITS 会把日文原文打印到 stdout，而 Windows 下 Python 的 stdout 默认是 GBK；
# 碰到「・」（U+30FB）这类字符会直接抛 UnicodeEncodeError，导致整个 /tts 请求 400。
# 统一用 UTF-8 输出，日志文件也一并变成 UTF-8。
$env:PYTHONIOENCODING = "utf-8"

$requiredPaths = @($appPython, $appEntry)
if ($enableTts) {
    $requiredPaths += @($ttsPython, $ttsEntry, $ttsConfig)
}
foreach ($requiredPath in $requiredPaths) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file not found: $requiredPath"
    }
}

if ($enableTts) {
    $configText = Get-Content -LiteralPath $ttsConfig -Raw
    $customConfig = [regex]::Match(
        $configText,
        '(?ms)^custom:\s*\r?\n(.*?)(?=^[^\s#]|\z)'
    ).Groups[1].Value
    if ($customConfig -notmatch '(?m)^\s+device:\s*cpu\s*$' -or
        $customConfig -notmatch '(?m)^\s+is_half:\s*false\s*$') {
        throw "GPT-SoVITS is not configured for CPU mode: $ttsConfig"
    }
}

try {
    if ($enableTts) {
        $ttsUri = "http://127.0.0.1:9880/docs"
        $ttsAlreadyRunning = $false
        try {
            $response = Invoke-WebRequest -Uri $ttsUri -TimeoutSec 3 -UseBasicParsing
            $ttsAlreadyRunning = $response.StatusCode -eq 200
        } catch {
            $ttsAlreadyRunning = $false
        }

        if (-not $ttsAlreadyRunning) {
            $logRoot = Join-Path $env:TEMP "violet"
            New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
            $ttsStdout = Join-Path $logRoot "gpt-sovits.log"
            $ttsStderr = Join-Path $logRoot "gpt-sovits-error.log"

            Write-Host "Starting GPT-SoVITS (CPU mode, $ttsThreads threads)..."
            $ttsProcess = Start-Process `
                -FilePath $ttsPython `
                -ArgumentList @("-u", "api_v2.py") `
                -WorkingDirectory $ttsRoot `
                -WindowStyle Hidden `
                -PassThru `
                -RedirectStandardOutput $ttsStdout `
                -RedirectStandardError $ttsStderr

            $ready = $false
            for ($attempt = 0; $attempt -lt 180; $attempt++) {
                if (-not (Get-Process -Id $ttsProcess.Id -ErrorAction SilentlyContinue)) {
                    break
                }

                try {
                    $response = Invoke-WebRequest -Uri $ttsUri -TimeoutSec 2 -UseBasicParsing
                    if ($response.StatusCode -eq 200) {
                        $ready = $true
                        break
                    }
                } catch {
                    Start-Sleep -Seconds 2
                }
            }

            if (-not $ready) {
                if (Get-Process -Id $ttsProcess.Id -ErrorAction SilentlyContinue) {
                    throw "GPT-SoVITS did not become ready. Check logs: $ttsStderr"
                }
                throw "GPT-SoVITS exited during startup. Check logs: $ttsStderr"
            }
            Write-Host "GPT-SoVITS is ready."
        } else {
            Write-Host "Using the GPT-SoVITS service already running on port 9880."
        }
    } else {
        Write-Host "ENABLE_TTS=false in config.env - skipping GPT-SoVITS, running text-only."
    }

    # 本地语音识别服务（FunASR，语音转文字用）。
    # 模型在服务内部后台加载，这里只等端口起来，不阻塞启动；
    # 没加载完时 voice_input.py 会自动先用 Vosk，加载完再切到 FunASR。
    $asrEnabled = $true
    if (Test-Path -LiteralPath $appConfig) {
        $asrConfigText = Get-Content -LiteralPath $appConfig -Raw
        if ($asrConfigText -match '(?m)^\s*ENABLE_ASR\s*=\s*["'']?false') {
            $asrEnabled = $false
        }
    }

    if ($asrEnabled -and (Test-Path -LiteralPath $asrEntry) -and (Test-Path -LiteralPath $ttsPython)) {
        $asrRunning = $false
        try {
            $null = Invoke-WebRequest -Uri $asrUri -TimeoutSec 2 -UseBasicParsing
            $asrRunning = $true
        } catch {
            $asrRunning = $false
        }

        if (-not $asrRunning) {
            $logRoot = Join-Path $env:TEMP "violet"
            New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
            Write-Host "Starting FunASR speech recognition..."
            $asrProcess = Start-Process `
                -FilePath $ttsPython `
                -ArgumentList @("-u", "asr_server.py") `
                -WorkingDirectory $projectRoot `
                -WindowStyle Hidden `
                -PassThru `
                -RedirectStandardOutput (Join-Path $logRoot "asr.log") `
                -RedirectStandardError (Join-Path $logRoot "asr-error.log")
        } else {
            Write-Host "Using the FunASR service already running on port 9881."
        }
    }

    Write-Host "Starting Violet. Close the mascot window to finish."
    $appProcess = Start-Process `
        -FilePath $appPython `
        -ArgumentList @("main.py") `
        -WorkingDirectory $projectRoot `
        -PassThru

    $appProcess.WaitForExit()
    if ($appProcess.ExitCode -ne 0) {
        throw "Violet exited with code $($appProcess.ExitCode)."
    }
} finally {
    if ($asrProcess) {
        Write-Host "Stopping the FunASR service started by this launcher..."
        Stop-ManagedProcessTree $asrProcess
    }
    if ($ttsProcess) {
        Write-Host "Stopping the GPT-SoVITS service started by this launcher..."
        Stop-ManagedProcessTree $ttsProcess
    }
}
