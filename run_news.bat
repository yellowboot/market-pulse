@echo off
cd /d "%~dp0"
echo Собираю свежие новости...
python fetch_news.py
if %errorlevel% neq 0 (
    echo.
    echo Похоже, Python не установлен или не найден в PATH.
    echo Скачайте Python с https://www.python.org/downloads/ и установите
    echo с галочкой "Add Python to PATH".
    pause
    exit /b
)
echo.
echo Готово! Открываю дашборд...
start "" "news_dashboard.html"
timeout /t 2 >nul
