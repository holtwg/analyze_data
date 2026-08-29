@echo off
chcp 65001 >nul
REM 一键启动「竞彩赔率分析网页版 + Cloudflare Tunnel 公网穿透」
REM 实际逻辑在 start_tunnel.ps1（需 UTF-8 BOM，已带），本批处理仅负责调用 PowerShell。
powershell -ExecutionPolicy Bypass -File "%~dp0start_tunnel.ps1" %*
