#Requires -Version 5.1
param(
    [int]$Port = 8000
)

# 不要设 Stop：cloudflared 会把运行日志写到 stderr，Stop 会把它当成错误直接中止隧道。
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

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
            # 该候选不存在，继续下一个
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

# 端口已被占用则自动顺延，避免 healthz 404
$Port = Get-FreePort -Start $Port

$py = Find-Python
if (-not $py) {
    Write-Host "错误：未找到已安装依赖(httpx/parsel/typer)的 Python。" -ForegroundColor Red
    Write-Host "请确认虚拟环境存在：C:\Users\Administrator\.workbuddy\binaries\python\envs\default" -ForegroundColor Yellow
    pause
    exit 1
}
Write-Host "[*] 使用 Python: $py" -ForegroundColor Cyan

# cloudflared 优先使用本目录的 exe（无需加入 PATH）
$localCf = Join-Path $root "cloudflared.exe"
if (-not (Test-Path $localCf)) {
    Write-Host "错误：未找到 cloudflared.exe（应放在本目录）。" -ForegroundColor Red
    Write-Host "下载地址：https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Yellow
    Write-Host "注意：必须下载 cloudflared-windows-amd64.exe（Windows 版），不要下 darwin/linux 版。" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "[*] 启动网页服务 python web_app.py $Port ..." -ForegroundColor Cyan
$webProc = Start-Process -FilePath $py -ArgumentList "web_app.py", $Port `
    -WorkingDirectory $root -PassThru -WindowStyle Minimized

# 等待 /healthz 就绪（用 127.0.0.1 强制 IPv4，避免 localhost 解析到 IPv6 ::1 失败）
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
    Write-Host "错误：网页服务启动失败或 /healthz 未响应。" -ForegroundColor Red
    Write-Host "请手动运行 'python web_app.py' 排查错误。" -ForegroundColor Yellow
    Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
    pause
    exit 1
}

Write-Host "[*] 网页服务已就绪：http://localhost:$Port" -ForegroundColor Green
Write-Host "[*] 启动 Cloudflare Tunnel（首次连接需数秒）..." -ForegroundColor Cyan
Write-Host ""

try {
    & $localCf tunnel --url "http://127.0.0.1:$Port" 2>&1 | ForEach-Object {
        $line = $_
        Write-Host $line
        # 高亮 https://xxx.trycloudflare.com
        if ($line -match "(https://[a-z0-9-]+\.trycloudflare\.com)") {
            Write-Host ""
            Write-Host "========================================" -ForegroundColor Green
            Write-Host " 手机访问地址：$($matches[1])" -ForegroundColor Green -BackgroundColor Black
            Write-Host "========================================" -ForegroundColor Green
            Write-Host ""
        }
    }
} finally {
    Write-Host "[*] Tunnel 已退出，正在关闭网页服务..." -ForegroundColor Yellow
    Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
}
