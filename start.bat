@echo off
title MOpsWork — Starting Servers
cd /d "%~dp0"

echo Killing any existing Python processes on ports 8000 and 8003...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000"') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8003"') do (
    taskkill /F /PID %%a >nul 2>&1
)

timeout /t 2 /nobreak >nul

echo Starting backend (port 8003)...
start "MOpsWork-Backend" "%CD%\.venv\Scripts\python.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8003

timeout /t 3 /nobreak >nul

echo Starting frontend (port 8000)...
start "MOpsWork-Frontend" "%CD%\.venv\Scripts\python.exe" -m http.server 8000 --directory "%CD%"

echo.
echo  MOpsWork — running at:
echo  ========================
echo  Frontend  ^>  http://localhost:8000/jobs.html
echo  Backend   ^>  http://localhost:8003/health
echo.
echo  Close these windows to stop the servers.
echo.

start http://localhost:8000/jobs.html

Pause