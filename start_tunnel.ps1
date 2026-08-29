#Requires -Version 5.1
<#
.SYNOPSIS
    一键启动「竞彩赔率分析网页版 + Cloudflare Tunnel 公网穿透」。

.DESCRIPTION
    1. 在本机启动 python web_app.py（默认端口 8000）。
    2. 等待服务可用后，自动启动 cloudflared tunnel --url http://localhost:8000。
    3. 控制台会输出 https://xxx.trycloudflare.com 的公网链接，手机浏览器打开即可。

.REQUIREMENTS
    - 已安装 Python 并在 PATH 中（或本目录的 venv）。
    - 已下载 cloudflared.exe 并放到 PATH 或本目录（见 README 方式一）。

.NOTES
    Cloudflare Quick Tunnel 每次启动会生成不同的临时链接。
    如需固定链接，请按 README 的"方式一"第 4 步配置 Cloudflare Zero Trust Tunnels。
#>

param(
    [int]$Port = 8000,
    [string]$Cloudflared = "cloudflared"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

# 检查 cloudflared 是否存在
$cf = Get-Command $Cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    $localCf = Join-Path $root "cloudflared.exe"
    if (Test-Path $localCf) {
        $Cloudflared = $localCf
    } else {
        Write-Host "错误：找不到 cloudflared。" -ForegroundColor Red
        Write-Host "请下载 Windows 版 cloudflared.exe 并放到本目录，或加入系统 PATH。" -ForegroundColor Yellow
        Write-Host "下载地址：https://github.com/cloudflare/cloudflared/releases" -ForegroundColor Yellow
        pause
        exit 1
    }
} else {
    $Cloudflared = $cf.Source
}

# 检查 Python 与依赖
python --version 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "错误：找不到 python，请确认 Python 已安装并加入 PATH。" -ForegroundColor Red
    pause
    exit 1
}

if (-not (Test-Path (Join-Path $root "requirements.txt"))) {
    Write-Host "错误：未找到 requirements.txt，请确认在本项目根目录运行。" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "[*] 检查 Python 依赖..." -ForegroundColor Cyan
python -m pip install -q -r requirements.txt | Out-Null

# 启动 web_app.py
Write-Host "[*] 启动网页服务 python web_app.py $Port ..." -ForegroundColor Cyan
$webProc = Start-Process -FilePath "python" -ArgumentList "web_app.py", $Port -WorkingDirectory $root -PassThru -WindowStyle Minimized

# 等待服务可用
$url = "http://localhost:$Port/healthz"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 300
    }
}

if (-not $ready) {
    Write-Host "错误：网页服务启动失败或 /healthz 未响应。" -ForegroundColor Red
    Write-Host "请手动检查 python web_app.py 是否能正常运行。" -ForegroundColor Yellow
    Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
    pause
    exit 1
}

Write-Host "[*] 网页服务已就绪：http://localhost:$Port" -ForegroundColor Green
Write-Host "[*] 启动 Cloudflare Tunnel（请稍候，首次连接需要几秒）..." -ForegroundColor Cyan
Write-Host ""

# 启动 cloudflared，并把输出的公网链接高亮显示
& $Cloudflared tunnel --url "http://localhost:$Port" 2>&1 | ForEach-Object {
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

# tunnel 结束后清理网页服务
Write-Host "[*] Tunnel 已退出，正在关闭网页服务..." -ForegroundColor Yellow
Stop-Process -Id $webProc.Id -Force -ErrorAction SilentlyContinue
