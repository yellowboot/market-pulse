#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Агрегатор новостей фондового рынка.
Собирает заголовки из публичных RSS-лент, делает простой механический
анализ тональности и упоминаний тикеров, сохраняет всё в news_data.js,
который подключается в news_dashboard.html через <script src>.

Запуск:
    python3 fetch_news.py

Требуется только стандартная библиотека Python (никаких pip install).
"""

import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from html import unescape

# На части Windows-систем консоль по умолчанию использует не UTF-8
# (например, cp1252), а вывод скрипта — сплошная кириллица. Без этого
# print() падает с UnicodeEncodeError на первой же строке. reconfigure()
# доступен с Python 3.7+, тихо ничего не делаем на более старых версиях.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# ---------------------------------------------------------------------------
# НАСТРОЙКИ
# ---------------------------------------------------------------------------

# --- Опциональная LLM-классификация (DeepSeek API) --------------------------
# Если задан DEEPSEEK_API_KEY — тональность и важность каждой новости
# определяет DeepSeek (понимает реальный смысл: "отмена санкций" — позитив,
# "рост издержек" — негатив, даже если отдельные слова говорят обратное).
# Если ключа нет или запрос не прошёл — используется локальная эвристика
# по ключевым словам (detect_sentiment / calc_importance ниже), как раньше.
#
# DeepSeek выбран как один из самых дешёвых API с качеством, достаточным для
# этой задачи (классификация тональности/важности — не creative writing).
# API OpenAI-совместимый (эндпоинт /chat/completions), ключ получаем на
# platform.deepseek.com.
#
# КЛЮЧ НИКОГДА НЕ ХРАНИТСЯ В ЭТОМ ФАЙЛЕ И НЕ ПОПАДАЕТ В РЕПОЗИТОРИЙ — только
# переменная окружения. Для локального запуска:
#   macOS/Linux:   export DEEPSEEK_API_KEY="sk-..."
#   Windows (cmd): set DEEPSEEK_API_KEY=sk-...
# Для автоматического обновления через GitHub Actions ключ должен лежать
# ТОЛЬКО в зашифрованных GitHub Secrets репозитория (Settings → Secrets and
# variables → Actions), никогда не в коде и не в логах workflow — подробности
# и инструкция, как задать секрет, не показывая его никому, — в README.md.
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = "deepseek-chat"  # DeepSeek-V3 — дешёвый, этого достаточно для классификации
LLM_BATCH_SIZE = 15  # сколько новостей отправлять в одном запросе к API

# Публичные RSS-ленты финансовых новостей (без подписки, без пейволла на уровне заголовков)
FEEDS = [
    {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex"},
    {"name": "MarketWatch",   "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"name": "Investing.com", "url": "https://www.investing.com/rss/news_25.rss"},
    {"name": "CNBC",          "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"},
    {"name": "Nasdaq",        "url": "https://www.nasdaq.com/feed/rssoutbound?category=Stocks"},
    {"name": "OilPrice.com",  "url": "https://oilprice.com/rss/main"},
    {"name": "Mining.com",    "url": "https://www.mining.com/feed"},
    {"name": "Defense One",   "url": "https://www.defenseone.com/rss/all/"},
    {"name": "FiercePharma",  "url": "https://www.fiercepharma.com/rss/xml"},
    {"name": "CoinDesk",      "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Retail Dive",   "url": "https://www.retaildive.com/feeds/news/"},
]

# Сколько новостей максимум показывать в итоге.
# 7 общих/нишевых лент + 4 отраслевые (оборонка, фарма, крипто, ритейл) —
# теперь у секторов, которые раньше пустовали, тоже будет материал.
MAX_ITEMS = 80

# Тикер + сектор + варианты названий компании (для поиска не только по коду,
# но и по имени в тексте новости — например "Rheinmetall" или "Nike").
# Список охватывает основные сектора рынка, интересные широкому кругу инвесторов:
# технологии, полупроводники, потребительский сектор, энергетику, металлы,
# финансы, здравоохранение, промышленность, облигации/макро и т.д.
COMPANY_MAP = [
    # ---- Полупроводники / AI-инфраструктура ----
    {"ticker": "NVDA", "sector": "Semiconductors",         "names": ["Nvidia"]},
    {"ticker": "AVGO", "sector": "Semiconductors",         "names": ["Broadcom"]},
    {"ticker": "MRVL", "sector": "Semiconductors",         "names": ["Marvell"]},
    {"ticker": "MU",   "sector": "Semiconductors",         "names": ["Micron"]},
    {"ticker": "ON",   "sector": "Semiconductors",         "names": ["ON Semiconductor", "Onsemi"]},
    {"ticker": "ALAB", "sector": "Semiconductors",         "names": ["Astera Labs"]},
    {"ticker": "AMAT", "sector": "Semiconductors",         "names": ["Applied Materials"]},
    {"ticker": "ASML", "sector": "Semiconductors",         "names": ["ASML"]},
    {"ticker": "INTC", "sector": "Semiconductors",         "names": ["Intel"]},
    {"ticker": "AMD",  "sector": "Semiconductors",         "names": ["AMD", "Advanced Micro Devices"]},
    {"ticker": "QCOM", "sector": "Semiconductors",         "names": ["Qualcomm"]},
    {"ticker": "TSM",  "sector": "Semiconductors",         "names": ["TSMC", "Taiwan Semiconductor"]},

    # ---- ПО / AI / Кибербезопасность / Cloud ----
    {"ticker": "CRWD", "sector": "Cybersecurity",      "names": ["CrowdStrike"]},
    {"ticker": "NET",  "sector": "Cybersecurity",      "names": ["Cloudflare"]},
    {"ticker": "PANW", "sector": "Cybersecurity",      "names": ["Palo Alto Networks"]},
    {"ticker": "FTNT", "sector": "Cybersecurity",      "names": ["Fortinet"]},
    {"ticker": "PLTR", "sector": "Software / AI Analytics",      "names": ["Palantir"]},
    {"ticker": "SOUN", "sector": "Software / AI Analytics",      "names": ["SoundHound"]},
    {"ticker": "CRM",  "sector": "Software / Cloud",             "names": ["Salesforce"]},
    {"ticker": "NOW",  "sector": "Software / Cloud",             "names": ["ServiceNow"]},
    {"ticker": "SNOW", "sector": "Software / Cloud",             "names": ["Snowflake"]},
    {"ticker": "ADBE", "sector": "Software / Cloud",             "names": ["Adobe"]},
    {"ticker": "ORCL", "sector": "Software / Cloud",             "names": ["Oracle"]},

    # ---- Big Tech ----
    {"ticker": "MSFT", "sector": "Big Tech",               "names": ["Microsoft"]},
    {"ticker": "GOOGL","sector": "Big Tech",               "names": ["Alphabet", "Google"]},
    {"ticker": "AAPL", "sector": "Big Tech",               "names": ["Apple"]},
    {"ticker": "AMZN", "sector": "Big Tech",               "names": ["Amazon"]},
    {"ticker": "META", "sector": "Big Tech",               "names": ["Meta", "Facebook"]},

    # ---- Электромобили / Автопром ----
    {"ticker": "TSLA", "sector": "Automotive / EV",          "names": ["Tesla"]},
    {"ticker": "RIVN", "sector": "Automotive / EV",          "names": ["Rivian"]},
    {"ticker": "F",    "sector": "Automotive / EV",          "names": ["Ford"]},
    {"ticker": "GM",   "sector": "Automotive / EV",          "names": ["General Motors"]},
    {"ticker": "VOW3", "sector": "Automotive / EV",          "names": ["Volkswagen"]},
    {"ticker": "TM",   "sector": "Automotive / EV",          "names": ["Toyota"]},
    {"ticker": "BYDDY","sector": "Automotive / EV",          "names": ["BYD"]},

    # ---- Потребительский сектор (реальный бизнес: еда, ритейл, бренды) ----
    {"ticker": "NKE",  "sector": "Consumer Goods", "names": ["Nike"]},
    {"ticker": "KO",   "sector": "Consumer Goods", "names": ["Coca-Cola"]},
    {"ticker": "PEP",  "sector": "Consumer Goods", "names": ["PepsiCo"]},
    {"ticker": "MCD",  "sector": "Consumer Goods", "names": ["McDonald's", "McDonalds"]},
    {"ticker": "SBUX", "sector": "Consumer Goods", "names": ["Starbucks"]},
    {"ticker": "WMT",  "sector": "Consumer Goods", "names": ["Walmart"]},
    {"ticker": "COST", "sector": "Consumer Goods", "names": ["Costco"]},
    {"ticker": "PG",   "sector": "Consumer Goods", "names": ["Procter & Gamble"]},
    {"ticker": "DIS",  "sector": "Media / Entertainment",    "names": ["Disney"]},
    {"ticker": "NFLX", "sector": "Media / Entertainment",    "names": ["Netflix"]},

    # ---- Энергетика (нефть и газ) ----
    {"ticker": "XOM",  "sector": "Oil & Gas",            "names": ["ExxonMobil", "Exxon Mobil"]},
    {"ticker": "CVX",  "sector": "Oil & Gas",            "names": ["Chevron"]},
    {"ticker": "SHEL", "sector": "Oil & Gas",            "names": ["Shell"]},
    {"ticker": "BP",   "sector": "Oil & Gas",            "names": ["BP"]},
    {"ticker": "COP",  "sector": "Oil & Gas",            "names": ["ConocoPhillips"]},
    {"ticker": "OPEC", "sector": "Oil & Gas",            "names": ["OPEC", "OPEC+"]},

    # ---- Металлы и добыча ----
    {"ticker": "RIO",  "sector": "Metals & Mining",       "names": ["Rio Tinto"]},
    {"ticker": "BHP",  "sector": "Metals & Mining",       "names": ["BHP"]},
    {"ticker": "FCX",  "sector": "Metals & Mining",       "names": ["Freeport-McMoRan"]},
    {"ticker": "NEM",  "sector": "Metals & Mining",       "names": ["Newmont"]},
    {"ticker": "AA",   "sector": "Metals & Mining",       "names": ["Alcoa"]},
    {"ticker": "GOLD", "sector": "Metals & Mining",       "names": ["Barrick Gold"]},

    # ---- Оборонный сектор / Космос ----
    {"ticker": "RHM",  "sector": "Defense",       "names": ["Rheinmetall"]},
    {"ticker": "LMT",  "sector": "Defense",       "names": ["Lockheed Martin"]},
    {"ticker": "BA",   "sector": "Defense",       "names": ["Boeing"]},
    {"ticker": "NOC",  "sector": "Defense",       "names": ["Northrop Grumman"]},
    {"ticker": "RTX",  "sector": "Defense",       "names": ["RTX", "Raytheon"]},
    {"ticker": "SPCX", "sector": "Space",                 "names": ["SpaceX"]},

    # ---- Финансы / банки / платежи ----
    {"ticker": "JPM",  "sector": "Banking & Finance",        "names": ["JPMorgan", "JP Morgan"]},
    {"ticker": "GS",   "sector": "Banking & Finance",        "names": ["Goldman Sachs"]},
    {"ticker": "BAC",  "sector": "Banking & Finance",        "names": ["Bank of America"]},
    {"ticker": "MS",   "sector": "Banking & Finance",        "names": ["Morgan Stanley"]},
    {"ticker": "SPGI", "sector": "Banking & Finance",        "names": ["S&P Global"]},
    {"ticker": "V",    "sector": "Payments / Fintech",       "names": ["Visa"]},
    {"ticker": "MA",   "sector": "Payments / Fintech",       "names": ["Mastercard"]},
    {"ticker": "PYPL", "sector": "Payments / Fintech",       "names": ["PayPal"]},

    # ---- Здравоохранение / фарма / биотех ----
    {"ticker": "PFE",  "sector": "Healthcare",        "names": ["Pfizer"]},
    {"ticker": "JNJ",  "sector": "Healthcare",        "names": ["Johnson & Johnson"]},
    {"ticker": "LLY",  "sector": "Healthcare",        "names": ["Eli Lilly"]},
    {"ticker": "MRK",  "sector": "Healthcare",        "names": ["Merck"]},
    {"ticker": "UNH",  "sector": "Healthcare",        "names": ["UnitedHealth"]},
    {"ticker": "MRNA", "sector": "Healthcare",        "names": ["Moderna"]},

    # ---- Промышленность / инфраструктура ----
    {"ticker": "CAT",  "sector": "Industrials",         "names": ["Caterpillar"]},
    {"ticker": "HON",  "sector": "Industrials",         "names": ["Honeywell"]},
    {"ticker": "GE",   "sector": "Industrials",         "names": ["General Electric"]},

    # ---- Телеком / энергоснабжение ----
    {"ticker": "T",    "sector": "Telecom",                "names": ["AT&T"]},
    {"ticker": "VZ",   "sector": "Telecom",                "names": ["Verizon"]},
    {"ticker": "NEE",  "sector": "Utilities",        "names": ["NextEra Energy"]},

    # ---- Авиаперевозки / туризм ----
    {"ticker": "DAL",  "sector": "Airlines / Travel", "names": ["Delta Air Lines"]},
    {"ticker": "UAL",  "sector": "Airlines / Travel", "names": ["United Airlines"]},
    {"ticker": "ABNB", "sector": "Airlines / Travel", "names": ["Airbnb"]},

    # ---- Крипто ----
    {"ticker": "BTC",  "sector": "Cryptocurrencies",           "names": ["Bitcoin"]},
    {"ticker": "ETH",  "sector": "Cryptocurrencies",           "names": ["Ethereum"]},
    {"ticker": "COIN", "sector": "Cryptocurrencies",           "names": ["Coinbase"]},
    {"ticker": "MSTR", "sector": "Cryptocurrencies",           "names": ["MicroStrategy", "Strategy"]},

    # ---- Облигации / макро (не компании, а рыночные термины) ----
    {"ticker": "UST10Y","sector": "Bonds / Macro",     "names": ["10-year Treasury", "Treasury yield", "Treasury yields", "U.S. Treasury"]},
    {"ticker": "TLT",   "sector": "Bonds / Macro",     "names": ["Treasury bond", "long-term Treasury bond"]},
    {"ticker": "FED",   "sector": "Bonds / Macro",     "names": ["Federal Reserve", "Fed rate", "interest rate decision"]},

    # ---- ETF / индексы ----
    {"ticker": "SPY",  "sector": "ETFs / Indices",          "names": ["S&P 500"]},
    {"ticker": "QQQ",  "sector": "ETFs / Indices",          "names": ["Nasdaq 100", "Nasdaq Composite"]},
    {"ticker": "DJI",  "sector": "ETFs / Indices",          "names": ["Dow Jones"]},
    {"ticker": "VWCE", "sector": "ETFs / Indices",          "names": ["VWCE", "FTSE All-World"]},
]

# Оставляю прежнее имя переменной для обратной совместимости кода ниже
WATCHLIST = COMPANY_MAP

# Простые ключевые слова для механической оценки тональности (без ИИ)
POSITIVE_WORDS = [
    "surge", "surges", "rally", "rallies", "jump", "jumps", "gain", "gains",
    "soar", "soars", "beat", "beats", "record high", "climbs", "climb",
    "upgrade", "upgraded", "boost", "boosts", "rebound", "outperform",
    "bullish", "rises", "rise", "advance", "advances", "profit growth",
]
NEGATIVE_WORDS = [
    "plunge", "plunges", "crash", "crashes", "fall", "falls", "falling",
    "drop", "drops", "slump", "slumps", "miss", "misses", "downgrade",
    "downgraded", "sell-off", "selloff", "recession", "bearish", "warns",
    "warning", "cut", "cuts", "layoffs", "decline", "declines", "tumbles",
    "tumble", "loss", "losses",
]

# "Громкие" события, которые обычно двигают рынок сильнее рядовых новостей —
# используются для механической оценки важности (без ИИ).
HIGH_IMPACT_WORDS = [
    "acquisition", "acquires", "acquired", "merger", "merges", "takeover",
    "bankruptcy", "bankrupt", "files for chapter 11", "chapter 11",
    "resigns", "resignation", "steps down", "fired", "ousted",
    "investigation", "probe", "lawsuit", "sues", "fraud", "guilty",
    "settlement", "antitrust", "sanctions", "tariff", "tariffs",
    "recall", "recalls", "hack", "hacked", "breach", "data breach",
    "record high", "record low", "all-time high", "all-time low",
    "halted", "trading halt", "bailout", "default", "ipo", "spinoff",
    "spin-off", "stake", "buyback", "dividend hike", "profit warning",
    "guidance cut", "earnings beat", "earnings miss", "rate decision",
    "rate hike", "rate cut", "emergency meeting",
    # маркеры срочности и широкого обвала/ралли рынка
    "breaking", "breaking news", "just in", "developing story",
    "sell-off", "selloff", "rout", "market rout", "tech rout",
    "wipes out", "wiped out", "erases", "erased", "worst day",
    "worst week", "biggest drop", "biggest decline", "billions wiped",
    "extends losses", "broad decline", "market-wide", "across the board",
    # зеркальные формулировки для резкого РОСТА — раньше их не было,
    # и обвалы получали незаслуженно больше веса, чем ралли
    "market rally", "broad rally", "tech rally", "best day", "best week",
    "biggest jump", "biggest gain", "biggest rally", "adds billions",
    "extends gains", "broad gain", "surges to record", "soars to record",
    "melt-up", "risk-on rally",
]

# Скомпилированные regex с ГРАНИЦАМИ СЛОВА (\b) для всех трёх списков.
# Раньше поиск шёл через простое "подстрока ли это" (`w in text`), из-за
# чего "again" ложно засчитывался как позитивное слово "gain" (просто
# потому что буквы "gain" встречаются внутри "again"), а "stake" ложно
# срабатывал внутри "stakeholder(s)". \b решает обе проблемы разом.
def _compile_word_patterns(words):
    return [re.compile(r"\b" + re.escape(w) + r"\b") for w in words]


POSITIVE_PATTERNS = _compile_word_patterns(POSITIVE_WORDS)
NEGATIVE_PATTERNS = _compile_word_patterns(NEGATIVE_WORDS)
HIGH_IMPACT_PATTERNS = _compile_word_patterns(HIGH_IMPACT_WORDS)

# Маркеры макро/геополитических новостей — санкции, войны, выборы, политика
# центробанков и т.п. Такие новости часто НЕ имеют прямого биржевого
# "адресата" (конкретной компании/тикера) и не должны выдавать за
# инвестиционный сигнал то, что на самом деле является политическим фоном.
# Если новость упоминает конкретный тикер/компанию — она остаётся
# "рыночным сигналом" (content_type = market_signal), даже если заодно
# несёт геополитический оттенок.
MACRO_KEYWORDS = [
    "sanction", "sanctions", "tariff", "tariffs", "embargo", "geopolitic",
    "war", "invasion", "ceasefire", "cease-fire", "treaty", "diplomatic",
    "diplomacy", "election", "referendum", "coup", "protest", "protests",
    "parliament", "president", "prime minister", "government",
    "european union", "united nations", "g7", "g20", "opec",
    "central bank", "trade deal", "trade war", "immigration", "border",
    "military", "troops", "nuclear", "missile", "patriarch",
]
MACRO_PATTERNS = _compile_word_patterns(MACRO_KEYWORDS)


def is_macro_context(text: str, tickers: list) -> bool:
    """True, если новость похожа на макро/геополитический фон, а не на
    новость с конкретным биржевым "адресатом". Если у новости есть хотя бы
    один распознанный тикер/компания — считаем её рыночным сигналом,
    даже если она заодно касается политики."""
    if tickers:
        return False
    lower = text.lower()
    return any(p.search(lower) for p in MACRO_PATTERNS)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

NS = {
    "media": "http://search.yahoo.com/mrss/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "atom": "http://www.w3.org/2005/Atom",
}


# ---------------------------------------------------------------------------
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ---------------------------------------------------------------------------

# Признаки личных колонок-советов (MarketWatch "Retirement" / "Fix My Portfolio"
# / "The Moneyist" и подобные) — это не рыночные новости, а разбор одного
# письма читателя ("моя бабушка получит такую-то пенсию", "я продал..."),
# либо прямой ответ редакции на письмо читателя. Раньше список семейных слов
# и личных оборотов был слишком узким, и часть такого мусора проскакивала.
#
# Ключевой сигнал: реальные новостные заголовки (агентства, биржевые ленты)
# почти ВСЕГДА безличны и говорят о компаниях/рынках в третьем лице —
# они не начинаются с "I"/"We"/"My"/"Our". Личные колонки, наоборот, почти
# всегда начинаются именно так. `^(i|we|my|our)\b` — не подстрока: `\b`
# по обеим сторонам не даст ложно сработать на "IPO", "iPhone", "Inc" и т.п.
ADVICE_COLUMN_PATTERNS = [
    r"^['’\"]",                                    # заголовок начинается с кавычки
    r"^(i|i'm|i've|i'd|we|we're|we've|my|our)\b",  # повествование от первого лица — "I retired...", "My husband...", "We sold..."
    r"\b(my|our) (wife|husband|brother|sister|mother|father|mom|dad|son|daughter|parents?|"
    r"grandmother|grandfather|grandma|grandpa|aunt|uncle|cousin|boyfriend|girlfriend|"
    r"fianc[eé]e?|spouse|partner|roommate|in-laws?|ex-wife|ex-husband)\b",
    r"\bi'?m \d{2}\b",                              # "I'm 67 with a pension"
    r"\bwe'?re \d{2}\b",
    r"\b(should i|should we)\b",
    r"\bmy (pension|retirement|401\(?k\)?|social security|inheritance|savings|nest egg|ira)\b",
    r"\b(reader|readers)\b[^.]{0,25}\b(ask|asks|asked|wrote|writes|question)\b",  # ответы редакции на письма читателей
    r"\b(the moneyist|fix my portfolio|retirement weekly|ask the fool|dear penny|money mailbag|ask the hammer)\b",  # известные колонки-советы
]
ADVICE_COLUMN_RE = re.compile("|".join(ADVICE_COLUMN_PATTERNS), flags=re.IGNORECASE)


def is_advice_column(title: str) -> bool:
    """True, если заголовок похож на личную колонку-совет, а не на новость."""
    return bool(ADVICE_COLUMN_RE.search(title))


def strip_html(raw_html: str) -> str:
    """Убирает html-теги и лишние пробелы из текста."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def fetch_url(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_pubdate(raw: str):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except Exception:
        # некоторые ленты используют ISO-формат
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None


