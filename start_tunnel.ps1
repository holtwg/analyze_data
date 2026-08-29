#Requires -Version 5.1
param(
    [int]$Port = 8000
)

# cloudflared 日志写 stderr，若用 Stop 会在报错时直接中止；这里用 Continue 保证窗口不闪退。
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

# 全程记录到 tunnel.log，便于出错后排查（窗口关闭也能看到）。
$logFile = Join-Path $root "tunnel.log"
try { Start-Transcript -Path $logFile -Encoding utf8 -Force | Out-Null } catch { }

function Find-Python {
    $candidates = @(
        "C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe",
        "python",
        "py"
    )
    foreach ($c in $candidates) {
        try {
            & $c -c "import httpx,parsel,typer" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return $c }
        } catch {
            # 该候选不可用，试下一个
        }
    }
    return $null
}

function Get-FreePort {
    param([int]$Start = 8000)
    for ($p = $Start; $p -lt ($Start + 100); $p++) {
        $listener = $null
        try {
            $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $p)
            $listener.Start()
            $listener.Stop()
            return $p
        } catch {
            if ($listener) { try { $listener.Stop() } catch { } }
        }
    }
    return $Start
}

# 端口被占用则自动顺延，避免 healthz 404
$Port = Get-FreePort -Start $Port

$py = Find-Python
if (-not $py) {
    Write-Host "未找到已安装依赖(httpx/parsel/typer)的 Python。" -ForegroundColor Red
    Write-Host "请确认虚拟环境在: C:\Users\Administrator\.workbuddy\binaries\python\envs\default" -ForegroundColor Yellow
    Read-Host "按 Enter 退出"
    exit 1
}
Write-Host "[*] 使用 Python: $py" -ForegroundColor Cyan

# cloudflared 优先使用本目录的 exe；同时兼容误存的 cloudflared.exe.exe 双扩展名
$cfCandidates = @(
    (Join-Path $root "cloudflared.exe"),
    (Join-Path $root "cloudflared.exe.exe")
)
$localCf = $null
foreach ($c in $cfCandidates) {
    if (Test-Path $c) { $localCf = $c; break }
}
if (-not $localCf) {
    Write-Host "未找到 cloudflared.exe，应放在本目录下。" -ForegroundColor Red
    Write-Host "下载地址: https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Yellow
    Write-Host "注意: 请下载 cloudflared-windows-amd64.exe(Windows 版), 不要下 darwin/linux。" -ForegroundColor Yellow
    Read-Host "按 Enter 退出"
    exit 1
}
# 若发现双扩展名，自动改名修复
if ($localCf -like "*.exe.exe") {
    $fixed = Join-Path $root "cloudflared.exe"
    try { Move-Item -Path $localCf -Destination $fixed -Force; $localCf = $fixed; Write-Host "[*] 已自动修复文件名 cloudflared.exe.exe -> cloudflared.exe" -ForegroundColor Green } catch { }
}

Write-Host "[*] 正在启动网页服务: python web_app.py $Port ..." -ForegroundColor Cyan
$webProc = Start-Process -FilePath $py -ArgumentList "web_app.py", $Port `
    -WorkingDirectory $root -PassThru -WindowStyle Minimized

# 等待 /healthz 就绪，强制用 127.0.0.1 (IPv4)，避免 localhost 解析到 IPv6 ::1 失败
$url = "http://127.0.0.1:$Port/healthz"
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $ready) {
    Write-Host "网页服务启动失败或 /healthz 未响应。" -ForegroundColor Red
    Write-Host "请手动运行 'python web_app.py' 并查看 tunnel.log。" -ForegroundColor Yellow
    Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
    Read-Host "按 Enter 退出"
    exit 1
}

Write-Host "[*] 网页服务已就绪: http://localhost:$Port" -ForegroundColor Green
Write-Host "[*] 正在启动 Cloudflare Tunnel（连接公网，请稍候）..." -ForegroundColor Cyan
Write-Host ""

# 后台方式启动 cloudflared，把日志写文件，避免刷屏；实时抓取 trycloudflare 地址
$cfOut = Join-Path $root "cf_out.log"
$cfErr = Join-Path $root "cf_err.log"
$urlFile = Join-Path $root "tunnel_url.txt"
if (Test-Path $cfOut) { Remove-Item $cfOut -Force }
if (Test-Path $cfErr) { Remove-Item $cfErr -Force }

$cfProc = Start-Process -FilePath $localCf -ArgumentList "tunnel", "--url", "http://127.0.0.1:$Port" `
    -WorkingDirectory $root -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $cfOut -RedirectStandardError $cfErr

$tunnelUrl = $null
for ($i = 0; $i -lt 60; $i++) {
    $txt = ""
    if (Test-Path $cfOut) { $txt += (Get-Content $cfOut -Raw -ErrorAction SilentlyContinue) }
    if (Test-Path $cfErr) { $txt += (Get-Content $cfErr -Raw -ErrorAction SilentlyContinue) }
    if ($txt -match "(https://[a-z0-9-]+\.trycloudflare\.com)") {
        $tunnelUrl = $matches[1]
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $tunnelUrl) {
    Write-Host "[!] 60 秒内未能获取隧道地址，请检查 cf_out.log / cf_err.log。" -ForegroundColor Red
    Write-Host "    常见原因: 网络被限制无法连接 cloudflare; 或 cloudflared 版本异常。" -ForegroundColor Yellow
    Stop-Process -Id $cfProc.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
    Read-Host "按 Enter 退出"
    exit 1
}

# 保存并复制到剪贴板，方便手机粘贴
Set-Content -Path $urlFile -Value $tunnelUrl -Encoding ascii
try { Set-Clipboard -Value $tunnelUrl } catch { }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "   手机访问地址（已自动复制到剪贴板）：" -ForegroundColor Green
Write-Host ""
Write-Host "   $tunnelUrl" -ForegroundColor Green -BackgroundColor Black
Write-Host ""
Write-Host "   同时已保存到本目录 tunnel_url.txt，可直接打开复制。" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "[*] 隧道运行中。本机请保持此窗口开启；手机用上面的地址即可访问。" -ForegroundColor Cyan
Write-Host "[*] 关闭本窗口 / 按 Enter 即停止网页与隧道。" -ForegroundColor Cyan
Write-Host ""

Read-Host "按 Enter 停止隧道并退出"

# 清理
try { Stop-Process -Id $cfProc.Id -Force -ErrorAction SilentlyContinue } catch { }
Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
Write-Host "[*] 已停止网页与隧道。" -ForegroundColor Yellow
