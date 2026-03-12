from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Berlin")
TARGET_LAT = 50.1521
TARGET_LON = 8.6118
NEWS_WINDOW_HOURS = 24
HOLIDAY_LOOKAHEAD_DAYS = 45
COUNTRY_CODE = "DE"
REGION_CODE = "DE-HE"

CATEGORY_CONFIGS = [
    {
        "key": "commute",
        "label": "Movilidad y huelgas",
        "query": 'Frankfurt (RMV OR VGF OR U7 OR "U-Bahn" OR "S-Bahn" OR Nordwest OR Ostend OR Streik OR Sperrung OR Ostbahnhof)',
        "limit": 6,
    },
    {
        "key": "alerts",
        "label": "Alertas y emergencias",
        "query": 'Frankfurt (Warnung OR Alarm OR Polizei OR Feuerwehr OR Unwetter OR Bombenentschaerfung OR Sperrung)',
        "limit": 5,
    },
    {
        "key": "city",
        "label": "Ciudad y barrio",
        "query": '"Frankfurt am Main" (Stadt OR Verkehr OR Baustelle OR Rathaus OR Nordwest OR Innenstadt OR Ostend)',
        "limit": 5,
    },
    {
        "key": "social",
        "label": "Social, vivienda y contexto",
        "query": 'Frankfurt (Wohnen OR Miete OR Bildung OR Gesundheit OR Gesellschaft OR Kultur OR Wirtschaft)',
        "limit": 5,
    },
    {
        "key": "germany_economy",
        "label": "Alemania: economia y finanzas",
        "query": 'Deutschland (Wirtschaft OR Finanzen OR DAX OR Banken OR Inflation OR Unternehmen OR Boerse)',
        "limit": 5,
    },
    {
        "key": "germany_culture",
        "label": "Alemania: cultura y conciertos",
        "query": 'Deutschland (Kultur OR Konzert OR Festival OR Oper OR Ausstellung OR Museum OR Tournee)',
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


def fetch_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "FrankfurtNewsBriefing/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch_json(url: str) -> Any:
    return json.loads(fetch_url(url).decode("utf-8"))


def strip_html(value: str) -> str:
    return unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value))).strip()


def normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=TIMEZONE)
    return value.astimezone(TIMEZONE)