def find_image(item: ET.Element) -> str:
    """Пытается найти картинку в разных возможных местах RSS-элемента."""
    media_content = item.find("media:content", NS)
    if media_content is not None and media_content.get("url"):
        return media_content.get("url")

    media_thumb = item.find("media:thumbnail", NS)
    if media_thumb is not None and media_thumb.get("url"):
        return media_thumb.get("url")

    enclosure = item.find("enclosure")
    if enclosure is not None and enclosure.get("url"):
        enc_type = enclosure.get("type", "")
        if "image" in enc_type or enclosure.get("url", "").lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return enclosure.get("url")

    # иногда картинка спрятана прямо в description как <img src="...">
    desc = item.find("description")
    if desc is not None and desc.text:
        m = re.search(r'<img[^>]+src="([^"]+)"', desc.text)
        if m:
            return m.group(1)

    return ""


def detect_sentiment(text: str) -> str:
    lower = text.lower()
    pos = sum(1 for p in POSITIVE_PATTERNS if p.search(lower))
    neg = sum(1 for p in NEGATIVE_PATTERNS if p.search(lower))
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def calc_importance(title: str, description: str, tickers: list, pub_dt) -> float:
    """Механическая оценка "важности" новости (0-100+, без ИИ).

    Компоненты:
    - "громкие" слова из заголовка — самый весомый сигнал (BREAKING, sell-off,
      rout, обвал и т.д.), с учётом того, СКОЛЬКО раз слово встретилось, а не
      просто факта наличия — статья, где подряд идут "plunge... crash...
      sell-off... tumbles", явно тревожнее, чем с одним таким словом
    - те же слова в теле новости — тоже считаются, но с меньшим весом
    - сила тональности (позитив/негатив) по всему тексту, тоже с учётом частоты
    - количество упомянутых тикеров/компаний
    - бонус за свежесть (решает исход близких по прочим параметрам новостей)

    Это ЭВРИСТИКА, а не редакционная оценка значимости — она хорошо ловит
    очевидно резонансные новости (обвалы, слияния, банкротства, рекорды), но
    не заменяет собственное суждение о том, что действительно важно.
    """
    title_lower = title.lower()
    desc_lower = description.lower()
    full_lower = f"{title_lower} {desc_lower}"

    def weighted_hits(patterns, text, cap_per_word=3):
        """Считает суммарные вхождения слов из списка (по границам слова,
        не по подстроке), ограничивая вклад каждого отдельного слова —
        чтобы одно многократно повторяющееся слово не перекручивало счётчик."""
        total = 0
        for p in patterns:
            c = len(p.findall(text))
            if c:
                total += min(c, cap_per_word)
        return total

    high_impact_title = weighted_hits(HIGH_IMPACT_PATTERNS, title_lower)
    high_impact_desc = weighted_hits(HIGH_IMPACT_PATTERNS, desc_lower)
    sentiment_hits = weighted_hits(POSITIVE_PATTERNS, full_lower) + weighted_hits(NEGATIVE_PATTERNS, full_lower)

    score = 0.0
    score += high_impact_title * 26   # громкое слово в заголовке — сильнейший сигнал
    score += high_impact_desc * 12    # то же самое, но в теле — тоже важно, но слабее
    score += sentiment_hits * 5       # интенсивность тональности (частота, не факт наличия)
    score += min(len(tickers), 4) * 4 # упоминание нескольких компаний сразу

    # явный маркер срочности — отдельный жирный бонус
    if "breaking" in title_lower:
        score += 25

    # бонус за свежесть: чем новее, тем выше (плавно убывает за 48 часов)
    if pub_dt is not None:
        try:
            now = datetime.now(timezone.utc)
            pub_utc = pub_dt if pub_dt.tzinfo else pub_dt.replace(tzinfo=timezone.utc)
            hours_ago = max(0, (now - pub_utc).total_seconds() / 3600)
            freshness_bonus = max(0.0, 12 - hours_ago * 0.25)
            score += freshness_bonus
        except Exception:
            pass

    return round(score, 1)


