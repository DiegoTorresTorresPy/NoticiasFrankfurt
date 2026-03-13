from __future__ import annotations

import html
import json
import os
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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

SPORTSDB_BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"
CHAMPIONS_LEAGUE_ID = "4480"
FORMULA_ONE_ID = "4370"
MOTOGP_ID = "4407"
TRACKED_CLUBS = [
    ("Real Madrid", "Real Madrid"),
    ("FC Barcelona", "Barcelona"),
    ("Atletico Madrid", "Atletico de Madrid"),
]

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


def parse_google_news_feed(category: dict[str, Any]) -> list[Article]:
    query = urllib.parse.quote_plus(category["query"])
    url = f"https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de"
    root = ET.fromstring(fetch_url(url))
    articles: list[Article] = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
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
            )
        )
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


def parse_sports_datetime(event: dict[str, Any]) -> datetime | None:
    raw_timestamp = event.get("strTimestamp")
    if raw_timestamp:
        normalized = raw_timestamp.replace(" ", "T").replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
            return parsed.astimezone(TIMEZONE)
        except ValueError:
            pass

    date_value = event.get("dateEvent")
    time_value = (event.get("strTime") or "00:00:00").replace("Z", "")
    if not date_value:
        return None
    try:
        parsed = datetime.fromisoformat(f"{date_value}T{time_value}")
    except ValueError:
        try:
            parsed = datetime.fromisoformat(f"{date_value}T00:00:00")
        except ValueError:
            return None
    return parsed.replace(tzinfo=TIMEZONE)


def normalize_sports_event(event: dict[str, Any], label: str | None = None) -> dict[str, Any]:
    start_time = parse_sports_datetime(event)
    home = event.get("strHomeTeam") or ""
    away = event.get("strAwayTeam") or ""
    title = event.get("strEvent") or "Evento"
    if home and away:
        title = f"{home} vs {away}"
    return {
        "title": title,
        "competition": label or event.get("strLeague") or event.get("strSport") or "Deporte",
        "round": event.get("strRound") or event.get("strSeason") or "",
        "venue": event.get("strVenue") or event.get("strCircuit") or "",
        "start_time": start_time,
        "start_text": format_datetime(start_time) if start_time else "Hora pendiente",
        "status": event.get("strStatus") or "",
    }


def fetch_next_league_events(league_id: str, label: str, limit: int = 4) -> list[dict[str, Any]]:
    payload = fetch_json(f"{SPORTSDB_BASE_URL}/eventsnextleague.php?id={league_id}")
    events = payload.get("events") or []
    normalized = [normalize_sports_event(event, label) for event in events]
    normalized = [event for event in normalized if event["start_time"]]
    normalized.sort(key=lambda item: item["start_time"])
    return normalized[:limit]


def fetch_team_next_matches(team_name: str, label: str, limit: int = 2) -> list[dict[str, Any]]:
    team_payload = fetch_json(f"{SPORTSDB_BASE_URL}/searchteams.php?t={urllib.parse.quote_plus(team_name)}")
    teams = team_payload.get("teams") or []
    if not teams:
        return []
    team_id = teams[0].get("idTeam")
    if not team_id:
        return []
    events_payload = fetch_json(f"{SPORTSDB_BASE_URL}/eventsnext.php?id={team_id}")
    events = events_payload.get("events") or []
    normalized = [normalize_sports_event(event) for event in events]
    normalized = [event for event in normalized if event["start_time"]]
    normalized.sort(key=lambda item: item["start_time"])
    for event in normalized:
        event["competition"] = label
    return normalized[:limit]


def fetch_alcaraz_matches(days: int = 7, limit: int = 3) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offset in range(days):
        target_day = datetime.now(TIMEZONE).date() + timedelta(days=offset)
        payload = fetch_json(f"{SPORTSDB_BASE_URL}/eventsday.php?d={target_day.isoformat()}&s=Tennis")
        events = payload.get("events") or []
        for event in events:
            haystack = " ".join(
                filter(
                    None,
                    [
                        event.get("strEvent"),
                        event.get("strHomeTeam"),
                        event.get("strAwayTeam"),
                    ],
                )
            ).lower()
            if "alcaraz" not in haystack:
                continue
            normalized = normalize_sports_event(event, "Tenis")
            event_key = f"{normalized['title']}|{normalized['start_text']}"
            if event_key in seen:
                continue
            seen.add(event_key)
            matches.append(normalized)
    matches.sort(key=lambda item: item["start_time"] or datetime.max.replace(tzinfo=TIMEZONE))
    return matches[:limit]


