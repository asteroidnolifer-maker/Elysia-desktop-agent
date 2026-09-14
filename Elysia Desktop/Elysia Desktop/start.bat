@echo off
cd /d "%~dp0"
start "" elysia-desktop.exe
timeout /t 2 >nul
start "" http://127.0.0.1:8085
