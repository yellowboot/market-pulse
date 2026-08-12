#!/bin/bash
cd "$(dirname "$0")"
echo "Собираю свежие новости..."
python3 fetch_news.py
if [ $? -ne 0 ]; then
    echo ""
    echo "Похоже, Python 3 не установлен. Установите его с python.org"
    read -n 1 -s -r -p "Нажмите любую клавишу для выхода..."
    exit 1
fi
echo ""
echo "Готово! Открываю дашборд..."
open "news_dashboard.html"
sleep 1
