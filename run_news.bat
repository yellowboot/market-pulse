@echo off
cd /d "%~dp0"
echo Fetching fresh news...
python fetch_news.py
if %errorlevel% neq 0 (
    echo.
    echo Looks like Python isn't installed or isn't on PATH.
    echo Download Python from https://www.python.org/downloads/ and install it
    echo with the "Add Python to PATH" checkbox checked.
    pause
    exit /b
)
echo.
echo Done! Opening the dashboard...
start "" "news_dashboard.html"
timeout /t 2 >nul