# ---------------------------------------------------------------------------
# LLM-КЛАССИФИКАЦИЯ (опционально, через DeepSeek API)
# ---------------------------------------------------------------------------

def classify_batch_with_llm(batch_items):
    """Отправляет пачку новостей в DeepSeek API (эндпоинт OpenAI-совместимый,
    /chat/completions) и просит честно (с пониманием контекста) определить
    тональность, важность и тип новости.

    batch_items: список {"title": ..., "description": ...}
    Возвращает список {"sentiment": ..., "importance": ..., "content_type": ...}
    в том же порядке, или None при любой ошибке (сеть, лимиты, неожиданный
    формат ответа) — вызывающий код в этом случае просто оставляет
    эвристические значения.
    """
    if not DEEPSEEK_API_KEY:
        return None

    numbered = "\n\n".join(
        f"{i + 1}. Title: {it['title']}\nDescription: {(it['description'] or '')[:300]}"
        for i, it in enumerate(batch_items)
    )
    prompt = (
        "You are a financial news classifier for an investor. For each news "
        "item below, determine three fields.\n\n"
        "1) content_type — \"market_signal\" or \"macro_context\":\n"
        "   - \"market_signal\" if the news has a specific market target — "
        "a company, sector, or asset class whose price could realistically "
        "move because of this news.\n"
        "   - \"macro_context\" if it's geopolitics/politics/macro background "
        "WITHOUT a direct link to a specific security — sanctions against an "
        "individual, diplomacy, elections, military action, decisions by "
        "international bodies, etc. Such news matters for understanding the "
        "bigger picture but is NOT a trading signal by itself.\n\n"
        "2) sentiment — \"positive\", \"negative\" or \"neutral\", STRICTLY "
        "from the standpoint of likely impact on the market/asset, NOT from "
        "a political, moral, or humanitarian judgment of the event. These "
        "are different axes: a news item can be tragic or controversial in "
        "substance while being neutral or even positive for a specific "
        "asset — and vice versa. If a news item is \"macro_context\" and has "
        "no clear one-sided market effect, honestly mark it \"neutral\" "
        "rather than trying to score its political significance.\n"
        "   Calibration examples:\n"
        "   - \"EU declines to sanction [a religious/political figure]\" → "
        "content_type=macro_context (no single stock price this directly "
        "acts on), sentiment=neutral (absence of escalation is not a strong "
        "signal up or down for any specific asset), NOT negative just "
        "because the underlying event may be morally contentious.\n"
        "   - \"EU imports record volumes of LNG from Russia\" → "
        "content_type=macro_context (no single ticker target in a broad "
        "trend), sentiment=neutral-to-positive for the energy market (more "
        "gas supply), not \"negative\" just because the topic involves "
        "Russia.\n"
        "   - \"Nvidia surges to record high\" → content_type=market_signal, "
        "sentiment=positive.\n\n"
        "3) importance — a number from 0 to 100: how much this news item can "
        "realistically move the market or specific stocks (0 = routine, "
        "100 = an event on the scale of a major bank's collapse or the "
        "start of a war). Geopolitical news can also score high importance "
        "if it's genuinely large in scale — importance measures the scale "
        "of the event, not whether it's a trading signal (that's separately "
        "content_type).\n\n"
        f"News items:\n{numbered}\n\n"
        "Respond with STRICTLY a JSON object, no prose outside the JSON, "
        "in this exact shape, with \"results\" containing one entry per news "
        "item above IN THE SAME ORDER:\n"
        '{"results": [{"content_type": "market_signal", "sentiment": "positive", "importance": 42}, ...]}'
    )

    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  [!] Ошибка обращения к DeepSeek API: {e}")
        return None

    try:
        text = raw["choices"][0]["message"]["content"].strip()
        # на случай, если модель всё же обернула JSON в ```json ... ```
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        results = parsed.get("results") if isinstance(parsed, dict) else parsed
        if isinstance(results, list) and len(results) == len(batch_items):
            return results
        print("  [!] LLM вернул неожиданный формат ответа — использую эвристику для этой партии")
        return None
    except Exception as e:
        print(f"  [!] Не удалось разобрать ответ DeepSeek API: {e}")
        return None


