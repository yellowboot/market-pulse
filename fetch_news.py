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

# --- Опциональная LLM-классификация (Claude API) ---------------------------
# Если задан ANTHROPIC_API_KEY — тональность и важность каждой новости
# определяет Claude (понимает реальный смысл: "отмена санкций" — позитив,
# "рост издержек" — негатив, даже если отдельные слова говорят обратное).
# Если ключа нет или запрос не прошёл — используется локальная эвристика
# по ключевым словам (detect_sentiment / calc_importance ниже), как раньше.
#
# Как задать ключ (ничего не хардкодим в файле — так безопаснее):
#   macOS/Linux:  export ANTHROPIC_API_KEY="sk-ant-..."
#   Windows (cmd): set ANTHROPIC_API_KEY=sk-ant-...
# Подробности — в README.md.
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"  # самая дешёвая модель — этого достаточно для классификации
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
    {"ticker": "NVDA", "sector": "Полупроводники",         "names": ["Nvidia"]},
    {"ticker": "AVGO", "sector": "Полупроводники",         "names": ["Broadcom"]},
    {"ticker": "MRVL", "sector": "Полупроводники",         "names": ["Marvell"]},
    {"ticker": "MU",   "sector": "Полупроводники",         "names": ["Micron"]},
    {"ticker": "ON",   "sector": "Полупроводники",         "names": ["ON Semiconductor", "Onsemi"]},
    {"ticker": "ALAB", "sector": "Полупроводники",         "names": ["Astera Labs"]},
    {"ticker": "AMAT", "sector": "Полупроводники",         "names": ["Applied Materials"]},
    {"ticker": "ASML", "sector": "Полупроводники",         "names": ["ASML"]},
    {"ticker": "INTC", "sector": "Полупроводники",         "names": ["Intel"]},
    {"ticker": "AMD",  "sector": "Полупроводники",         "names": ["AMD", "Advanced Micro Devices"]},
    {"ticker": "QCOM", "sector": "Полупроводники",         "names": ["Qualcomm"]},
    {"ticker": "TSM",  "sector": "Полупроводники",         "names": ["TSMC", "Taiwan Semiconductor"]},

    # ---- ПО / AI / Кибербезопасность / Cloud ----
    {"ticker": "CRWD", "sector": "Кибербезопасность",      "names": ["CrowdStrike"]},
    {"ticker": "NET",  "sector": "Кибербезопасность",      "names": ["Cloudflare"]},
    {"ticker": "PANW", "sector": "Кибербезопасность",      "names": ["Palo Alto Networks"]},
    {"ticker": "FTNT", "sector": "Кибербезопасность",      "names": ["Fortinet"]},
    {"ticker": "PLTR", "sector": "ПО / AI-аналитика",      "names": ["Palantir"]},
    {"ticker": "SOUN", "sector": "ПО / AI-аналитика",      "names": ["SoundHound"]},
    {"ticker": "CRM",  "sector": "ПО / Cloud",             "names": ["Salesforce"]},
    {"ticker": "NOW",  "sector": "ПО / Cloud",             "names": ["ServiceNow"]},
    {"ticker": "SNOW", "sector": "ПО / Cloud",             "names": ["Snowflake"]},
    {"ticker": "ADBE", "sector": "ПО / Cloud",             "names": ["Adobe"]},
    {"ticker": "ORCL", "sector": "ПО / Cloud",             "names": ["Oracle"]},

    # ---- Big Tech ----
    {"ticker": "MSFT", "sector": "Big Tech",               "names": ["Microsoft"]},
    {"ticker": "GOOGL","sector": "Big Tech",               "names": ["Alphabet", "Google"]},
    {"ticker": "AAPL", "sector": "Big Tech",               "names": ["Apple"]},
    {"ticker": "AMZN", "sector": "Big Tech",               "names": ["Amazon"]},
    {"ticker": "META", "sector": "Big Tech",               "names": ["Meta", "Facebook"]},

    # ---- Электромобили / Автопром ----
    {"ticker": "TSLA", "sector": "Автопром / EV",          "names": ["Tesla"]},
    {"ticker": "RIVN", "sector": "Автопром / EV",          "names": ["Rivian"]},
    {"ticker": "F",    "sector": "Автопром / EV",          "names": ["Ford"]},
    {"ticker": "GM",   "sector": "Автопром / EV",          "names": ["General Motors"]},
    {"ticker": "VOW3", "sector": "Автопром / EV",          "names": ["Volkswagen"]},
    {"ticker": "TM",   "sector": "Автопром / EV",          "names": ["Toyota"]},
    {"ticker": "BYDDY","sector": "Автопром / EV",          "names": ["BYD"]},

    # ---- Потребительский сектор (реальный бизнес: еда, ритейл, бренды) ----
    {"ticker": "NKE",  "sector": "Потребительский сектор", "names": ["Nike"]},
    {"ticker": "KO",   "sector": "Потребительский сектор", "names": ["Coca-Cola"]},
    {"ticker": "PEP",  "sector": "Потребительский сектор", "names": ["PepsiCo"]},
    {"ticker": "MCD",  "sector": "Потребительский сектор", "names": ["McDonald's", "McDonalds"]},
    {"ticker": "SBUX", "sector": "Потребительский сектор", "names": ["Starbucks"]},
    {"ticker": "WMT",  "sector": "Потребительский сектор", "names": ["Walmart"]},
    {"ticker": "COST", "sector": "Потребительский сектор", "names": ["Costco"]},
    {"ticker": "PG",   "sector": "Потребительский сектор", "names": ["Procter & Gamble"]},
    {"ticker": "DIS",  "sector": "Медиа / развлечения",    "names": ["Disney"]},
    {"ticker": "NFLX", "sector": "Медиа / развлечения",    "names": ["Netflix"]},

    # ---- Энергетика (нефть и газ) ----
    {"ticker": "XOM",  "sector": "Нефть и газ",            "names": ["ExxonMobil", "Exxon Mobil"]},
    {"ticker": "CVX",  "sector": "Нефть и газ",            "names": ["Chevron"]},
    {"ticker": "SHEL", "sector": "Нефть и газ",            "names": ["Shell"]},
    {"ticker": "BP",   "sector": "Нефть и газ",            "names": ["BP"]},
    {"ticker": "COP",  "sector": "Нефть и газ",            "names": ["ConocoPhillips"]},
    {"ticker": "OPEC", "sector": "Нефть и газ",            "names": ["OPEC", "OPEC+"]},

    # ---- Металлы и добыча ----
    {"ticker": "RIO",  "sector": "Металлы и добыча",       "names": ["Rio Tinto"]},
    {"ticker": "BHP",  "sector": "Металлы и добыча",       "names": ["BHP"]},
    {"ticker": "FCX",  "sector": "Металлы и добыча",       "names": ["Freeport-McMoRan"]},
    {"ticker": "NEM",  "sector": "Металлы и добыча",       "names": ["Newmont"]},
    {"ticker": "AA",   "sector": "Металлы и добыча",       "names": ["Alcoa"]},
    {"ticker": "GOLD", "sector": "Металлы и добыча",       "names": ["Barrick Gold"]},

    # ---- Оборонный сектор / Космос ----
    {"ticker": "RHM",  "sector": "Оборонный сектор",       "names": ["Rheinmetall"]},
    {"ticker": "LMT",  "sector": "Оборонный сектор",       "names": ["Lockheed Martin"]},
    {"ticker": "BA",   "sector": "Оборонный сектор",       "names": ["Boeing"]},
    {"ticker": "NOC",  "sector": "Оборонный сектор",       "names": ["Northrop Grumman"]},
    {"ticker": "RTX",  "sector": "Оборонный сектор",       "names": ["RTX", "Raytheon"]},
    {"ticker": "SPCX", "sector": "Космос",                 "names": ["SpaceX"]},

    # ---- Финансы / банки / платежи ----
    {"ticker": "JPM",  "sector": "Банки и финансы",        "names": ["JPMorgan", "JP Morgan"]},
    {"ticker": "GS",   "sector": "Банки и финансы",        "names": ["Goldman Sachs"]},
    {"ticker": "BAC",  "sector": "Банки и финансы",        "names": ["Bank of America"]},
    {"ticker": "MS",   "sector": "Банки и финансы",        "names": ["Morgan Stanley"]},
    {"ticker": "SPGI", "sector": "Банки и финансы",        "names": ["S&P Global"]},
    {"ticker": "V",    "sector": "Платежи / финтех",       "names": ["Visa"]},
    {"ticker": "MA",   "sector": "Платежи / финтех",       "names": ["Mastercard"]},
    {"ticker": "PYPL", "sector": "Платежи / финтех",       "names": ["PayPal"]},

    # ---- Здравоохранение / фарма / биотех ----
    {"ticker": "PFE",  "sector": "Здравоохранение",        "names": ["Pfizer"]},
    {"ticker": "JNJ",  "sector": "Здравоохранение",        "names": ["Johnson & Johnson"]},
    {"ticker": "LLY",  "sector": "Здравоохранение",        "names": ["Eli Lilly"]},
    {"ticker": "MRK",  "sector": "Здравоохранение",        "names": ["Merck"]},
    {"ticker": "UNH",  "sector": "Здравоохранение",        "names": ["UnitedHealth"]},
    {"ticker": "MRNA", "sector": "Здравоохранение",        "names": ["Moderna"]},

    # ---- Промышленность / инфраструктура ----
    {"ticker": "CAT",  "sector": "Промышленность",         "names": ["Caterpillar"]},
    {"ticker": "HON",  "sector": "Промышленность",         "names": ["Honeywell"]},
    {"ticker": "GE",   "sector": "Промышленность",         "names": ["General Electric"]},

    # ---- Телеком / энергоснабжение ----
    {"ticker": "T",    "sector": "Телеком",                "names": ["AT&T"]},
    {"ticker": "VZ",   "sector": "Телеком",                "names": ["Verizon"]},
    {"ticker": "NEE",  "sector": "Энергоснабжение",        "names": ["NextEra Energy"]},

    # ---- Авиаперевозки / туризм ----
    {"ticker": "DAL",  "sector": "Авиаперевозки / туризм", "names": ["Delta Air Lines"]},
    {"ticker": "UAL",  "sector": "Авиаперевозки / туризм", "names": ["United Airlines"]},
    {"ticker": "ABNB", "sector": "Авиаперевозки / туризм", "names": ["Airbnb"]},

    # ---- Крипто ----
    {"ticker": "BTC",  "sector": "Криптовалюты",           "names": ["Bitcoin"]},
    {"ticker": "ETH",  "sector": "Криптовалюты",           "names": ["Ethereum"]},
    {"ticker": "COIN", "sector": "Криптовалюты",           "names": ["Coinbase"]},
    {"ticker": "MSTR", "sector": "Криптовалюты",           "names": ["MicroStrategy", "Strategy"]},

    # ---- Облигации / макро (не компании, а рыночные термины) ----
    {"ticker": "UST10Y","sector": "Облигации / макро",     "names": ["10-year Treasury", "Treasury yield", "Treasury yields", "U.S. Treasury"]},
    {"ticker": "TLT",   "sector": "Облигации / макро",     "names": ["Treasury bond", "long-term Treasury bond"]},
    {"ticker": "FED",   "sector": "Облигации / макро",     "names": ["Federal Reserve", "Fed rate", "interest rate decision"]},

    # ---- ETF / индексы ----
    {"ticker": "SPY",  "sector": "ETF / индексы",          "names": ["S&P 500"]},
    {"ticker": "QQQ",  "sector": "ETF / индексы",          "names": ["Nasdaq 100", "Nasdaq Composite"]},
    {"ticker": "DJI",  "sector": "ETF / индексы",          "names": ["Dow Jones"]},
    {"ticker": "VWCE", "sector": "ETF / индексы",          "names": ["VWCE", "FTSE All-World"]},
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
# LLM-КЛАССИФИКАЦИЯ (опционально, через Claude API)
# ---------------------------------------------------------------------------