def fetch_sports_agenda() -> dict[str, Any]:
    agenda = {
        "champions": [],
        "formula1": [],
        "motogp": [],
        "alcaraz": [],
        "clubs": {},
        "errors": [],
    }
    loaders = [
        ("champions", lambda: fetch_next_league_events(CHAMPIONS_LEAGUE_ID, "Champions League", 4)),
        ("formula1", lambda: fetch_next_league_events(FORMULA_ONE_ID, "Formula 1", 3)),
        ("motogp", lambda: fetch_next_league_events(MOTOGP_ID, "MotoGP", 3)),
        ("alcaraz", lambda: fetch_alcaraz_matches()),
    ]
    for key, loader in loaders:
        try:
            agenda[key] = loader()
        except Exception as exc:  # noqa: BLE001
            agenda["errors"].append(f"{key}: {exc}")
    for team_query, team_label in TRACKED_CLUBS:
        try:
            agenda["clubs"][team_label] = fetch_team_next_matches(team_query, team_label)
        except Exception as exc:  # noqa: BLE001
            agenda["clubs"][team_label] = []
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

    sports_items = []
    for key in ("champions", "formula1", "motogp", "alcaraz"):
        if sports.get(key):
            sports_items.append(f"{sports[key][0]['competition']}: {sports[key][0]['title']} ({sports[key][0]['start_text']}).")
    for club_name, club_events in sports.get("clubs", {}).items():
        if club_events:
            sports_items.append(f"{club_name}: {club_events[0]['title']} ({club_events[0]['start_text']}).")
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
        "round": event.get("round", ""),
        "venue": event.get("venue", ""),
        "start_time": event["start_time"].isoformat() if isinstance(event.get("start_time"), datetime) else event.get("start_time"),
        "start_text": event.get("start_text", ""),
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
            "champions": [serialize_sports_event(event) for event in sports.get("champions", [])[:3]],
            "formula1": [serialize_sports_event(event) for event in sports.get("formula1", [])[:2]],
            "motogp": [serialize_sports_event(event) for event in sports.get("motogp", [])[:2]],
            "alcaraz": [serialize_sports_event(event) for event in sports.get("alcaraz", [])[:2]],
            "clubs": {
                key: [serialize_sports_event(event) for event in items[:2]]
                for key, items in sports.get("clubs", {}).items()
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


def article_card(article: Article) -> str:
    tags = "".join(f"<li>{html.escape(term)}</li>" for term in article.matched_terms[:3])
    visible_title = article.translated_title or article.title
    raw_description = article.translated_description or article.description
    description = raw_description[:220] + ("..." if len(raw_description) > 220 else "")
    return f"""
        <article class="story-card">
          <div class="story-meta">
            <span class="impact-pill {impact_class(article.impact_label)}">{html.escape(article.impact_label)} prioridad</span>
            <span>{html.escape(article.source)}</span>
            <span>{html.escape(article.age_text)}</span>
          </div>
          <h3><a href="{html.escape(article.link)}" target="_blank" rel="noreferrer">{html.escape(visible_title)}</a></h3>
          <p>{html.escape(description)}</p>
          <ul class="story-tags">{tags}</ul>
        </article>
    """


def forecast_card(title: str, day: dict[str, Any]) -> str:
    return f"""
        <article class="forecast-card">
          <p class="eyebrow">{html.escape(title)}</p>
          <h3>{html.escape(format_day_label(day['date']))}</h3>
          <strong>{day['temp_min']:.0f}° / {day['temp_max']:.0f}°</strong>
          <p>{html.escape(WEATHER_CODE_LABELS.get(day['weather_code'], 'Variable'))}</p>
          <span>{day['precipitation_probability_max']:.0f}% lluvia</span>
        </article>
    """


def holiday_card(holiday: Holiday) -> str:
    scope = "Solo Hesse" if holiday.is_regional else "Nacional"
    return f"""
        <article class="holiday-card">
          <span class="impact-pill impact-low">{html.escape(holiday.countdown_label)}</span>
          <h3>{html.escape(holiday.name)}</h3>
          <p>{html.escape(format_day_label(holiday.date))}</p>
          <span>{html.escape(scope)}</span>
        </article>
    """


def sports_event_item(event: dict[str, Any]) -> str:
    meta_parts = [event["competition"]]
    if event.get("round"):
        meta_parts.append(str(event["round"]))
    if event.get("venue"):
        meta_parts.append(event["venue"])
    meta = " · ".join(part for part in meta_parts if part)
    return f"""
        <article class="sports-item">
          <h3>{html.escape(event['title'])}</h3>
          <p>{html.escape(event['start_text'])}</p>
          <span>{html.escape(meta)}</span>
        </article>
    """


def sports_column(title: str, items: list[dict[str, Any]], empty_label: str) -> str:
    cards = "".join(sports_event_item(item) for item in items)
    return f"""
        <section class="sports-column">
          <p class="eyebrow">{html.escape(title)}</p>
          <div class="sports-list">
            {cards or f'<p class="empty-state">{html.escape(empty_label)}</p>'}
          </div>
        </section>
    """


def digest_section_card(title: str, items: list[str]) -> str:
    rows = "".join(f"<li>{html.escape(stringify_digest_item(item))}</li>" for item in items)
    return f"""
        <article class="digest-card section-card">
          <p class="eyebrow">{html.escape(title)}</p>
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
        <section class="content-block ai-report-card">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Informe generado por IA</p>
              <h2>Resumen detallado agrupado</h2>
            </div>
          </div>
          {body}
        </section>
    """


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
    weekend_cards = "".join(forecast_card("Fin de semana", day) for day in weather["weekend"])
    holiday_cards = "".join(holiday_card(holiday) for holiday in holidays)
    sports_errors = "".join(f"<li>{html.escape(item)}</li>" for item in sports.get("errors", []))
    llm_status = ""
    if digest_meta.get("source") != "azure_llm":
        llm_status = '<p class="status-banner status-error">No hubo conexion con Azure OpenAI. Se muestra el fallback local.</p>'
    hourly_cards = []
    for hour in weather["next_hours"]:
        hourly_cards.append(
            f"""
            <div class="hour-card">
              <span class="hour-time">{hour['time']:%H:%M}</span>
              <strong>{hour['temperature']:.0f}°</strong>
              <span>{html.escape(WEATHER_CODE_LABELS.get(hour['weather_code'], 'Variable'))}</span>
              <span>{hour['precipitation_probability']:.0f}% lluvia</span>
            </div>
            """
        )
    category_sections = []
    for config in CATEGORY_CONFIGS:
        cards = "".join(article_card(article) for article in categories.get(config["key"], []))
        category_sections.append(
            f"""
            <section class="content-block">
              <div class="section-heading">
                <div>
                  <p class="eyebrow">{html.escape(config['label'])}</p>
                  <h2>{html.escape(config['description'])}</h2>
                </div>
              </div>
              <div class="story-grid">
                {cards or '<p class="empty-state">No se han recuperado titulares para esta seccion.</p>'}
              </div>
            </section>
            """
        )
    digest_cards = "".join(
        [
            digest_section_card("Resumen operativo", digest.get("summary", [])),
            digest_section_card("Movilidad y alertas", digest.get("mobility_alerts", [])),
            digest_section_card("Clima", digest.get("climate", [])),
            digest_section_card("Festivos cercanos", digest.get("holidays", [])),
            digest_section_card("Alemania", digest.get("germany", [])),
            digest_section_card("Deportes", digest.get("sports", [])),
        ]
    )
    ai_report_html = ai_report_card(digest.get("ai_report", []), digest_meta)
    watchlist = "".join(f"<li>{html.escape(item)}</li>" for item in digest.get("watchlist", []))
    club_columns = "".join(
        sports_column(team_name, team_events, f"Sin partido cercano detectado para {team_name}.")
        for team_name, team_events in sports.get("clubs", {}).items()
    )
    sports_section = f"""
      <section class="content-block">
        <div class="section-heading">
          <div>
            <p class="eyebrow">Deporte</p>
            <h2>Champions, motor, tenis y proximos partidos de los grandes equipos espanoles</h2>
          </div>
        </div>
        <div class="sports-grid">
          {sports_column('Champions League', sports.get('champions', []), 'No hay partidos cercanos detectados de Champions League.')}
          {sports_column('Formula 1', sports.get('formula1', []), 'No hay gran premio cercano detectado.')}
          {sports_column('MotoGP', sports.get('motogp', []), 'No hay carrera cercana detectada de MotoGP.')}
          {sports_column('Carlos Alcaraz', sports.get('alcaraz', []), 'No se ha detectado partido cercano de Alcaraz.')}
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
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap" rel="stylesheet" />
    <link rel="stylesheet" href="./styles.css" />
  </head>
  <body>
    <main class="page-shell">
      <section class="hero">
        <div class="hero-copy">
          <p class="eyebrow">Frankfurt operativo</p>
          <h1>{html.escape(digest.get("headline", "Briefing local para Frankfurt"))}</h1>
          <p class="hero-text">Actualizado el {html.escape(format_datetime(generated_at))}. Solo incluye noticias de las ultimas 24 horas, clima de hoy y manana, proximo fin de semana y festivos cercanos.</p>
          {llm_status}
        </div>
        <div class="weather-panel">
          <div class="weather-main">
            <span class="eyebrow">Clima ahora</span>
            <strong>{weather_now['temperature']:.1f}°C</strong>
            <p>{html.escape(WEATHER_CODE_LABELS.get(weather_now['weather_code'], 'Condiciones variables'))}</p>
          </div>
          <div class="weather-stats">
            <div><span>Sensacion</span><strong>{weather_now['apparent_temperature']:.1f}°C</strong></div>
            <div><span>Lluvia</span><strong>{weather_now['precipitation_probability']:.0f}%</strong></div>
            <div><span>Viento</span><strong>{weather_now['wind_speed']:.0f} km/h</strong></div>
            <div><span>Rango hoy</span><strong>{daily['temp_min']:.0f}° / {daily['temp_max']:.0f}°</strong></div>
          </div>
          <div class="hour-strip">{''.join(hourly_cards)}</div>
        </div>
      </section>
      {ai_report_html}
      <section class="utility-grid">
        <article class="content-block compact-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Prevision diaria</p>
              <h2>Hoy, manana y fin de semana</h2>
            </div>
          </div>
          <div class="forecast-grid">
            {forecast_card("Hoy", daily)}
            {forecast_card("Manana", tomorrow)}
            {weekend_cards or '<p class="empty-state">No hay todavia datos de fin de semana.</p>'}
          </div>
        </article>
        <article class="content-block compact-block">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Calendario</p>
              <h2>Festivos cercanos en Alemania y Hesse</h2>
            </div>
          </div>
          <div class="holiday-grid">
            {holiday_cards or '<p class="empty-state">No hay festivos en los proximos 45 dias.</p>'}
          </div>
        </article>
      </section>
      <section class="digest-grid briefing-grid">
        {digest_cards}
      </section>
      <section class="digest-grid watchlist-grid">
        <article class="digest-card">
          <p class="eyebrow">Vigilar</p>
          <ul>{watchlist}</ul>
        </article>
      </section>
      {sports_section}
      {''.join(category_sections)}
      <footer class="site-footer">
        <p>Fuentes: Google News RSS, Open-Meteo, Nager.Date y TheSportsDB. El resumen usa Azure OpenAI si hay secretos configurados; si no, aplica reglas locales.</p>
      </footer>
    </main>
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
        sports = {"champions": [], "formula1": [], "motogp": [], "alcaraz": [], "clubs": {}, "errors": [str(exc)]}
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
                "champions": len(sports.get("champions", [])),
                "formula1": len(sports.get("formula1", [])),
                "motogp": len(sports.get("motogp", [])),
                "alcaraz": len(sports.get("alcaraz", [])),
                "clubs": {club: len(items) for club, items in sports.get("clubs", {}).items()},
            },
            "digest_source": digest_meta["source"],
            "digest_reason": digest_meta["reason"],
            "errors": errors,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