def classify_items_with_llm(items):
    """Прогоняет items через classify_batch_with_llm пачками, обновляя
    sentiment/importance/content_type на месте. Новости, для которых LLM
    не ответил (партия целиком упала по сети/лимитам), сохраняют
    эвристические значения."""
    classified = 0
    for start in range(0, len(items), LLM_BATCH_SIZE):
        batch = items[start:start + LLM_BATCH_SIZE]
        batch_input = [{"title": it["title"], "description": it["description"]} for it in batch]
        result = classify_batch_with_llm(batch_input)
        if result is None:
            continue  # эта партия — остаётся эвристика

        for item, res in zip(batch, result):
            sentiment = res.get("sentiment")
            importance = res.get("importance")
            content_type = res.get("content_type")
            if sentiment in ("positive", "negative", "neutral"):
                item["sentiment"] = sentiment
            if isinstance(importance, (int, float)):
                item["importance"] = round(float(importance), 1)
            if content_type in ("market_signal", "macro_context"):
                item["content_type"] = content_type
            item["llm_classified"] = True
        classified += len(batch)

    print(f"  Классифицировано через DeepSeek: {classified}/{len(items)} новостей "
          f"(остальные — по локальной эвристике)")


def detect_watchlist_matches(text: str) -> list:
    """Ищет в тексте и тикеры, и названия компаний из COMPANY_MAP.
    Возвращает список уникальных {"ticker": ..., "sector": ...}.

    Правила, чтобы избежать ложных срабатываний:
    1) Тикеры длиной 3+ символа ищем с учётом регистра (в реальных текстах
       тикеры пишут заглавными — NVDA, RIO, CAT). Так короткие тикеры вроде
       "CAT" не путаются со случайным словом "cat" в обычном тексте.
    2) Тикеры длиной 1-2 символа (F, T, V, MA, GE, AA...) почти всегда
       совпадают с обычными словами/буквами/аббревиатурами — для них поиск
       по самому тикеру ОТКЛЮЧЁН, ищем только по названию компании
       ("Ford", "AT&T", "Mastercard" и т.д.).
    3) Название компании ищем без учёта регистра, т.к. в заголовках оно
       может стоять и в начале предложения.
    """
    found = {}
    for entry in COMPANY_MAP:
        ticker = entry["ticker"]
        matched = False

        if len(ticker) >= 3 and re.search(r"\b" + re.escape(ticker) + r"\b", text):
            matched = True

        if not matched:
            for name in entry["names"]:
                if re.search(r"\b" + re.escape(name) + r"\b", text, flags=re.IGNORECASE):
                    matched = True
                    break

        if matched:
            found[ticker] = entry["sector"]
    return [{"ticker": t, "sector": s} for t, s in found.items()]