def parse_google_news_feed(category: dict[str, Any]) -> list[dict[str, Any]]:
    query = urllib.parse.quote_plus(category["query"])
    url = f"https://news.google.com/rss/search?q={query}&hl=de&gl=DE&ceid=DE:de"
    root = ET.fromstring(fetch_url(url))
    articles = []
    now = datetime.now(TIMEZONE)
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        published = None
        pub_date_raw = (item.findtext("pubDate") or "").strip()
        if pub_date_raw:
            try:
                published = normalize_datetime(parsedate_to_datetime(pub_date_raw))
            except (TypeError, ValueError):
                published = None
        if published is None:
            continue
        age_hours = (now - published).total_seconds() / 3600
        if age_hours < 0 or age_hours > NEWS_WINDOW_HOURS:
            continue
        description = strip_html(item.findtext("description") or "")
        haystack = f"{title} {description}".lower()
        score = 0
        matched_terms: list[str] = []
        for term, weight in KEYWORD_WEIGHTS.items():
            if term in haystack:
                score += weight
                matched_terms.append(term)
        score += 4 if age_hours <= 6 else 2
        if category["key"] == "commute":
            score += 2
        articles.append(
            {
                "title": title,
                "link": link,
                "source": (item.findtext("source") or "Google News").strip(),
                "description": description,
                "published_at": published.isoformat(),
                "age_hours": round(age_hours, 1),
                "category": category["label"],
                "score": score,
                "impact": "Alta" if score >= 14 else "Media" if score >= 8 else "Baja",
                "matched_terms": matched_terms[:4],
            }
        )
    deduped: dict[str, dict[str, Any]] = {}
    for article in articles:
        key = re.sub(r"\s+", " ", article["title"].lower()).strip()
        current = deduped.get(key)
        if current is None or article["score"] > current["score"]:
            deduped[key] = article
    ordered = sorted(deduped.values(), key=lambda item: (-item["score"], item["age_hours"]))
    return ordered[: category["limit"]]


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
        "time": hourly_times[current_idx].isoformat(),
        "temperature": data["hourly"]["temperature_2m"][current_idx],
        "apparent_temperature": data["hourly"]["apparent_temperature"][current_idx],
        "precipitation_probability": data["hourly"]["precipitation_probability"][current_idx],
        "weather_code": data["hourly"]["weather_code"][current_idx],
        "weather_label": WEATHER_CODE_LABELS.get(data["hourly"]["weather_code"][current_idx], "Variable"),
        "wind_speed": data["hourly"]["wind_speed_10m"][current_idx],
    }
    next_hours = []
    for idx in range(current_idx, min(current_idx + 8, len(hourly_times))):
        next_hours.append(
            {
                "time": hourly_times[idx].isoformat(),
                "temperature": data["hourly"]["temperature_2m"][idx],
                "precipitation_probability": data["hourly"]["precipitation_probability"][idx],
                "weather_code": data["hourly"]["weather_code"][idx],
                "weather_label": WEATHER_CODE_LABELS.get(data["hourly"]["weather_code"][idx], "Variable"),
            }
        )
    daily_entries = []
    for idx, raw_date in enumerate(data["daily"]["time"]):
        day = datetime.fromisoformat(raw_date).replace(tzinfo=TIMEZONE)
        daily_entries.append(
            {
                "date": day.date().isoformat(),
                "weekday": WEEKDAY_LABELS[day.weekday()],
                "temp_max": data["daily"]["temperature_2m_max"][idx],
                "temp_min": data["daily"]["temperature_2m_min"][idx],
                "precipitation_probability_max": data["daily"]["precipitation_probability_max"][idx],
                "weather_code": data["daily"]["weather_code"][idx],
                "weather_label": WEATHER_CODE_LABELS.get(data["daily"]["weather_code"][idx], "Variable"),
            }
        )
    next_saturday_index = next((idx for idx, entry in enumerate(daily_entries) if entry["weekday"] == "Sabado"), None)
    weekend = daily_entries[next_saturday_index:next_saturday_index + 2] if next_saturday_index is not None else []
    return {
        "current": current,
        "next_hours": next_hours,
        "today": daily_entries[0],
        "tomorrow": daily_entries[1] if len(daily_entries) > 1 else daily_entries[0],
        "weekend": weekend,
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
        "start_time": start_time.isoformat() if start_time else None,
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
    normalized = [normalize_sports_event(event, label) for event in events]
    normalized = [event for event in normalized if event["start_time"]]
    normalized.sort(key=lambda item: item["start_time"])
    return normalized[:limit]


def fetch_alcaraz_matches(days: int = 7, limit: int = 3) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for offset in range(days):
        target_day = datetime.now(TIMEZONE).date() + timedelta(days=offset)
        payload = fetch_json(f"{SPORTSDB_BASE_URL}/eventsday.php?d={target_day.isoformat()}&s=Tennis")
        events = payload.get("events") or []
        for event in events:
            haystack = " ".join(filter(None, [event.get("strEvent"), event.get("strHomeTeam"), event.get("strAwayTeam")])).lower()
            if "alcaraz" not in haystack:
                continue
            normalized = normalize_sports_event(event, "Tenis")
            event_key = f"{normalized['title']}|{normalized['start_time']}"
            if event_key in seen:
                continue
            seen.add(event_key)
            matches.append(normalized)
    matches.sort(key=lambda item: item["start_time"] or "")
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


def fetch_nearby_holidays() -> list[dict[str, Any]]:
    now = datetime.now(TIMEZONE)
    years = {now.year, (now + timedelta(days=HOLIDAY_LOOKAHEAD_DAYS)).year}
    holidays: dict[tuple[str, str], dict[str, Any]] = {}
    for year in sorted(years):
        url = f"https://date.nager.at/api/v3/PublicHolidays/{year}/{COUNTRY_CODE}"
        payload = json.loads(fetch_url(url).decode("utf-8"))
        for item in payload:
            holiday_date = datetime.fromisoformat(item["date"]).replace(tzinfo=TIMEZONE)
            delta_days = (holiday_date.date() - now.date()).days
            if delta_days < 0 or delta_days > HOLIDAY_LOOKAHEAD_DAYS:
                continue
            counties = item.get("counties") or []
            is_regional = REGION_CODE in counties
            if not item.get("global") and not is_regional:
                continue
            holidays[(item["localName"], item["date"])] = {
                "name": item["localName"],
                "date": item["date"],
                "countdown_days": delta_days,
                "scope": "regional" if is_regional and not item.get("global", False) else "national",
            }
    return sorted(holidays.values(), key=lambda item: item["date"])[:4]


def build_payload() -> dict[str, Any]:
    categories: dict[str, list[dict[str, Any]]] = {}
    all_articles: list[dict[str, Any]] = []
    errors: list[str] = []
    for category in CATEGORY_CONFIGS:
        try:
            items = parse_google_news_feed(category)
            categories[category["key"]] = items
            all_articles.extend(items)
        except Exception as exc:  # noqa: BLE001
            categories[category["key"]] = []
            errors.append(f"{category['label']}: {exc}")
    try:
        weather = fetch_weather()
    except Exception as exc:  # noqa: BLE001
        weather = {}
        errors.append(f"Weather: {exc}")
    try:
        holidays = fetch_nearby_holidays()
    except Exception as exc:  # noqa: BLE001
        holidays = []
        errors.append(f"Holidays: {exc}")
    try:
        sports = fetch_sports_agenda()
    except Exception as exc:  # noqa: BLE001
        sports = {"champions": [], "formula1": [], "motogp": [], "alcaraz": [], "clubs": {}, "errors": [str(exc)]}
        errors.append(f"Sports: {exc}")
    ordered_articles = sorted(all_articles, key=lambda item: (-item["score"], item["age_hours"]))
    return {
        "generated_at": datetime.now(TIMEZONE).isoformat(),
        "news_window_hours": NEWS_WINDOW_HOURS,
        "top_headlines": ordered_articles[:8],
        "categories": categories,
        "weather": weather,
        "holidays": holidays,
        "sports": sports,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Frankfurt local news, weather, and nearby holidays.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    args = parser.parse_args()
    payload = build_payload()
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
