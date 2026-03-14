from __future__ import annotations

import html
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
try:
    import googlenewsdecoder
except ImportError:
    googlenewsdecoder = None

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
OUTPUT_DIR = ROOT / "dist"
TIMEZONE = ZoneInfo("Europe/Berlin")
TARGET_LAT = 50.1521
TARGET_LON = 8.6118
NEWS_WINDOW_HOURS = 24
HOLIDAY_LOOKAHEAD_DAYS = 45
REGION_CODE = "DE-HE"
COUNTRY_CODE = "DE"

CATEGORY_CONFIGS = [
    {
        "key": "commute",
        "label": "Movilidad y huelgas",
        "query": 'Frankfurt (RMV OR VGF OR U7 OR "U-Bahn" OR "S-Bahn" OR Nordwest OR Ostend OR Streik OR Sperrung OR Ostbahnhof)',
        "description": "Lo que puede afectar a desplazamientos diarios por Frankfurt.",
        "limit": 6,
    },
    {
        "key": "alerts",
        "label": "Alertas y emergencias",
        "query": 'Frankfurt (Warnung OR Alarm OR Polizei OR Feuerwehr OR Unwetter OR Bombenentschaerfung OR Sperrung)',
        "description": "Incidentes operativos, meteorologia y avisos criticos.",
        "limit": 5,
    },
    {
        "key": "city",
        "label": "Ciudad y barrio",
        "query": '"Frankfurt am Main" (Stadt OR Verkehr OR Baustelle OR Rathaus OR Nordwest OR Innenstadt OR Ostend)',
        "description": "Noticias de ciudad con impacto practico para residentes.",
        "limit": 5,
    },
    {
        "key": "social",
        "label": "Social, vivienda y contexto",
        "query": 'Frankfurt (Wohnen OR Miete OR Bildung OR Gesundheit OR Gesellschaft OR Kultur OR Wirtschaft)',
        "description": "Temas de entorno que ayudan a anticipar ambiente y conversacion local.",
        "limit": 5,
    },
    {
        "key": "germany_economy",
        "label": "Alemania: economia y finanzas",
        "query": 'Deutschland (Wirtschaft OR Finanzen OR DAX OR Banken OR Inflation OR Unternehmen OR Boerse)',
        "description": "Panorama de Alemania para economia, finanzas y empresa.",
        "limit": 5,
    },
    {
        "key": "germany_culture",
        "label": "Alemania: cultura y conciertos",
        "query": 'Deutschland (Kultur OR Konzert OR Festival OR Oper OR Ausstellung OR Museum OR Tournee)',
        "description": "Cultura, conciertos y agenda amplia en Alemania.",
        "limit": 5,
    },
]