# ---------------------------------------------------------------------------
# ОСНОВНАЯ ЛОГИКА
# ---------------------------------------------------------------------------

def parse_feed(feed_name: str, url: str) -> list:
    items_out = []
    try:
        raw = fetch_url(url)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"[!] Не удалось загрузить {feed_name}: {e}")
        return items_out

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"[!] Ошибка парсинга XML у {feed_name}: {e}")
        return items_out

    # RSS 2.0: channel/item ; Atom: entry
    channel = root.find("channel")
    entries = channel.findall("item") if channel is not None else root.findall("atom:entry", NS)

    for item in entries:
        title_el = item.find("title")
        title = strip_html(title_el.text) if title_el is not None and title_el.text else ""
        if not title:
            continue

        if is_advice_column(title):
            continue

        link_el = item.find("link")
        link = ""
        if link_el is not None:
            link = link_el.text or link_el.get("href", "")

        desc_el = item.find("description")
        if desc_el is None:
            desc_el = item.find("content:encoded", NS)
        description = strip_html(desc_el.text) if desc_el is not None and desc_el.text else ""
        if len(description) > 240:
            description = description[:237].rsplit(" ", 1)[0] + "…"

        pub_el = item.find("pubDate")
        if pub_el is None:
            pub_el = item.find("atom:published", NS)
        pub_dt = parse_pubdate(pub_el.text) if pub_el is not None and pub_el.text else None

        image = find_image(item)
        full_text = f"{title} {description}"
        matches = detect_watchlist_matches(full_text)
        tickers = [m["ticker"] for m in matches]

        items_out.append({
            "title": title,
            "link": link.strip() if link else "",
            "description": description,
            "source": feed_name,
            "image": image,
            "published": pub_dt.isoformat() if pub_dt else None,
            "published_display": pub_dt.strftime("%d.%m %H:%M") if pub_dt else "—",
            "sentiment": detect_sentiment(full_text),
            "tickers": tickers,
            "sectors": sorted(set(m["sector"] for m in matches)),
            "importance": calc_importance(title, description, tickers, pub_dt),
            "content_type": "macro_context" if is_macro_context(full_text, tickers) else "market_signal",
            "llm_classified": False,
        })

    return items_out