def classify_batch_with_llm(batch_items):
    """Отправляет пачку новостей в Claude API и просит честно (с пониманием
    контекста) определить тональность, важность и тип новости.

    batch_items: список {"title": ..., "description": ...}
    Возвращает список {"sentiment": ..., "importance": ..., "content_type": ...}
    в том же порядке, или None при любой ошибке (сеть, лимиты, неожиданный
    формат ответа) — вызывающий код в этом случае просто оставляет
    эвристические значения.
    """
    if not ANTHROPIC_API_KEY:
        return None

    numbered = "\n\n".join(
        f"{i + 1}. Заголовок: {it['title']}\nОписание: {(it['description'] or '')[:300]}"
        for i, it in enumerate(batch_items)
    )
    prompt = (
        "Ты — классификатор финансовых новостей для инвестора. Для каждой "
        "новости ниже определи три поля.\n\n"
        "1) content_type — \"market_signal\" или \"macro_context\":\n"
        "   - \"market_signal\", если у новости есть конкретный биржевой "
        "\"адресат\" — компания, сектор, класс активов, чья цена реально "
        "может сдвинуться из-за этой новости.\n"
        "   - \"macro_context\", если это геополитика/политика/макро-фон "
        "БЕЗ прямой привязки к конкретной бумаге — санкции против "
        "физического лица, дипломатия, выборы, военные действия, решения "
        "международных органов и т.п. Такие новости важны для понимания "
        "картины мира, но НЕ являются торговым сигналом сами по себе.\n\n"
        "2) sentiment — \"positive\", \"negative\" или \"neutral\", СТРОГО "
        "с точки зрения вероятного влияния на рынок/актив, а НЕ с точки "
        "зрения политической, моральной или гуманитарной оценки события. "
        "Это разные оси: новость может быть трагичной или спорной по сути "
        "и при этом нейтральной или даже позитивной для конкретного актива "
        "— и наоборот. Если новость помечена как \"macro_context\" и не "
        "имеет ясного одностороннего рыночного эффекта, честно ставь "
        "\"neutral\", а не пытайся оценить её политическую значимость.\n"
        "   Примеры, чтобы откалибровать критерий:\n"
        "   - \"ЕС не вводит санкции против главы РПЦ и главы 'Лукойла'\" "
        "→ content_type=macro_context (нет цены акции, на которую это "
        "прямо действует), sentiment=neutral (отсутствие эскалации — "
        "не сильный сигнал ни вверх, ни вниз для конкретного актива), "
        "НЕ negative, даже если само событие может восприниматься как "
        "морально неоднозначное.\n"
        "   - \"ЕС импортировал рекордный объём СПГ из России\" → "
        "content_type=macro_context (нет единственного тикера-адресата "
        "в общем потоке), sentiment=neutral-to-positive для энергетического "
        "рынка (больше предложения газа), а не \"негатив\" просто потому, "
        "что тема связана с Россией.\n"
        "   - \"Nvidia surges to record high\" → content_type=market_signal, "
        "sentiment=positive.\n\n"
        "3) importance — число от 0 до 100: насколько новость способна "
        "реально двигать рынок или конкретные акции (0 — рутина, "
        "100 — событие уровня банкротства крупного банка или начала войны). "
        "Геополитические новости тоже могут получать высокий importance, "
        "если они действительно масштабны — importance измеряет масштаб "
        "события, а не наличие торгового сигнала (это отдельно в content_type).\n\n"
        f"Новости:\n{numbered}\n\n"
        "Ответь СТРОГО в виде JSON-массива, без пояснений вне JSON, "
        "в том же порядке, в формате:\n"
        '[{"content_type": "market_signal", "sentiment": "positive", "importance": 42}, ...]'
    )

    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        print(f"  [!] Ошибка обращения к Claude API: {e}")
        return None

    try:
        text = "".join(
            block.get("text", "") for block in raw.get("content", [])
            if block.get("type") == "text"
        ).strip()
        # на случай, если модель обернула JSON в ```json ... ```
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        if isinstance(parsed, list) and len(parsed) == len(batch_items):
            return parsed
        print("  [!] LLM вернул неожиданный формат ответа — использую эвристику для этой партии")
        return None
    except Exception as e:
        print(f"  [!] Не удалось разобрать ответ Claude API: {e}")
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

    print(f"  Классифицировано через Claude: {classified}/{len(items)} новостей "
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
    {"symbol": "^VIX",  "name": "VIX (индекс страха)"},

    # --- Международные индексы (платформа для глобальной аудитории) ---
    {"symbol": "^FTSE",     "name": "FTSE 100 (UK)"},
    {"symbol": "^GDAXI",    "name": "DAX (Германия)"},
    {"symbol": "^STOXX50E", "name": "Euro Stoxx 50"},
    {"symbol": "^N225",     "name": "Nikkei 225 (Япония)"},
    {"symbol": "^HSI",      "name": "Hang Seng (Гонконг)"},

    # --- Сырьё, крипто, облигации ---
    {"symbol": "GC=F",    "name": "Золото (фьючерс)"},
    {"symbol": "CL=F",    "name": "Нефть WTI (фьючерс)"},
    {"symbol": "BTC-USD", "name": "Bitcoin"},
    {"symbol": "^TNX",    "name": "Доходность 10-летних US Treasury", "unit": "yield_pct", "scale": 0.1},
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

    if ANTHROPIC_API_KEY:
        print(f"\nAPI-ключ найден — уточняю тональность и важность через Claude ({ANTHROPIC_MODEL})...")
        classify_items_with_llm(deduped)
    else:
        print("\nANTHROPIC_API_KEY не задан — использую локальную эвристику по ключевым словам.")
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