SPORTS_LOOKAHEAD_DAYS = 14
SPORTS_LOOKBACK_DAYS = 10
ESPN_TIMEZONE = ZoneInfo("America/New_York")
GOOGLE_CONTEXT_CATEGORIES = {"commute", "alerts"}
INITIALIZATION_KEYWORDS = {
    "streik",
    "huelga",
    "paro",
    "ausstand",
    "lockout",
    "sperrung",
    "corte",
}
INITIALIZATION_PREFIXES = ("seit", "ab", "desde", "a partir", "starting", "since", "desde el", "desde la", "empieza", "empiezan", "entra", "entrara")
INITIALIZATION_PREFIXES += ("am", "vom", "desde hoy", "ab dem", "ab dem", "ab dem", "starting from", "desde el", "desde mañana", "desde manana")
DATE_DETECTION_RE = re.compile(
    r"\b(?:\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\d{1,2}\s+(?:de\s+)?(?:ene|enero|feb|febrero|mar|marzo|abr|abril|may|mayo|jun|junio|jul|julio|ago|agosto|sep|sept|septiembre|setiembre|oct|octubre|nov|noviembre|dic|diciembre|jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december))\b|"
    r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
GOOGLE_ARTICLE_CACHE: dict[str, tuple[str | None, str]] = {}

TEAM_SOURCES = {
    "Real Madrid": {
        "fixtures_url": "https://www.espn.com/soccer/team/fixtures/_/id/86/real-madrid",
        "results_url": "https://www.espn.com/soccer/team/results/_/id/86/real-madrid",
        "competition": "Real Madrid",
        "source": "ESPN",
    },
    "Barcelona": {
        "fixtures_url": "https://www.espn.com/soccer/team/fixtures/_/id/83/esp.1",
        "results_url": "https://www.espn.com/soccer/team/results/_/id/83/esp.1",
        "competition": "Barcelona",
        "source": "ESPN",
    },
    "Atletico de Madrid": {
        "fixtures_url": "https://www.espn.com/soccer/team/fixtures/_/id/1068/atletico-madrid",
        "results_url": "https://www.espn.com/soccer/team/results/_/id/1068/atletico-madrid",
        "competition": "Atletico de Madrid",
        "source": "ESPN",
    },
}
CHAMPIONS_SCHEDULE_URL = "https://www.espn.com/soccer/schedule/_/league/uefa.champions"
F1_SCHEDULE_URL = "https://www.formula1.com/en/racing/2026"
F1_RESULTS_URL = "https://www.formula1.com/en/results/2026/races"
MOTOGP_CALENDAR_URL = "https://espndeportes.espn.com/motociclismo/nota/_/id/16389011/motogp-cuando-son-las-carreras-calendario-2026"
ALCARAZ_RESULTS_URL = "https://www.espn.com/tennis/player/results/_/id/3782/carlos-alcaraz"

KEYWORD_WEIGHTS = {
    "streik": 5,
    "warnung": 4,
    "sperrung": 4,
    "stoerung": 4,
    "unwetter": 4,
    "u7": 6,
    "u-bahn": 5,
    "s-bahn": 5,
    "rmv": 5,
    "vgf": 5,
    "nordwest": 5,
    "ostend": 4,
    "ostbahnhof": 4,
    "verkehr": 3,
    "polizei": 3,
    "feuerwehr": 3,
    "baustelle": 3,
    "frankfurt": 1,
}

COMMUTE_HINTS = [
    ("streik", "Revisa RMV/VGF antes de salir; el riesgo de servicio reducido es alto."),
    ("sperrung", "Puede haber desvíos o cortes; conviene abrir RMV antes del trayecto."),
    ("u7", "Hay señales directas sobre la línea U7 o su entorno inmediato."),
    ("rmv", "El sistema RMV aparece en titulares; valida conexiones antes del siguiente desplazamiento."),
    ("vgf", "La red VGF está mencionada; comprueba si afecta a U-Bahn o transbordos."),
    ("unwetter", "Si sales a pie hasta la estación, lleva paraguas y deja margen."),
]

WEATHER_CODE_LABELS = {
    0: "Despejado",
    1: "Mayormente despejado",
    2: "Parcialmente nuboso",
    3: "Cubierto",
    45: "Niebla",
    48: "Niebla helada",
    51: "Llovizna ligera",
    53: "Llovizna moderada",
    55: "Llovizna intensa",
    61: "Lluvia ligera",
    63: "Lluvia moderada",
    65: "Lluvia intensa",
    71: "Nieve ligera",
    73: "Nieve moderada",
    75: "Nieve intensa",
    80: "Chubascos ligeros",
    81: "Chubascos moderados",
    82: "Chubascos intensos",
    95: "Tormenta",
    96: "Tormenta con granizo",
    99: "Tormenta fuerte con granizo",
}

WEEKDAY_LABELS = {
    0: "Lunes",
    1: "Martes",
    2: "Miercoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sabado",
    6: "Domingo",
}


@dataclass
class Article:
    title: str
    link: str
    source: str
    description: str
    published_at: datetime | None
    category_key: str
    category_label: str
    score: int = 0
    impact_label: str = "Baja"
    matched_terms: list[str] = field(default_factory=list)
    translated_title: str | None = None
    translated_description: str | None = None
    initialization_hint: str | None = None
    source_url: str | None = None

    @property
    def age_text(self) -> str:
        if not self.published_at:
            return "Hora no disponible"
        delta = datetime.now(TIMEZONE) - self.published_at.astimezone(TIMEZONE)
        hours = int(delta.total_seconds() // 3600)
        if hours < 1:
            minutes = max(1, int(delta.total_seconds() // 60))
            return f"Hace {minutes} min"
        if hours < 24:
            return f"Hace {hours} h"
        return f"Hace {delta.days} d"


@dataclass
class Holiday:
    name: str
    date: datetime
    is_regional: bool

    @property
    def countdown_label(self) -> str:
        today = datetime.now(TIMEZONE).date()
        delta_days = (self.date.date() - today).days
        if delta_days == 0:
            return "Hoy"
        if delta_days == 1:
            return "Manana"
        return f"En {delta_days} dias"


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TIMEZONE)
    return value.astimezone(TIMEZONE)


def is_recent_article(article: Article, reference_time: datetime) -> bool:
    published = normalize_datetime(article.published_at)
    if published is None:
        return False
    delta_hours = (reference_time - published).total_seconds() / 3600
    return 0 <= delta_hours <= NEWS_WINDOW_HOURS


def load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def fetch_url(url: str, *, headers: dict[str, str] | None = None, data: bytes | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NoticiasFrankfurtBot/1.0", **(headers or {})},
        data=data,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_json(url: str) -> Any:
    return json.loads(fetch_url(url).decode("utf-8"))


def strip_html(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value))).strip()


def is_google_news_link(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "news.google.com" or host.startswith("news.google.")


def normalize_candidate_url(raw_url: str) -> str | None:
    if not raw_url:
        return None
    value = html.unescape(raw_url.strip())
    if value.startswith("//"):
        value = f"https:{value}"
    if value.startswith("/"):
        value = urllib.parse.urljoin("https://news.google.com", value)
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return None


def is_source_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    if host == "news.google.com" or host.startswith("news.google."):
        return False
    return True


def _extract_url_from_payload(value: Any) -> str | None:
    if isinstance(value, str):
        normalized = normalize_candidate_url(value.strip())
        if normalized and is_source_url(normalized):
            return normalized
        return None
    if isinstance(value, dict):
        for key in ("url", "link", "source_url", "target", "target_url", "source", "canonical_url", "final", "final_url"):
            candidate = _extract_url_from_payload(value.get(key))
            if candidate:
                return candidate
        for item in value.values():
            candidate = _extract_url_from_payload(item)
            if candidate:
                return candidate
    if isinstance(value, (list, tuple, set)):
        for item in value:
            candidate = _extract_url_from_payload(item)
            if candidate:
                return candidate
    return None


def _decode_with_googlenewsdecoder(url: str) -> str | None:
    if googlenewsdecoder is None:
        return None

    candidates: list[Any] = []
    for fn_name in (
        "decode_google_news_url",
        "decode_google_news",
        "decode_news_url",
        "decode_url",
        "decode",
    ):
        fn = getattr(googlenewsdecoder, fn_name, None)
        if callable(fn):
            candidates.append(fn)

    decoder_cls = getattr(googlenewsdecoder, "GoogleNewsDecoder", None)
    if callable(decoder_cls):
        try:
            decoder = decoder_cls()
        except Exception:
            decoder = None
        if decoder is not None:
            for fn_name in ("decode_google_news_url", "decode_google_news", "decode_url", "decode", "get_source_url"):
                fn = getattr(decoder, fn_name, None)
                if callable(fn):
                    candidates.append(fn)

    for fn in candidates:
        try:
            decoded = fn(url)
        except Exception:
            continue
        candidate = _extract_url_from_payload(decoded)
        if candidate:
            return candidate
    return None


def extract_text_from_html(raw_html: str) -> str:
    if BeautifulSoup is None:
        text = re.sub(r"<script[^>]*>.*?</script>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
        return collapse_whitespace(re.sub(r"<[^>]+>", " ", text))
    soup = BeautifulSoup(raw_html, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.decompose()
    body = soup.find("article") or soup.find("main") or soup.body
    if body is None:
        body = soup
    return collapse_whitespace(body.get_text(" ", strip=True))


def collect_urls_from_jsonld(payload: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str) and key in {"url", "mainEntityOfPage", "sameAs", "@id"} and is_source_url(value):
                urls.append(value)
            elif key == "url" and isinstance(value, dict):
                nested = value.get("url")
                if isinstance(nested, str) and is_source_url(nested):
                    urls.append(nested)
            else:
                urls.extend(collect_urls_from_jsonld(value))
    elif isinstance(payload, list):
        for item in payload:
            urls.extend(collect_urls_from_jsonld(item))
    return urls


def extract_google_news_target_url(raw_html: str) -> str | None:
    if BeautifulSoup is None:
        for pattern in [
            r"<link[^>]*rel=[\"']canonical[\"'][^>]*href=[\"']([^\"']+)[\"']",
            r"<meta[^>]*property=[\"']og:url[\"'][^>]*content=[\"']([^\"']+)[\"']",
            r"<meta[^>]*name=[\"']twitter:url[\"'][^>]*content=[\"']([^\"']+)[\"']",
        ]:
            match = re.search(pattern, raw_html, flags=re.IGNORECASE)
            if match:
                candidate = normalize_candidate_url(match.group(1))
                if candidate and is_source_url(candidate):
                    return candidate
        return None

    soup = BeautifulSoup(raw_html, "html.parser")
    candidates = [
        (soup.select_one("meta[property='og:url']"), "content"),
        (soup.select_one("meta[name='twitter:url']"), "content"),
        (soup.select_one("meta[property='twitter:url']"), "content"),
        (soup.select_one("meta[property='article:canonical_url']"), "content"),
        (soup.select_one("link[rel='canonical']"), "href"),
        (soup.select_one("meta[itemprop='url']"), "content"),
    ]
    for tag, attr in candidates:
        if not tag:
            continue
        candidate = normalize_candidate_url(tag.get(attr, ""))
        if candidate and is_source_url(candidate):
            return candidate

    for script in soup.find_all("script", type="application/ld+json"):
        script_content = script.get_text(" ", strip=True)
        if not script_content:
            continue
        try:
            payload = json.loads(script_content)
        except json.JSONDecodeError:
            continue
        for candidate in collect_urls_from_jsonld(payload):
            if is_source_url(candidate):
                return candidate

    for a_tag in soup.select("a[href]"):
        candidate = normalize_candidate_url(a_tag.get("href", ""))
        if candidate and is_source_url(candidate):
            return candidate
    return None


def resolve_google_news_article(url: str) -> tuple[str | None, str]:
    if not is_google_news_link(url):
        return None, ""
    cached = GOOGLE_ARTICLE_CACHE.get(url)
    if cached is not None:
        return cached
    decoder_target = _decode_with_googlenewsdecoder(url)
    if decoder_target:
        try:
            article_text = extract_text_from_html(fetch_url(decoder_target).decode("utf-8", errors="ignore"))
        except Exception:
            article_text = ""
        GOOGLE_ARTICLE_CACHE[url] = (decoder_target, article_text)
        return GOOGLE_ARTICLE_CACHE[url]
    try:
        raw_html = fetch_url(url).decode("utf-8", errors="ignore")
    except Exception:
        GOOGLE_ARTICLE_CACHE[url] = (None, "")
        return None, ""
    target_url = extract_google_news_target_url(raw_html)
    if target_url == "":  # pragma: no cover - fallback
        target_url = None
    if target_url and is_google_news_link(target_url):
        target_url = None
    article_text = extract_text_from_html(raw_html)
    GOOGLE_ARTICLE_CACHE[url] = (target_url, article_text)
    return GOOGLE_ARTICLE_CACHE[url]


def should_extract_initialization(article: Article) -> bool:
    if article.category_key not in GOOGLE_CONTEXT_CATEGORIES:
        return False
    haystack = normalize_text(f"{article.title} {article.description}")
    return any(term in haystack for term in INITIALIZATION_KEYWORDS)


def extract_initialization_hint(article: Article, article_text: str) -> str | None:
    haystack = normalize_text(f"{article.title} {article.description} {article_text}")
    for match in DATE_DETECTION_RE.finditer(haystack):
        phrase = haystack[max(0, match.start() - 45) : match.end() + 45]
        if any(prefix in phrase for prefix in INITIALIZATION_PREFIXES):
            return collapse_whitespace(f"Inicio estimado: {phrase}")
    return None


def enrich_google_news_article(article: Article, source_url: str | None = None) -> None:
    if not is_google_news_link(article.link):
        return
    if not should_extract_initialization(article):
        if source_url and is_source_url(source_url):
            article.link = source_url
        return
    target_link, article_text = resolve_google_news_article(article.link)
    if target_link:
        article.link = target_link
    elif source_url and is_source_url(source_url):
        article.link = source_url
    if article_text:
        article.initialization_hint = extract_initialization_hint(article, article_text)


def parse_google_news_feed(category: dict[str, Any]) -> list[Article]:
    query = urllib.parse.quote_plus(category["query"])
    url = f"https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de"
    root = ET.fromstring(fetch_url(url))
    articles: list[Article] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source_node = item.find("source")
        source_url = (source_node.attrib.get("url") if source_node is not None and source_node.attrib else None) if isinstance(source_node, ET.Element) else None
        if not title or not link:
            continue
        published_at = None
        if item.findtext("pubDate"):
            try:
                published_at = parsedate_to_datetime(item.findtext("pubDate") or "")
            except (TypeError, ValueError):
                published_at = None
        articles.append(
            Article(
                title=title,
                link=link,
                source=(item.findtext("source") or "Google News").strip(),
                description=strip_html(item.findtext("description") or ""),
                published_at=published_at,
                category_key=category["key"],
                category_label=category["label"],
                source_url=source_url,
            )
        )
        if category["key"] in GOOGLE_CONTEXT_CATEGORIES and should_extract_initialization(articles[-1]):
            try:
                enrich_google_news_article(articles[-1], source_url)
            except Exception:
                pass
    return articles


def score_article(article: Article) -> Article:
    haystack = f"{article.title} {article.description}".lower()
    score = 0
    matches: list[str] = []
    for term, weight in KEYWORD_WEIGHTS.items():
        if term in haystack:
            score += weight
            matches.append(term)
    published = normalize_datetime(article.published_at)
    if published:
        hours = max(0.0, (datetime.now(TIMEZONE) - published).total_seconds() / 3600)
        score += 4 if hours <= 6 else 2 if hours <= 24 else 0
    if article.category_key == "commute":
        score += 2
    article.score = score
    article.matched_terms = matches
    article.impact_label = "Alta" if score >= 14 else "Media" if score >= 8 else "Baja"
    return article


def deduplicate_articles(articles: list[Article]) -> list[Article]:
    seen: dict[str, Article] = {}
    for article in articles:
        key = re.sub(r"\s+", " ", article.title.lower()).strip()
        current = seen.get(key)
        if not current or article.score > current.score:
            seen[key] = article
    return list(seen.values())


def sort_articles(articles: list[Article]) -> list[Article]:
    return sorted(
        articles,
        key=lambda item: (-item.score, -(item.published_at.timestamp() if item.published_at else 0)),
    )


def fetch_weather() -> dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={TARGET_LAT}&longitude={TARGET_LON}"
        "&hourly=temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        "&timezone=Europe%2FBerlin&forecast_days=10"
    )
    data = json.loads(fetch_url(url).decode("utf-8"))
    now = datetime.now(TIMEZONE)
    hourly_times = [datetime.fromisoformat(value).replace(tzinfo=TIMEZONE) for value in data["hourly"]["time"]]
    current_idx = min(range(len(hourly_times)), key=lambda idx: abs((hourly_times[idx] - now).total_seconds()))
    current = {
        "time": hourly_times[current_idx],
        "temperature": data["hourly"]["temperature_2m"][current_idx],
        "apparent_temperature": data["hourly"]["apparent_temperature"][current_idx],
        "precipitation_probability": data["hourly"]["precipitation_probability"][current_idx],
        "weather_code": data["hourly"]["weather_code"][current_idx],
        "wind_speed": data["hourly"]["wind_speed_10m"][current_idx],
    }
    next_hours = []
    for idx in range(current_idx, min(current_idx + 8, len(hourly_times))):
        next_hours.append(
            {
                "time": hourly_times[idx],
                "temperature": data["hourly"]["temperature_2m"][idx],
                "precipitation_probability": data["hourly"]["precipitation_probability"][idx],
                "weather_code": data["hourly"]["weather_code"][idx],
            }
        )
    daily_entries = []
    for idx, raw_date in enumerate(data["daily"]["time"]):
        daily_date = datetime.fromisoformat(raw_date).replace(tzinfo=TIMEZONE)
        daily_entries.append(
            {
                "date": daily_date,
                "weekday": WEEKDAY_LABELS[daily_date.weekday()],
                "temp_max": data["daily"]["temperature_2m_max"][idx],
                "temp_min": data["daily"]["temperature_2m_min"][idx],
                "precipitation_probability_max": data["daily"]["precipitation_probability_max"][idx],
                "weather_code": data["daily"]["weather_code"][idx],
            }
        )

    tomorrow = daily_entries[1] if len(daily_entries) > 1 else daily_entries[0]
    next_saturday = next((entry for entry in daily_entries if entry["date"].date() >= now.date() and entry["date"].weekday() == 5), None)
    weekend = []
    if next_saturday:
        weekend.append(next_saturday)
        sunday_date = next_saturday["date"].date() + timedelta(days=1)
        sunday = next((entry for entry in daily_entries if entry["date"].date() == sunday_date), None)
        if sunday:
            weekend.append(sunday)
    return {
        "current": current,
        "next_hours": next_hours,
        "daily": daily_entries[0],
        "tomorrow": tomorrow,
        "weekend": weekend,
        "daily_entries": daily_entries,
    }


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_only).strip().lower()


def fetch_soup(url: str) -> BeautifulSoup:
    if BeautifulSoup is None:
        raise RuntimeError("Falta beautifulsoup4. Instala el paquete para activar la agenda deportiva mejorada.")
    return BeautifulSoup(fetch_url(url).decode("utf-8", errors="ignore"), "html.parser")


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def infer_year(month: int, day: int, now: datetime | None = None) -> int:
    now = now or datetime.now(TIMEZONE)
    candidate = datetime(now.year, month, day, tzinfo=TIMEZONE)
    if candidate.date() < (now.date() - timedelta(days=180)):
        return now.year + 1
    if candidate.date() > (now.date() + timedelta(days=180)):
        return now.year - 1
    return now.year


def parse_month_day_label(value: str, with_time: str | None = None, timezone: ZoneInfo = TIMEZONE) -> datetime | None:
    value = collapse_whitespace(value)
    match = re.match(r"^[A-Za-z]{3},\s+([A-Za-z]{3})\s+(\d{1,2})$", value)
    if not match:
        return None
    month = datetime.strptime(match.group(1), "%b").month
    day = int(match.group(2))
    year = infer_year(month, day)
    if with_time and with_time not in {"TBD", "-"}:
        time_text = collapse_whitespace(with_time)
        try:
            parsed = datetime.strptime(f"{match.group(1)} {day} {year} {time_text}", "%b %d %Y %I:%M %p")
            return parsed.replace(tzinfo=timezone).astimezone(TIMEZONE)
        except ValueError:
            pass
    return datetime(year, month, day, 12, 0, tzinfo=TIMEZONE)


def parse_full_date_label(value: str) -> datetime | None:
    value = collapse_whitespace(value)
    try:
        return datetime.strptime(value, "%A, %B %d, %Y").replace(tzinfo=TIMEZONE)
    except ValueError:
        return None


def parse_f1_date_range(value: str, year: int = 2026) -> datetime | None:
    value = collapse_whitespace(value)
    match = re.match(r"^(\d{1,2})\s*-\s*(\d{1,2})\s+([A-Z]{3})$", value)
    if not match:
        return None
    day = int(match.group(2))
    month = datetime.strptime(match.group(3).title(), "%b").month
    return datetime(year, month, day, 12, 0, tzinfo=TIMEZONE)


def parse_day_month_numeric(value: str, year: int = 2026) -> datetime | None:
    value = collapse_whitespace(value)
    match = re.match(r"^(\d{1,2})/(\d{1,2})$", value)
    if not match:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    return datetime(year, month, day, 12, 0, tzinfo=TIMEZONE)


def within_window(moment: datetime | None, *, lookback_days: int = SPORTS_LOOKBACK_DAYS, lookahead_days: int = SPORTS_LOOKAHEAD_DAYS) -> bool:
    if moment is None:
        return False
    now = datetime.now(TIMEZONE)
    return (now - timedelta(days=lookback_days)) <= moment <= (now + timedelta(days=lookahead_days))


def build_upcoming_event(
    title: str,
    competition: str,
    start_time: datetime | None,
    source: str,
    link: str,
    *,
    details: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "competition": competition,
        "start_time": start_time.isoformat() if start_time else None,
        "status": "Upcoming",
        "details": details,
        "source": source,
        "link": link,
    }


def build_result_event(
    title: str,
    competition: str,
    event_time: datetime | None,
    source: str,
    link: str,
    *,
    result: str = "",
    details: str = "",
) -> dict[str, Any]:
    return {
        "title": title,
        "competition": competition,
        "start_time": event_time.isoformat() if event_time else None,
        "status": "Final",
        "result": result,
        "details": details,
        "source": source,
        "link": link,
    }


def clean_flag_prefix(value: str) -> str:
    return re.sub(r"^Flag of [A-Za-z ]+\s+", "", collapse_whitespace(value))


def fetch_team_schedule_and_results(team_label: str) -> dict[str, Any]:
    config = TEAM_SOURCES[team_label]
    fixtures_soup = fetch_soup(config["fixtures_url"])
    results_soup = fetch_soup(config["results_url"])
    upcoming: list[dict[str, Any]] = []
    recent_results: list[dict[str, Any]] = []
    for table in fixtures_soup.find_all("table"):
        for row in table.find_all("tr")[1:]:
            cells = [collapse_whitespace(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if len(cells) < 6:
                continue
            event_time = parse_month_day_label(cells[0], cells[4], timezone=ESPN_TIMEZONE)
            if event_time is None or event_time < datetime.now(TIMEZONE) or not within_window(event_time):
                continue
            upcoming.append(
                build_upcoming_event(
                    f"{cells[1]} vs {cells[3]}",
                    cells[5],
                    event_time,
                    config["source"],
                    config["fixtures_url"],
                    details=f"Hora ESPN: {cells[4]}",
                )
            )
    for table in results_soup.find_all("table"):
        for row in table.find_all("tr")[1:]:
            cells = [collapse_whitespace(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if len(cells) < 6:
                continue
            event_time = parse_month_day_label(cells[0])
            if event_time is None or event_time > datetime.now(TIMEZONE) or not within_window(event_time):
                continue
            recent_results.append(
                build_result_event(
                    f"{cells[1]} vs {cells[3]}",
                    cells[5],
                    event_time,
                    config["source"],
                    config["results_url"],
                    result=cells[2],
                    details=cells[4],
                )
            )
    upcoming.sort(key=lambda item: item["start_time"] or "")
    recent_results.sort(key=lambda item: item["start_time"] or "", reverse=True)
    return {"upcoming": upcoming[:4], "recent_results": recent_results[:4], "source": config["source"]}


def fetch_champions_schedule_and_results() -> dict[str, Any]:
    soup = fetch_soup(CHAMPIONS_SCHEDULE_URL)
    upcoming: list[dict[str, Any]] = []
    recent_results: list[dict[str, Any]] = []
    for block in soup.find_all("div", class_="ResponsiveTable"):
        title_el = block.find("div", class_="Table__Title")
        table = block.find("table")
        if not title_el or not table:
            continue
        block_date = parse_full_date_label(title_el.get_text(" ", strip=True))
        headers = [collapse_whitespace(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        rows = table.find_all("tr")[1:]
        target_list = upcoming if "time" in headers else recent_results
        last_item: dict[str, Any] | None = None
        for row in rows:
            cells = [collapse_whitespace(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if not cells:
                continue
            if len(cells) == 1 and last_item is not None:
                last_item["details"] = collapse_whitespace(" ".join(filter(None, [last_item.get("details", ""), cells[0]])))
                continue
            if "time" in headers and len(cells) >= 5:
                away = re.sub(r"^v\s*", "", cells[1], flags=re.IGNORECASE)
                event_time = None
                if block_date is not None and cells[2] and cells[2] not in {"-", "TBD"}:
                    try:
                        local_time = datetime.strptime(cells[2], "%I:%M %p").time()
                        event_time = datetime.combine(block_date.date(), local_time, tzinfo=ESPN_TIMEZONE).astimezone(TIMEZONE)
                    except ValueError:
                        event_time = block_date
                if event_time is None or event_time < datetime.now(TIMEZONE) or not within_window(event_time):
                    continue
                last_item = build_upcoming_event(
                    f"{cells[0]} vs {away}",
                    "UEFA Champions League",
                    event_time,
                    "ESPN",
                    CHAMPIONS_SCHEDULE_URL,
                    details=cells[4],
                )
                target_list.append(last_item)
            elif len(cells) >= 4:
                score_match = re.search(r"(\d+\s*-\s*\d+)", cells[1])
                if not score_match:
                    continue
                score = score_match.group(1)
                away = cells[1].replace(score, "", 1).strip()
                if block_date is None or block_date > datetime.now(TIMEZONE) or not within_window(block_date):
                    continue
                last_item = build_result_event(
                    f"{cells[0]} vs {away}",
                    "UEFA Champions League",
                    block_date,
                    "ESPN",
                    CHAMPIONS_SCHEDULE_URL,
                    result=score,
                    details=f"{cells[2]} | {cells[3]}",
                )
                target_list.append(last_item)
    upcoming.sort(key=lambda item: item["start_time"] or "")
    recent_results.sort(key=lambda item: item["start_time"] or "", reverse=True)
    return {"upcoming": upcoming[:4], "recent_results": recent_results[:4], "source": "ESPN"}


def fetch_f1_schedule_and_results() -> dict[str, Any]:
    schedule_soup = fetch_soup(F1_SCHEDULE_URL)
    results_soup = fetch_soup(F1_RESULTS_URL)
    upcoming: list[dict[str, Any]] = []
    recent_results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in schedule_soup.find_all("a", href=re.compile(r"^/en/racing/2026/[a-z-]+$")):
        href = anchor.get("href") or ""
        if href in seen:
            continue
        seen.add(href)
        texts = [collapse_whitespace(text) for text in anchor.stripped_strings]
        if len(texts) < 3 or not texts[0].startswith("ROUND"):
            continue
        event_time = parse_f1_date_range(texts[2], year=2026)
        if event_time is None or event_time < datetime.now(TIMEZONE) or not within_window(event_time):
            continue
        upcoming.append(
            build_upcoming_event(
                f"GP de {texts[1]}",
                "Formula 1",
                event_time,
                "Formula1.com",
                urllib.parse.urljoin(F1_SCHEDULE_URL, href),
                details=texts[0],
            )
        )
    table = results_soup.find("table")
    if table:
        for row in table.find_all("tr")[1:]:
            cells = [clean_flag_prefix(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if len(cells) < 6:
                continue
            try:
                event_time = datetime.strptime(f"{cells[1]} 2026", "%d %b %Y").replace(tzinfo=TIMEZONE)
            except ValueError:
                continue
            if event_time > datetime.now(TIMEZONE) or not within_window(event_time):
                continue
            recent_results.append(
                build_result_event(
                    f"GP de {cells[0]}",
                    "Formula 1",
                    event_time,
                    "Formula1.com",
                    F1_RESULTS_URL,
                    result=f"Ganador: {cells[2]}",
                    details=f"{cells[3]} | {cells[5]}",
                )
            )
    upcoming.sort(key=lambda item: item["start_time"] or "")
    recent_results.sort(key=lambda item: item["start_time"] or "", reverse=True)
    return {"upcoming": upcoming[:4], "recent_results": recent_results[:4], "source": "Formula1.com"}


def fetch_motogp_schedule_and_results() -> dict[str, Any]:
    soup = fetch_soup(MOTOGP_CALENDAR_URL)
    table = soup.find("table")
    upcoming: list[dict[str, Any]] = []
    recent_results: list[dict[str, Any]] = []
    if table:
        for row in table.find_all("tr")[1:]:
            cells = [collapse_whitespace(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if len(cells) < 3:
                continue
            event_time = parse_day_month_numeric(cells[0], year=2026)
            if event_time is None or not within_window(event_time):
                continue
            title = f"GP de {cells[1]}"
            if cells[2]:
                if event_time <= datetime.now(TIMEZONE):
                    recent_results.append(
                        build_result_event(
                            title,
                            "MotoGP",
                            event_time,
                            "ESPN",
                            MOTOGP_CALENDAR_URL,
                            result=f"Ganador: {cells[2]}",
                        )
                    )
            elif event_time >= datetime.now(TIMEZONE):
                upcoming.append(build_upcoming_event(title, "MotoGP", event_time, "ESPN", MOTOGP_CALENDAR_URL))
    upcoming.sort(key=lambda item: item["start_time"] or "")
    recent_results.sort(key=lambda item: item["start_time"] or "", reverse=True)
    return {"upcoming": upcoming[:4], "recent_results": recent_results[:4], "source": "ESPN"}


def fetch_alcaraz_schedule_and_results() -> dict[str, Any]:
    soup = fetch_soup(ALCARAZ_RESULTS_URL)
    target_table = None
    for table in soup.find_all("table"):
        headers = [collapse_whitespace(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        if headers[:4] == ["round", "opponent", "result", "score"]:
            target_table = table
            break
    upcoming: list[dict[str, Any]] = []
    recent_results: list[dict[str, Any]] = []
    if target_table:
        for row in target_table.find_all("tr")[1:]:
            cells = [collapse_whitespace(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            if len(cells) < 4 or cells[0] in {"Men's Singles", "Women's Singles"}:
                continue
            opponent = cells[1] or "Rival por confirmar"
            title = f"Carlos Alcaraz vs {opponent}"
            if cells[2] in {"W", "L"}:
                recent_results.append(
                    build_result_event(
                        title,
                        "Tenis",
                        None,
                        "ESPN",
                        ALCARAZ_RESULTS_URL,
                        result=f"{cells[2]} | {cells[3]}",
                        details=cells[0],
                    )
                )
            elif cells[2] == "-" and cells[3]:
                event_time = None
                try:
                    event_time = datetime.strptime(cells[3], "%B %d %I:%M %p ET").replace(year=2026, tzinfo=ESPN_TIMEZONE).astimezone(TIMEZONE)
                except ValueError:
                    event_time = None
                upcoming.append(
                    build_upcoming_event(
                        title,
                        "Tenis",
                        event_time,
                        "ESPN",
                        ALCARAZ_RESULTS_URL,
                        details=cells[0],
                    )
                )
    upcoming.sort(key=lambda item: item["start_time"] or "")
    return {"upcoming": upcoming[:2], "recent_results": recent_results[:5], "source": "ESPN"}


def empty_sports_bucket(source: str = "") -> dict[str, Any]:
    return {"upcoming": [], "recent_results": [], "source": source}


def empty_sports_agenda() -> dict[str, Any]:
    return {
        "champions": empty_sports_bucket("ESPN"),
        "formula1": empty_sports_bucket("Formula1.com"),
        "motogp": empty_sports_bucket("ESPN"),
        "alcaraz": empty_sports_bucket("ESPN"),
        "clubs": {team_label: empty_sports_bucket("ESPN") for team_label in TEAM_SOURCES},
        "errors": [],
    }


def fetch_sports_agenda() -> dict[str, Any]:
    agenda = empty_sports_agenda()
    loaders = [
        ("champions", fetch_champions_schedule_and_results),
        ("formula1", fetch_f1_schedule_and_results),
        ("motogp", fetch_motogp_schedule_and_results),
        ("alcaraz", fetch_alcaraz_schedule_and_results),
    ]
    for key, loader in loaders:
        try:
            agenda[key] = loader()
        except Exception as exc:  # noqa: BLE001
            agenda["errors"].append(f"{key}: {exc}")
    for team_label in TEAM_SOURCES:
        try:
            agenda["clubs"][team_label] = fetch_team_schedule_and_results(team_label)
        except Exception as exc:  # noqa: BLE001
            agenda["errors"].append(f"{team_label}: {exc}")
    return agenda


def fetch_nearby_holidays(reference_time: datetime) -> list[Holiday]:
    years = {reference_time.year, (reference_time + timedelta(days=HOLIDAY_LOOKAHEAD_DAYS)).year}
    holidays: list[Holiday] = []
    for year in sorted(years):
        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{COUNTRY_CODE}"
        payload = json.loads(fetch_url(url).decode("utf-8"))
        for item in payload:
            holiday_date = datetime.fromisoformat(item["date"]).replace(tzinfo=TIMEZONE)
            delta_days = (holiday_date.date() - reference_time.date()).days
            if delta_days < 0 or delta_days > HOLIDAY_LOOKAHEAD_DAYS:
                continue
            counties = item.get("counties") or []
            is_regional = REGION_CODE in counties
            if item.get("global") or is_regional:
                holidays.append(
                    Holiday(
                        name=item["localName"],
                        date=holiday_date,
                        is_regional=is_regional and not item.get("global", False),
                    )
                )
    unique: dict[tuple[str, str], Holiday] = {}
    for holiday in holidays:
        unique[(holiday.name, holiday.date.date().isoformat())] = holiday
    return sorted(unique.values(), key=lambda holiday: holiday.date)[:4]


def build_weather_recommendation(weather: dict[str, Any]) -> str:
    current = weather["current"]
    recommendations: list[str] = []
    if current["precipitation_probability"] >= 50:
        recommendations.append("llevar paraguas")
    if current["apparent_temperature"] <= 4:
        recommendations.append("salir con abrigo serio")
    elif current["apparent_temperature"] <= 10:
        recommendations.append("añadir una capa ligera")
    if current["wind_speed"] >= 25:
        recommendations.append("contar con viento incómodo")
    if not recommendations:
        recommendations.append("condiciones cómodas para el trayecto a pie")
    return ", ".join(recommendations)


def sports_bucket_has_content(bucket: dict[str, Any] | None) -> bool:
    if not isinstance(bucket, dict):
        return False
    return bool(bucket.get("upcoming") or bucket.get("recent_results"))


def parse_event_start_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(TIMEZONE)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=TIMEZONE)
    return parsed.astimezone(TIMEZONE)


def sports_event_start_text(event: dict[str, Any]) -> str:
    start_time = parse_event_start_time(event.get("start_time"))
    return format_datetime(start_time) if start_time else "Hora pendiente"


def summarize_sports_bucket(label: str, bucket: dict[str, Any]) -> str | None:
    upcoming = bucket.get("upcoming") or []
    recent_results = bucket.get("recent_results") or []
    if upcoming:
        event = upcoming[0]
        return f"{label}: {event['title']} ({sports_event_start_text(event)})."
    if recent_results:
        event = recent_results[0]
        result_text = f" ({event['result']})" if event.get("result") else ""
        time_text = sports_event_start_text(event)
        time_suffix = f" - {time_text}" if time_text != "Hora pendiente" else ""
        return f"{label}: {event['title']}{result_text}{time_suffix}."
    return None


def fallback_digest(
    weather: dict[str, Any],
    top_articles: list[Article],
    holidays: list[Holiday],
    categories: dict[str, list[Article]],
    sports: dict[str, Any],
) -> dict[str, Any]:
    combined = " ".join(f"{article.title} {article.description}".lower() for article in top_articles)
    mobility = [message for term, message in COMMUTE_HINTS if term in combined][:2]
    if not mobility:
        mobility.append("No aparece una incidencia grave clara, pero conviene validar RMV/VGF antes de salir.")
    mobility.append("Revisar cortes de carretera y tren si hay desplazamientos largos por la region.")

    summary = [article.title for article in top_articles[:3]] or ["Sin titulares destacados en esta actualizacion."]
    climate = [
        f"Ahora: {weather['current']['temperature']:.0f}°C y {WEATHER_CODE_LABELS.get(weather['current']['weather_code'], 'condiciones variables').lower()}.",
        f"Hoy: {weather['daily']['temp_min']:.0f}° / {weather['daily']['temp_max']:.0f}° con {weather['daily']['precipitation_probability_max']:.0f}% de lluvia maxima.",
        f"Manana: {weather['tomorrow']['temp_min']:.0f}° / {weather['tomorrow']['temp_max']:.0f}°.",
    ]
    if weather["weekend"]:
        weekend_labels = ", ".join(
            f"{day['weekday']}: {day['temp_min']:.0f}°/{day['temp_max']:.0f}°"
            for day in weather["weekend"][:2]
        )
        climate.append(f"Fin de semana: {weekend_labels}.")

    holidays_section = [
        f"{holiday.name}: {format_day_label(holiday.date)} ({holiday.countdown_label.lower()})."
        for holiday in holidays[:3]
    ] or ["No hay festivos cercanos en los proximos 45 dias."]

    germany_items = []
    for key in ("germany_economy", "germany_culture"):
        germany_items.extend(article.title for article in categories.get(key, [])[:2])
    if not germany_items:
        germany_items = ["Sin titulares destacados de economia o cultura alemana en esta actualizacion."]

    sports_labels = {
        "champions": "Champions League",
        "formula1": "Formula 1",
        "motogp": "MotoGP",
        "alcaraz": "Carlos Alcaraz",
    }
    sports_items = []
    for key, label in sports_labels.items():
        summary_line = summarize_sports_bucket(label, sports.get(key, {}))
        if summary_line:
            sports_items.append(summary_line)
    for club_name, club_bucket in sports.get("clubs", {}).items():
        summary_line = summarize_sports_bucket(club_name, club_bucket)
        if summary_line:
            sports_items.append(summary_line)
    if not sports_items:
        sports_items = ["Sin agenda deportiva cercana detectada en esta actualizacion."]

    watchlist = [article.title for article in top_articles[3:6]]
    if holidays:
        watchlist.append(f"Festivo cercano: {holidays[0].name} ({holidays[0].countdown_label.lower()}).")
    if sports.get("errors"):
        watchlist.append("La fuente deportiva ha fallado en esta ejecucion.")

    return {
        "headline": "Briefing local para Frankfurt con foco en movilidad y ciudad",
        "summary": summary,
        "mobility_alerts": mobility[:3],
        "climate": climate[:4],
        "holidays": holidays_section,
        "germany": germany_items[:4],
        "sports": sports_items[:5],
        "watchlist": watchlist or ["Seguir movilidad, avisos y clima en la proxima actualizacion."],
    }


def serialize_sports_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": event["title"],
        "competition": event["competition"],
        "start_time": event["start_time"].isoformat() if isinstance(event.get("start_time"), datetime) else event.get("start_time"),
        "start_text": sports_event_start_text(event),
        "status": event.get("status", ""),
        "result": event.get("result", ""),
        "details": event.get("details", ""),
        "source": event.get("source", ""),
        "link": event.get("link", ""),
    }


def serialize_sports_bucket(bucket: dict[str, Any], *, upcoming_limit: int, recent_limit: int) -> dict[str, Any]:
    return {
        "source": bucket.get("source", ""),
        "upcoming": [serialize_sports_event(event) for event in (bucket.get("upcoming") or [])[:upcoming_limit]],
        "recent_results": [serialize_sports_event(event) for event in (bucket.get("recent_results") or [])[:recent_limit]],
    }


def build_llm_prompt(
    weather: dict[str, Any],
    articles: list[Article],
    holidays: list[Holiday],
    categories: dict[str, list[Article]],
    sports: dict[str, Any],
) -> str:
    article_rows = []
    for article in articles[:8]:
        article_rows.append(
            {
                "titulo": article.title,
                "link": article.link,
                "fuente": article.source,
                "categoria": article.category_label,
                "impacto": article.impact_label,
                "hora": article.published_at.astimezone(TIMEZONE).isoformat() if article.published_at else None,
                "descripcion": article.description[:160],
            }
        )
    payload = {
        "persona": "Persona con desplazamientos diarios entre el noroeste y el este de Frankfurt.",
        "objetivo": "Priorizar huelgas, transporte, alertas, clima, noticias de ciudad, Alemania economia/cultura, fin de semana, festivos cercanos y deporte.",
        "ventana_noticias": "Solo articulos de las ultimas 24 horas.",
        "weather": {
            "hora_actual": weather["current"]["time"].isoformat(),
            "temperatura": weather["current"]["temperature"],
            "sensacion": weather["current"]["apparent_temperature"],
            "lluvia_probabilidad": weather["current"]["precipitation_probability"],
            "viento": weather["current"]["wind_speed"],
            "estado": WEATHER_CODE_LABELS.get(weather["current"]["weather_code"], "Condiciones variables"),
            "hoy": serialize_day_forecast(weather["daily"]),
            "manana": serialize_day_forecast(weather["tomorrow"]),
            "fin_de_semana": [serialize_day_forecast(day) for day in weather["weekend"]],
        },
        "festivos_cercanos": [
            {
                "nombre": holiday.name,
                "fecha": holiday.date.date().isoformat(),
                "regional_hessen": holiday.is_regional,
            }
            for holiday in holidays
        ],
        "categorias_destacadas": {
            key: [
                {
                    "titulo": article.title,
                    "fuente": article.source,
                    "impacto": article.impact_label,
                }
                for article in items[:2]
            ]
            for key, items in categories.items()
        },
        "deportes": {
            "champions": serialize_sports_bucket(sports.get("champions", {}), upcoming_limit=3, recent_limit=2),
            "formula1": serialize_sports_bucket(sports.get("formula1", {}), upcoming_limit=2, recent_limit=2),
            "motogp": serialize_sports_bucket(sports.get("motogp", {}), upcoming_limit=2, recent_limit=2),
            "alcaraz": serialize_sports_bucket(sports.get("alcaraz", {}), upcoming_limit=2, recent_limit=3),
            "clubs": {
                key: serialize_sports_bucket(bucket, upcoming_limit=2, recent_limit=2)
                for key, bucket in sports.get("clubs", {}).items()
            },
        },
        "articulos": article_rows,
    }
    return (
        'Devuelve solo JSON valido en espanol con las claves "headline", "ai_report_sections", "article_translations", "summary", "mobility_alerts", "climate", "holidays", "germany", "sports", "watchlist". '
        'En "ai_report_sections" devuelve un objeto con estas claves exactas: "clima_forecast", "movilidad_alertas", "alemania", "deportes", "festivos". Cada valor debe ser un parrafo claro, relativamente largo y bien redactado en espanol. '
        'El orden conceptual del briefing es: clima y forecast, movilidad y alertas, Alemania economia/cultura, deportes, festivos cercanos. '
        'En "article_translations" devuelve una lista de objetos con "link", "translated_title" y "translated_description". Traduce al espanol solo los articulos que esten claramente en aleman; si ya estan en espanol o ingles, puedes dejarlos fuera. '
        "No incluyas markdown ni texto adicional. Usa frases claras, con algo mas de desarrollo que el resto del JSON.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def build_reduced_llm_prompt(
    weather: dict[str, Any],
    holidays: list[Holiday],
    categories: dict[str, list[Article]],
    sports: dict[str, Any],
) -> str:
    payload = {
        "weather": {
            "actual": {
                "temperatura": weather["current"]["temperature"],
                "estado": WEATHER_CODE_LABELS.get(weather["current"]["weather_code"], "Condiciones variables"),
            },
            "hoy": serialize_day_forecast(weather["daily"]),
            "manana": serialize_day_forecast(weather["tomorrow"]),
            "fin_de_semana": [serialize_day_forecast(day) for day in weather["weekend"][:2]],
        },
        "holidays": [
            {"nombre": holiday.name, "fecha": holiday.date.date().isoformat()}
            for holiday in holidays[:3]
        ],
        "categories": {
            key: [article.title for article in items[:2]]
            for key, items in categories.items()
        },
        "sports": {
            "champions": serialize_sports_bucket(sports.get("champions", {}), upcoming_limit=2, recent_limit=1),
            "formula1": serialize_sports_bucket(sports.get("formula1", {}), upcoming_limit=1, recent_limit=1),
            "motogp": serialize_sports_bucket(sports.get("motogp", {}), upcoming_limit=1, recent_limit=1),
            "alcaraz": serialize_sports_bucket(sports.get("alcaraz", {}), upcoming_limit=1, recent_limit=2),
            "clubs": {
                key: serialize_sports_bucket(bucket, upcoming_limit=1, recent_limit=1)
                for key, bucket in sports.get("clubs", {}).items()
            },
        },
    }
    return (
        'Devuelve solo JSON valido con las claves "headline", "ai_report_sections", "summary", "mobility_alerts", "climate", "holidays", "germany", "sports", "watchlist". '
        'En "ai_report_sections" usa exactamente las claves "clima_forecast", "movilidad_alertas", "alemania", "deportes", "festivos". '
        "No incluyas article_translations ni markdown. Devuelve JSON pequeno, limpio y valido.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


def azure_chat_completion(
    endpoint: str,
    api_key: str,
    deployment: str,
    api_version: str,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> dict[str, Any]:
    body = {
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
    raw = fetch_url(
        url,
        headers={"Content-Type": "application/json", "api-key": api_key},
        data=json.dumps(body).encode("utf-8"),
    )
    return json.loads(raw.decode("utf-8"))


def parse_or_repair_llm_json(
    content: str,
    endpoint: str,
    api_key: str,
    deployment: str,
    api_version: str,
) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        stripped = content.strip()
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = stripped[first_brace:last_brace + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        repair_messages = [
            {
                "role": "system",
                "content": "Repara JSON roto. Devuelve solo JSON valido sin markdown ni explicaciones.",
            },
            {
                "role": "user",
                "content": (
                    "Convierte este contenido en JSON valido preservando la intencion original. "
                    "Si falta cerrar cadenas u objetos, completalos de forma conservadora. "
                    "Devuelve solo JSON valido.\n\n"
                    f"{content}"
                ),
            },
        ]
        repaired_payload = azure_chat_completion(
            endpoint,
            api_key,
            deployment,
            api_version,
            repair_messages,
            1800,
        )
        repaired_content = repaired_payload["choices"][0]["message"]["content"]
        return json.loads(repaired_content)


def generate_llm_digest(
    weather: dict[str, Any],
    articles: list[Article],
    holidays: list[Holiday],
    categories: dict[str, list[Article]],
    sports: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").rstrip("/")
    api_key = os.getenv("AZURE_OPENAI_API_KEY", "")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_MODEL", "")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
    if not endpoint or not api_key or not deployment:
        return (
            fallback_digest(weather, articles, holidays, categories, sports),
            {"source": "fallback", "reason": "missing_azure_config"},
        )
    messages = [
        {"role": "system", "content": "Eres un analista local de Frankfurt extremadamente practico. Prioriza impacto real y accion inmediata."},
        {"role": "user", "content": build_llm_prompt(weather, articles, holidays, categories, sports)},
    ]
    try:
        payload = azure_chat_completion(
            endpoint,
            api_key,
            deployment,
            api_version,
            messages,
            1600,
        )
        choice = payload["choices"][0]
        content = choice["message"]["content"]
        digest = parse_or_repair_llm_json(content, endpoint, api_key, deployment, api_version)
        finish_reason = choice.get("finish_reason")
        return digest, {"source": "azure_llm", "reason": None if finish_reason != "length" else "azure_length_truncated_but_repaired"}
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError) as exc:
        try:
            reduced_messages = [
                {"role": "system", "content": "Eres un analista local de Frankfurt extremadamente practico. Devuelve JSON pequeno y valido."},
                {"role": "user", "content": build_reduced_llm_prompt(weather, holidays, categories, sports)},
            ]
            reduced_payload = azure_chat_completion(
                endpoint,
                api_key,
                deployment,
                api_version,
                reduced_messages,
                900,
            )
            reduced_content = reduced_payload["choices"][0]["message"]["content"]
            reduced_digest = parse_or_repair_llm_json(reduced_content, endpoint, api_key, deployment, api_version)
            return reduced_digest, {"source": "azure_llm", "reason": "azure_reduced_retry"}
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError, TimeoutError):
            pass
        return (
            fallback_digest(weather, articles, holidays, categories, sports),
            {"source": "fallback", "reason": f"azure_error: {exc}"},
        )


def stringify_digest_item(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (int, float, bool)):
        return str(item)
    if isinstance(item, dict):
        preferred_keys = (
            "text",
            "title",
            "headline",
            "summary",
            "label",
            "name",
            "value",
            "content",
            "descripcion",
            "description",
        )
        parts = [str(item[key]).strip() for key in preferred_keys if item.get(key)]
        if parts:
            return " - ".join(parts[:2])
        compact_parts = [f"{key}: {value}" for key, value in item.items() if value not in (None, "", [], {})]
        return " - ".join(compact_parts[:2])
    if isinstance(item, list):
        parts = [stringify_digest_item(value) for value in item]
        return " - ".join(part for part in parts if part)
    return str(item).strip()


def normalize_digest_section(value: Any, fallback: list[str]) -> list[str]:
    if value in (None, "", [], {}):
        return fallback
    if not isinstance(value, list):
        value = [value]
    normalized = [stringify_digest_item(item) for item in value]
    expanded: list[str] = []
    for item in normalized:
        if not item:
            continue
        if "///" in item:
            expanded.extend(part.strip() for part in item.split("///") if part.strip())
            continue
        expanded.append(item)
    normalized = expanded
    return normalized or fallback


def normalize_digest_payload(digest: dict[str, Any]) -> dict[str, list[str] | str]:
    headline = stringify_digest_item(digest.get("headline")) or "Briefing local para Frankfurt con foco en movilidad y ciudad"
    ai_report_sections = digest.get("ai_report_sections") if isinstance(digest.get("ai_report_sections"), dict) else {}
    ai_report_fallback = []
    if ai_report_sections:
        ai_report_fallback = [
            ai_report_sections.get("clima_forecast"),
            ai_report_sections.get("movilidad_alertas"),
            ai_report_sections.get("alemania"),
            ai_report_sections.get("deportes"),
            ai_report_sections.get("festivos"),
        ]
    normalized = {
        "headline": headline,
        "ai_report": normalize_digest_section(
            digest.get("ai_report", ai_report_fallback),
            [],
        ),
        "summary": normalize_digest_section(
            digest.get("summary", digest.get("takeaways")),
            ["Sin titulares destacados en esta actualizacion."],
        ),
        "mobility_alerts": normalize_digest_section(
            digest.get("mobility_alerts", digest.get("commute_plan")),
            ["Sin novedades claras de movilidad o alertas en esta actualizacion."],
        ),
        "climate": normalize_digest_section(
            digest.get("climate"),
            ["Sin resumen meteorologico disponible en esta actualizacion."],
        ),
        "holidays": normalize_digest_section(
            digest.get("holidays"),
            ["Sin festivos cercanos destacados."],
        ),
        "germany": normalize_digest_section(
            digest.get("germany"),
            ["Sin novedades destacadas de Alemania en esta actualizacion."],
        ),
        "sports": normalize_digest_section(
            digest.get("sports"),
            ["Sin agenda deportiva cercana detectada en esta actualizacion."],
        ),
        "watchlist": normalize_digest_section(
            digest.get("watchlist"),
            ["Seguir movilidad, avisos y clima en la proxima actualizacion."],
        ),
    }
    return normalized


def format_datetime(value: datetime) -> str:
    months = {
        1: "enero",
        2: "febrero",
        3: "marzo",
        4: "abril",
        5: "mayo",
        6: "junio",
        7: "julio",
        8: "agosto",
        9: "septiembre",
        10: "octubre",
        11: "noviembre",
        12: "diciembre",
    }
    local = value.astimezone(TIMEZONE)
    return f"{local.day} {months[local.month]} {local.year}, {local:%H:%M} h"


def format_day_label(value: datetime) -> str:
    local = value.astimezone(TIMEZONE)
    return f"{WEEKDAY_LABELS[local.weekday()]} {local.day}/{local.month}"


def serialize_day_forecast(day: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": day["date"].date().isoformat(),
        "weekday": day["weekday"],
        "temp_max": day["temp_max"],
        "temp_min": day["temp_min"],
        "precipitation_probability_max": day["precipitation_probability_max"],
        "weather_code": day["weather_code"],
        "weather_label": WEATHER_CODE_LABELS.get(day["weather_code"], "Condiciones variables"),
    }


def impact_class(label: str) -> str:
    return {"Alta": "impact-high", "Media": "impact-medium"}.get(label, "impact-low")


def apply_article_translations(categories: dict[str, list[Article]], digest: dict[str, Any]) -> None:
    translations = digest.get("article_translations")
    if not isinstance(translations, list):
        return
    by_link: dict[str, dict[str, Any]] = {}
    for item in translations:
        if not isinstance(item, dict):
            continue
        link = str(item.get("link") or "").strip()
        if not link:
            continue
        by_link[link] = item
    if not by_link:
        return
    for articles in categories.values():
        for article in articles:
            translated = by_link.get(article.link)
            if not translated:
                continue
            translated_title = stringify_digest_item(translated.get("translated_title"))
            translated_description = stringify_digest_item(translated.get("translated_description"))
            if translated_title:
                article.translated_title = translated_title
            if translated_description:
                article.translated_description = translated_description


def priority_dot_class(label: str) -> str:
    return {"Alta": "p-high", "Media": "p-mid"}.get(label, "p-low")


def digest_tag_class(value: str) -> str:
    normalized = normalize_text(value)
    if normalized in {"streik", "warnung", "sperrung", "unwetter", "u7", "huelga"}:
        return "tag-red"
    if normalized in {"rmv", "vgf", "frankfurt", "a3", "verkehr", "movilidad"}:
        return "tag-blue"
    if normalized in {"polizei", "feuerwehr", "baustelle", "finanzas", "festivo"}:
        return "tag-yellow"
    return "tag-green"


def render_tags(values: list[str], limit: int = 3) -> str:
    tags = []
    for raw_value in values[:limit]:
        value = stringify_digest_item(raw_value)
        if not value:
            continue
        tags.append(f'<span class="tag {digest_tag_class(value)}">{html.escape(value)}</span>')
    return "".join(tags)


def format_header_date(value: datetime) -> str:
    months = {
        1: "ENE",
        2: "FEB",
        3: "MAR",
        4: "ABR",
        5: "MAY",
        6: "JUN",
        7: "JUL",
        8: "AGO",
        9: "SEP",
        10: "OCT",
        11: "NOV",
        12: "DIC",
    }
    local = value.astimezone(TIMEZONE)
    return f"{local.day:02d} {months[local.month]} {local.year}"


def format_time_short(value: datetime) -> str:
    local = value.astimezone(TIMEZONE)
    return f"{local:%H:%M} h"


def article_card(article: Article) -> str:
    visible_title = article.translated_title or article.title
    raw_description = article.translated_description or article.description
    description = raw_description[:190] + ("..." if len(raw_description) > 190 else "")
    init_hint = article.initialization_hint
    tags = render_tags(article.matched_terms)
    return f"""
      <a class="news-item" href="{html.escape(article.link)}" target="_blank" rel="noreferrer">
        <div class="priority-dot {priority_dot_class(article.impact_label)}"></div>
        <div>
          <div class="news-source">{html.escape(article.source)}</div>
          <div class="news-title">{html.escape(visible_title)}</div>
          <div class="news-summary">{html.escape(description)}</div>
          {f'<div class="news-summary">{html.escape(init_hint)}</div>' if init_hint else ''}
          {f'<div>{tags}</div>' if tags else ''}
        </div>
        <div class="news-time">{html.escape(article.age_text)}</div>
      </a>
    """


def forecast_card(title: str, day: dict[str, Any]) -> str:
    rain_probability = int(day["precipitation_probability_max"])
    rain_class = " danger" if rain_probability >= 60 else ""
    today_class = " today" if normalize_text(title) == "hoy" else ""
    rain_label = "Lluvia" if rain_probability >= 40 else "Seco"
    return f"""
      <article class="day-card{today_class}">
        <div class="day-name">{html.escape(title)} · {html.escape(format_day_label(day['date']))}</div>
        <div class="day-range">{day['temp_max']:.0f}° <span class="low">/ {day['temp_min']:.0f}°</span></div>
        <div class="day-cond">{html.escape(WEATHER_CODE_LABELS.get(day['weather_code'], 'Variable'))}</div>
        <div class="day-rain">{rain_label} · {rain_probability}% lluvia<div class="rain-bar"><div class="rain-fill{rain_class}" style="width:{max(0, min(rain_probability, 100))}%"></div></div></div>
      </article>
    """


def holiday_card(holiday: Holiday) -> str:
    local = holiday.date.astimezone(TIMEZONE)
    delta_days = max(0, (local.date() - datetime.now(TIMEZONE).date()).days)
    badge_value = "HOY" if delta_days == 0 else str(delta_days)
    badge_suffix = "ACTIVO" if delta_days == 0 else "DIAS"
    scope = "Hesse" if holiday.is_regional else "Nacional"
    return f"""
      <article class="holiday-card">
        <div class="days-badge">{html.escape(badge_value)}<small>{html.escape(badge_suffix)}</small></div>
        <div>
          <div class="holiday-name">{html.escape(holiday.name)}</div>
          <div class="holiday-date">{html.escape(format_day_label(holiday.date))}</div>
          <span class="tag tag-yellow">{html.escape(scope)}</span>
        </div>
      </article>
    """


def sports_event_item(event: dict[str, Any]) -> str:
    source = event.get("source") or event.get("competition") or "Agenda"
    detail_parts = [event.get("result", ""), event.get("details", "")]
    detail_text = " · ".join(part for part in detail_parts if part)
    href = html.escape(event.get("link") or "#")
    dot_class = "p-high" if event.get("status") == "Upcoming" else "p-low"
    return f"""
      <a class="news-item sports-news-item" href="{href}" target="_blank" rel="noreferrer">
        <div class="priority-dot {dot_class}"></div>
        <div>
          <div class="news-source">{html.escape(source)}</div>
          <div class="news-title">{html.escape(event['title'])}</div>
          <div class="news-summary">{html.escape(sports_event_start_text(event))}</div>
          {f'<div class="news-summary">{html.escape(detail_text)}</div>' if detail_text else ''}
        </div>
        <div class="news-time">{html.escape(event.get('status') or '')}</div>
      </a>
    """


def sports_event_group(title: str, items: list[dict[str, Any]], empty_label: str) -> str:
    cards = "".join(sports_event_item(item) for item in items)
    return f"""
      <div class="sports-group">
        <h3 class="sports-subheading">{html.escape(title)}</h3>
        <div class="news-grid compact-news-grid">
          {cards or f'<div class="empty-panel">{html.escape(empty_label)}</div>'}
        </div>
      </div>
    """


def sports_column(title: str, bucket: dict[str, Any], empty_upcoming: str, empty_results: str) -> str:
    source = bucket.get("source", "")
    return f"""
      <section class="sports-panel">
        <div class="sports-panel-head">
          <h3>{html.escape(title)}</h3>
          {f'<span class="sports-source">{html.escape(source)}</span>' if source else ''}
        </div>
        {sports_event_group('Proximos eventos', bucket.get('upcoming', []), empty_upcoming)}
        {sports_event_group('Resultados recientes', bucket.get('recent_results', []), empty_results)}
      </section>
    """


def digest_section_card(title: str, items: list[str]) -> str:
    rows = "".join(f"<li>{html.escape(stringify_digest_item(item))}</li>" for item in items)
    return f"""
      <article class="mini-card">
        <div class="mini-card-title">{html.escape(title)}</div>
        <ul>{rows or '<li>Sin novedades relevantes.</li>'}</ul>
      </article>
    """


def ai_report_card(items: list[str], digest_meta: dict[str, Any]) -> str:
    if digest_meta.get("source") == "azure_llm" and items:
        paragraphs = "".join(f"<p>{html.escape(stringify_digest_item(item))}</p>" for item in items)
        body = f'<div class="ai-report-body">{paragraphs}</div>'
    else:
        reason = stringify_digest_item(digest_meta.get("reason")) or "No hubo conexion con Azure OpenAI."
        body = f'<p class="ai-report-error">No hubo conexion con Azure OpenAI.</p><p class="ai-report-detail">{html.escape(reason)}</p>'
    return f"""
      <section class="feature-panel">
        <div class="section-label">Informe IA</div>
        <div class="feature-panel-body">
          <h2>Resumen detallado agrupado</h2>
          {body}
        </div>
      </section>
    """


def alert_banner_html(categories: dict[str, list[Article]], digest: dict[str, Any]) -> str:
    featured_article = None
    for key in ("alerts", "commute"):
        items = categories.get(key) or []
        if items:
            featured_article = items[0]
            break
    if featured_article:
        body = featured_article.translated_description or featured_article.description or featured_article.title
        title = featured_article.translated_title or featured_article.title
        tags = render_tags(featured_article.matched_terms)
        return f"""
      <div class="alert-banner">
        <div class="alert-icon">!</div>
        <div>
          <div class="alert-title">{html.escape(title)}</div>
          <div class="alert-body">{html.escape(body[:220] + ('...' if len(body) > 220 else ''))}</div>
          {f'<div>{tags}</div>' if tags else ''}
        </div>
      </div>
    """
    alerts = digest.get("mobility_alerts", [])
    if alerts:
        return f"""
      <div class="alert-banner">
        <div class="alert-icon">!</div>
        <div>
          <div class="alert-title">Aviso operativo</div>
          <div class="alert-body">{html.escape(stringify_digest_item(alerts[0]))}</div>
        </div>
      </div>
    """
    return ""


def render_html(
    weather: dict[str, Any],
    digest: dict[str, Any],
    categories: dict[str, list[Article]],
    holidays: list[Holiday],
    sports: dict[str, Any],
    digest_meta: dict[str, Any],
    generated_at: datetime,
) -> str:
    digest = normalize_digest_payload(digest)
    weather_now = weather["current"]
    daily = weather["daily"]
    tomorrow = weather["tomorrow"]
    forecast_cards = [
        forecast_card("Hoy", daily),
        forecast_card("Manana", tomorrow),
    ]
    weekend_labels = ["Sabado", "Domingo"]
    for idx, day in enumerate(weather["weekend"][:2]):
        label = weekend_labels[idx] if idx < len(weekend_labels) else "Fin de semana"
        forecast_cards.append(forecast_card(label, day))
    holiday_cards = "".join(holiday_card(holiday) for holiday in holidays)
    sports_errors = "".join(f"<li>{html.escape(item)}</li>" for item in sports.get("errors", []))
    llm_status = ""
    if digest_meta.get("source") != "azure_llm":
        llm_status = '<div class="system-note">Fallback local activo: no hubo conexion con Azure OpenAI en esta ejecucion.</div>'
    hourly_cards = []
    for hour in weather["next_hours"]:
        rain_class = " high" if hour["precipitation_probability"] >= 40 else ""
        hourly_cards.append(
            f"""
            <div class="fc-item">
              <div class="fc-hour">{hour['time']:%H:%M}</div>
              <div class="fc-temp">{hour['temperature']:.0f}°</div>
              <div class="fc-rain{rain_class}">{hour['precipitation_probability']:.0f}%</div>
            </div>
            """
        )
    category_sections = []
    for config in CATEGORY_CONFIGS:
        cards = "".join(article_card(article) for article in categories.get(config["key"], []))
        category_sections.append(
            f"""
            <section>
              <div class="section-label">{html.escape(config['label'])}</div>
              <div class="news-grid">
                {cards or '<div class="empty-panel">No se han recuperado titulares para esta seccion.</div>'}
              </div>
            </section>
            """
        )
    summary_cards = "".join(
        [
            digest_section_card("Resumen operativo", digest.get("summary", [])),
            digest_section_card("Movilidad y alertas", digest.get("mobility_alerts", [])),
            digest_section_card("Alemania", digest.get("germany", [])),
            digest_section_card("Deportes", digest.get("sports", [])),
            digest_section_card("Clima", digest.get("climate", [])),
            digest_section_card("Vigilar", digest.get("watchlist", [])),
        ]
    )
    ai_report_html = ai_report_card(digest.get("ai_report", []), digest_meta)
    club_columns = "".join(
        sports_column(
            team_name,
            team_bucket,
            f"Sin partido cercano detectado para {team_name}.",
            f"Sin resultado reciente detectado para {team_name}.",
        )
        for team_name, team_bucket in sports.get("clubs", {}).items()
    )
    alert_banner = alert_banner_html(categories, digest)
    sports_section = f"""
      <section>
        <div class="section-label">Deporte</div>
        <div class="sports-grid">
          {sports_column('Champions League', sports.get('champions', {}), 'No hay partidos cercanos detectados de Champions League.', 'No hay resultados recientes detectados de Champions League.')}
          {sports_column('Formula 1', sports.get('formula1', {}), 'No hay gran premio cercano detectado.', 'No hay resultados recientes detectados de Formula 1.')}
          {sports_column('MotoGP', sports.get('motogp', {}), 'No hay carrera cercana detectada de MotoGP.', 'No hay resultados recientes detectados de MotoGP.')}
          {sports_column('Carlos Alcaraz', sports.get('alcaraz', {}), 'No se ha detectado partido cercano de Alcaraz.', 'No se ha detectado resultado reciente de Alcaraz.')}
        </div>
        <div class="sports-grid club-grid">
          {club_columns}
        </div>
        {'<ul class="inline-errors">' + sports_errors + '</ul>' if sports_errors else ''}
      </section>
    """
    return f"""<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Noticias Frankfurt | Briefing local</title>
    <meta name="description" content="Resumen local de Frankfurt con foco en transporte, alertas, clima y contexto urbano util para el dia." />
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,600;1,9..40,300&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body>
    <header>
      <div class="logo">Frankfurt<span>.</span>Briefing</div>
      <div class="header-meta">
        <div><span class="live-dot"></span>EN VIVO · {html.escape(format_header_date(generated_at))}</div>
        <div>Actualizado {html.escape(format_time_short(generated_at))}</div>
      </div>
    </header>

    <main>
      <section class="hero-block">
        <div class="headline-panel">
          <div class="section-label">Resumen principal</div>
          <h1>{html.escape(digest.get("headline", "Briefing local para Frankfurt"))}</h1>
          <p class="hero-text">Solo incluye noticias de las ultimas 24 horas, clima de hoy y manana, proximo fin de semana y festivos cercanos.</p>
          {llm_status}
        </div>
      </section>

      <section>
        <div class="section-label">Clima ahora</div>
        <div class="climate-strip">
          <div>
            <div class="temp-now">{weather_now['temperature']:.1f}<sub>°C</sub></div>
            <div class="climate-desc">{html.escape(WEATHER_CODE_LABELS.get(weather_now['weather_code'], 'Condiciones variables'))} · Sensacion {weather_now['apparent_temperature']:.1f}°C</div>
          </div>
          <div class="climate-stats">
            <div class="stat-row">
              <div class="stat"><div class="stat-val">{weather_now['precipitation_probability']:.0f}%</div><div class="stat-label">lluvia ahora</div></div>
              <div class="stat"><div class="stat-val">{weather_now['wind_speed']:.0f} km/h</div><div class="stat-label">viento</div></div>
              <div class="stat"><div class="stat-val">{daily['temp_min']:.0f}° / {daily['temp_max']:.0f}°</div><div class="stat-label">rango hoy</div></div>
            </div>
            <div class="forecast-scroll">{''.join(hourly_cards)}</div>
          </div>
          <div></div>
        </div>
      </section>

      <section>
        <div class="section-label">Hoy, manana y fin de semana</div>
        <div class="day-cards">
          {''.join(forecast_cards) or '<div class="empty-panel">No hay previsiones disponibles.</div>'}
        </div>
      </section>

      {alert_banner}
      {ai_report_html}

      <section>
        <div class="section-label">Radar operativo</div>
        <div class="mini-grid">
          {summary_cards}
        </div>
      </section>

      <section>
        <div class="section-label">Festivos cercanos - Alemania / Hesse</div>
        <div class="holiday-row">
          {holiday_cards or '<div class="empty-panel">No hay festivos en los proximos 45 dias.</div>'}
        </div>
      </section>

      {sports_section}
      {''.join(category_sections)}
    </main>

    <footer>
      <span>Fuentes: Google News RSS · Open-Meteo · Nager.Date · ESPN · Formula1.com</span>
      <span>Frankfurt am Main, Hesse, DE</span>
    </footer>
  </body>
</html>
"""


def write_output(html_document: str, summary: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "index.html").write_text(html_document, encoding="utf-8")
    shutil.copyfile(ASSETS_DIR / "styles.css", OUTPUT_DIR / "styles.css")
    (OUTPUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    load_dotenv(ROOT / ".env")
    generated_at = datetime.now(TIMEZONE)
    categories: dict[str, list[Article]] = {}
    all_articles: list[Article] = []
    errors: list[str] = []
    for category in CATEGORY_CONFIGS:
        try:
            raw_articles = parse_google_news_feed(category)
            recent_articles = [article for article in raw_articles if is_recent_article(article, generated_at)]
            articles = [score_article(article) for article in recent_articles]
            articles = sort_articles(deduplicate_articles(articles))[: category["limit"]]
            categories[category["key"]] = articles
            all_articles.extend(articles)
        except Exception as exc:  # noqa: BLE001
            categories[category["key"]] = []
            errors.append(f"{category['label']}: {exc}")
    try:
        weather = fetch_weather()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Weather: {exc}")
        weather = {
            "current": {"time": generated_at, "temperature": 0, "apparent_temperature": 0, "precipitation_probability": 0, "weather_code": 3, "wind_speed": 0},
            "next_hours": [],
            "daily": {"date": generated_at, "weekday": WEEKDAY_LABELS[generated_at.weekday()], "temp_max": 0, "temp_min": 0, "precipitation_probability_max": 0, "weather_code": 3},
            "tomorrow": {"date": generated_at + timedelta(days=1), "weekday": WEEKDAY_LABELS[(generated_at + timedelta(days=1)).weekday()], "temp_max": 0, "temp_min": 0, "precipitation_probability_max": 0, "weather_code": 3},
            "weekend": [],
            "daily_entries": [],
        }
    try:
        holidays = fetch_nearby_holidays(generated_at)
    except Exception as exc:  # noqa: BLE001
        holidays = []
        errors.append(f"Holidays: {exc}")
    try:
        sports = fetch_sports_agenda()
    except Exception as exc:  # noqa: BLE001
        sports = empty_sports_agenda()
        sports["errors"] = [str(exc)]
        errors.append(f"Sports: {exc}")
    digest, digest_meta = generate_llm_digest(
        weather,
        sort_articles(deduplicate_articles(all_articles)),
        holidays,
        categories,
        sports,
    )
    apply_article_translations(categories, digest)
    if errors:
        digest["watchlist"] = list(digest.get("watchlist", [])) + [f"Error de captura: {item}" for item in errors[:2]]
    write_output(
        render_html(weather, digest, categories, holidays, sports, digest_meta, generated_at),
        {
            "generated_at": generated_at.isoformat(),
            "stories": sum(len(items) for items in categories.values()),
            "news_window_hours": NEWS_WINDOW_HOURS,
            "holidays_found": len(holidays),
            "sports_loaded": {
                "champions": {
                    "upcoming": len((sports.get("champions", {}) or {}).get("upcoming", [])),
                    "recent_results": len((sports.get("champions", {}) or {}).get("recent_results", [])),
                },
                "formula1": {
                    "upcoming": len((sports.get("formula1", {}) or {}).get("upcoming", [])),
                    "recent_results": len((sports.get("formula1", {}) or {}).get("recent_results", [])),
                },
                "motogp": {
                    "upcoming": len((sports.get("motogp", {}) or {}).get("upcoming", [])),
                    "recent_results": len((sports.get("motogp", {}) or {}).get("recent_results", [])),
                },
                "alcaraz": {
                    "upcoming": len((sports.get("alcaraz", {}) or {}).get("upcoming", [])),
                    "recent_results": len((sports.get("alcaraz", {}) or {}).get("recent_results", [])),
                },
                "clubs": {
                    club: {
                        "upcoming": len((bucket or {}).get("upcoming", [])),
                        "recent_results": len((bucket or {}).get("recent_results", [])),
                    }
                    for club, bucket in sports.get("clubs", {}).items()
                },
            },
            "digest_source": digest_meta["source"],
            "digest_reason": digest_meta["reason"],
            "errors": errors,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