def build_summary(all_items: list) -> dict:
    # Тональность считаем ТОЛЬКО по новостям с конкретным биржевым "адресатом"
    # (content_type == market_signal). Макро/геополитические новости — это
    # фон, а не инвестиционный сигнал, и не должны перекашивать общий
    # рыночный настрой (иначе новость про санкции против кого-то может
    # утянуть "Беглую аналитику" в минус, хотя по сути это не сигнал по
    # конкретной бумаге).
    signal_items = [i for i in all_items if i.get("content_type", "market_signal") == "market_signal"]
    macro_items = [i for i in all_items if i.get("content_type") == "macro_context"]

    pos = sum(1 for i in signal_items if i["sentiment"] == "positive")
    neg = sum(1 for i in signal_items if i["sentiment"] == "negative")
    neu = sum(1 for i in signal_items if i["sentiment"] == "neutral")

    ticker_counts = {}
    for i in all_items:
        for t in i["tickers"]:
            ticker_counts[t] = ticker_counts.get(t, 0) + 1
    top_tickers = sorted(ticker_counts.items(), key=lambda x: -x[1])[:6]

    sector_counts = {}
    for i in all_items:
        for sec in i.get("sectors", []):
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

    source_counts = {}
    for i in all_items:
        source_counts[i["source"]] = source_counts.get(i["source"], 0) + 1

    return {
        "total": len(all_items),
        "signal_total": len(signal_items),
        "macro_total": len(macro_items),
        "positive": pos,
        "negative": neg,
        "neutral": neu,
        "top_tickers": [{"ticker": t, "count": c} for t, c in top_tickers],
        "sectors": sorted(sector_counts.keys()),
        "source_counts": source_counts,
    }


