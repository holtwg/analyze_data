@echo off
chcp 65001 >nul
:: 一键启动「竞彩赔率分析网页版 + Cloudflare Tunnel 公网穿透」
:: 如果 PowerShell 执行策略被限制，可改用此批处理。
:: 需要 cloudflared.exe 在本目录或 PATH 中。

powershell -ExecutionPolicy Bypass -File "%~dp0start_tunnel.ps1" %*
