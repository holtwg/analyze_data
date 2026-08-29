@echo off
chcp 65001 >nul
REM One-click launcher for the odds-analysis web app + Cloudflare Tunnel.
REM All logic lives in start_tunnel.ps1 (UTF-8 BOM). This bat just calls PowerShell.
powershell -ExecutionPolicy Bypass -File "%~dp0start_tunnel.ps1" %*
echo.
echo ============================================================
echo  Script exited. To stop the web server / tunnel, just close this window.
echo  If something went wrong, check tunnel.log in this folder.
echo ============================================================
pause