# ---------------------------------------------------------------------------
# КОТИРОВКИ ОСНОВНЫХ ИНДЕКСОВ
# ---------------------------------------------------------------------------

# Неофициальный, но широко используемый в open-source проектах эндпоинт
# Yahoo Finance — ключ не нужен, но это НЕофициальный API: Yahoo может
# изменить его в любой момент без предупреждения. Поэтому вся эта секция
# обёрнута в try/except с тихим пропуском — если формат ответа изменится
# или эндпоинт станет недоступен, дашборд просто не покажет блок
# котировок, остальная часть скрипта продолжит работать как обычно.
INDEX_QUOTES = [
    # --- Индексы США ---
    {"symbol": "^GSPC", "name": "S&P 500"},
    {"symbol": "^DJI",  "name": "Dow Jones"},
    {"symbol": "^IXIC", "name": "Nasdaq Composite"},
    {"symbol": "^NDX",  "name": "Nasdaq 100"},
    {"symbol": "^RUT",  "name": "Russell 2000"},
    {"symbol": "^NYA",  "name": "NYSE Composite"},
    {"symbol": "^VIX",  "name": "VIX (Fear Index)"},

    # --- Международные индексы (платформа для глобальной аудитории) ---
    {"symbol": "^FTSE",     "name": "FTSE 100 (UK)"},
    {"symbol": "^GDAXI",    "name": "DAX (Germany)"},
    {"symbol": "^STOXX50E", "name": "Euro Stoxx 50"},
    {"symbol": "^N225",     "name": "Nikkei 225 (Japan)"},
    {"symbol": "^HSI",      "name": "Hang Seng (Hong Kong)"},

    # --- Сырьё, крипто, облигации ---
    {"symbol": "GC=F",    "name": "Gold (futures)"},
    {"symbol": "CL=F",    "name": "WTI Crude Oil (futures)"},
    {"symbol": "BTC-USD", "name": "Bitcoin"},
    {"symbol": "^TNX",    "name": "10-Year US Treasury Yield", "unit": "yield_pct", "scale": 0.1},
]


