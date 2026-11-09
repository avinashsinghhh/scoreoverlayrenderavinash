@echo off
title Live Stream Overlay Server (Port 5050)
color 0C

echo ======================================================================
echo              LIVE STREAM OVERLAY SUITE (FIXED PORT 5050)
echo           - Live YouTube Like Counter and Goal Overlay
echo           - Chess.com Live Session Score Overlay
echo ======================================================================
echo.
echo  [!] Keep this terminal window OPEN (or MINIMIZED) while streaming.
echo  [OK] OBS BROWSER URL: http://localhost:5050/likes-overlay.html
echo ======================================================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Launching overlay server on fixed port 5050...
    python server.py
) else (
    echo [Notice] Python is not in system PATH.
    echo Opening Like Counter Dashboard directly in your default browser...
    start likes-control.html
)

echo.
echo Server closed. Press any key to exit.
pause >nul
