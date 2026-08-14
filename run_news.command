#!/bin/bash
cd "$(dirname "$0")"
echo "Fetching fresh news..."
python3 fetch_news.py
if [ $? -ne 0 ]; then
    echo ""
    echo "Looks like Python 3 isn't installed. Install it from python.org"
    read -n 1 -s -r -p "Press any key to exit..."
    exit 1
fi
echo ""
echo "Done! Opening the dashboard..."
open "news_dashboard.html"
sleep 1