def fetch_index_quote(symbol: str, scale: float = 1.0):
    """Возвращает {"price", "change_abs", "change_pct"} для тикера индекса
    или None при любой ошибке (сеть, неожиданный формат ответа и т.п.).

    scale: Yahoo хранит доходность облигаций (^TNX) в масштабе ×10 от
    реальной ставки (42.85 вместо 4.285%) — для таких тикеров передаём
    scale=0.1, чтобы показать настоящее значение. На change_pct это не
    влияет: это отношение, оно не зависит от масштаба.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        raw = fetch_url(url, timeout=10)
        data = json.loads(raw)
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or prev_close in (None, 0):
            return None
        change_abs = price - prev_close
        change_pct = (change_abs / prev_close) * 100
        return {
            "price": round(price * scale, 2),
            "change_abs": round(change_abs * scale, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        print(f"  [!] Не удалось получить котировку {symbol}: {e}")
        return None


def fetch_all_indices() -> list:
    print("\nПодтягиваю котировки основных индексов...")
    results = []
    for item in INDEX_QUOTES:
        quote = fetch_index_quote(item["symbol"], scale=item.get("scale", 1.0))
        if quote:
            results.append({
                "name": item["name"],
                "symbol": item["symbol"],
                "unit": item.get("unit", "index"),
                **quote,
            })
        else:
            print(f"  пропускаю {item['name']} — данные недоступны")
    print(f"  Получено котировок: {len(results)}/{len(INDEX_QUOTES)}")
    return results


def main():
    print("Собираю новости...")
    all_items = []
    for feed in FEEDS:
        print(f"  → {feed['name']}")
        items = parse_feed(feed["name"], feed["url"])
        print(f"    получено: {len(items)}")
        all_items.extend(items)

    # сортировка по дате (свежие сверху), без даты — в конец
    all_items.sort(
        key=lambda i: i["published"] or "0000-00-00T00:00:00",
        reverse=True,
    )

    # простая дедупликация по первым словам заголовка
    seen = set()
    deduped = []
    for i in all_items:
        key = i["title"].lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(i)

    deduped = deduped[:MAX_ITEMS]

    if DEEPSEEK_API_KEY:
        print(f"\nAPI-ключ найден — уточняю тональность и важность через DeepSeek ({DEEPSEEK_MODEL})...")
        classify_items_with_llm(deduped)
    else:
        print("\nDEEPSEEK_API_KEY не задан — использую локальную эвристику по ключевым словам.")
        print("(Подробнее о подключении LLM-классификации — в README.md)")

    summary = build_summary(deduped)
    indices = fetch_all_indices()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at_display": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "summary": summary,
        "indices": indices,
        "items": deduped,
    }

    out_path = "news_data.js"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("// Файл сгенерирован автоматически скриптом fetch_news.py — не редактируйте вручную\n")
        f.write("const NEWS_DATA = ")
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"\nГотово! Собрано новостей: {len(deduped)}")
    print(f"Данные сохранены в {out_path}")
    print("Откройте (или обновите) news_dashboard.html в браузере.")


if __name__ == "__main__":
    main()
