from __future__ import annotations

import re
import urllib.parse
from datetime import date as _date
from typing import Optional

from eli.core.netguard import http_get_json


PLUGIN_ID = "weather"
ACTIONS = ["GET_WEATHER"]


def _get_json(url: str) -> dict:
    # Routed through the central network gate: fails closed (OfflineError) when
    # the Net toggle is off, exactly like NEWS_FETCH / WEB_SEARCH. open-meteo is
    # a free, key-less API, but it is still the internet — so it must be gated.
    return http_get_json(url, headers={"User-Agent": "ELI-Weather/1.0"})


def _geocode(location: str) -> dict:
    url = (
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urllib.parse.urlencode(
            {"name": location, "count": 1, "language": "en", "format": "json"}
        )
    )
    data = _get_json(url)
    hits = data.get("results") or []
    if not hits:
        raise ValueError(f"No location match for: {location}")
    return hits[0]


def _weather_code_text(code: int | None) -> str:
    table = {
        0: "clear",
        1: "mainly clear",
        2: "partly cloudy",
        3: "overcast",
        45: "fog",
        48: "depositing rime fog",
        51: "light drizzle",
        53: "moderate drizzle",
        55: "dense drizzle",
        56: "light freezing drizzle",
        57: "dense freezing drizzle",
        61: "slight rain",
        63: "moderate rain",
        65: "heavy rain",
        66: "light freezing rain",
        67: "heavy freezing rain",
        71: "slight snow",
        73: "moderate snow",
        75: "heavy snow",
        77: "snow grains",
        80: "slight rain showers",
        81: "moderate rain showers",
        82: "violent rain showers",
        85: "slight snow showers",
        86: "heavy snow showers",
        95: "thunderstorm",
        96: "thunderstorm with slight hail",
        99: "thunderstorm with heavy hail",
    }
    return table.get(code, f"code {code}" if code is not None else "unknown")


_DAY_WORDS = re.compile(
    r"(?i)\b(?:today|tonight|tomorrow|now|later|this (?:morning|afternoon|evening|weekend|week)|next week|"
    r"the weekend|the week|(?:on |next |this )?(?:mon|tues|wednes|thurs|fri|satur|sun)day)\b")


def clean_place(text: str) -> str:
    """A place name with any day words taken out: "tomorrow in Dublin" is Dublin, and
    "tomorrow" on its own is no place at all."""
    out = _DAY_WORDS.sub(" ", str(text or ""))
    out = re.sub(r"(?i)^\s*(?:in|at|for|near)\s+", "", re.sub(r"\s+", " ", out).strip(" ,?.!"))
    return out.strip(" ,?.!")


def _forecast_for(g: dict, label: str, day: _date) -> dict:
    """The forecast for one named day. The current conditions are not an answer to "tomorrow"."""
    url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(
            {
                "latitude": g["latitude"],
                "longitude": g["longitude"],
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 14,
                "timezone": "auto",
            }
        )
    )
    data = _get_json(url)
    daily = data.get("daily") or {}
    days = list(daily.get("time") or [])
    key = day.isoformat()
    when = day.strftime("%A %d %B").replace(" 0", " ")
    if key not in days:
        msg = f"The forecast for {label} only reaches {len(days)} days ahead, so I have nothing for {when} yet."
        return {"ok": False, "action": "GET_WEATHER", "error": "beyond_forecast", "content": msg, "response": msg,
                "location": label}
    i = days.index(key)

    def _at(name):
        values = daily.get(name) or []
        return values[i] if i < len(values) else None

    low, high, rain = _at("temperature_2m_min"), _at("temperature_2m_max"), _at("precipitation_probability_max")
    msg = f"Forecast for {label}, {when}: {low} to {high}°C, {_weather_code_text(_at('weather_code'))}"
    msg += f", {rain}% chance of rain." if rain is not None else "."
    return {"ok": True, "action": "GET_WEATHER", "content": msg, "response": msg, "location": label,
            "day": key, "raw": data}


def get_weather(location: str, day: Optional[_date] = None) -> dict:
    location = clean_place(location)
    if not location:
        msg = "Missing location"
        return {"ok": False, "action": "GET_WEATHER", "error": msg, "content": msg, "response": msg}

    g = _geocode(location)
    lat = g["latitude"]
    lon = g["longitude"]
    if day is not None and day != _date.today():
        return _forecast_for(g, ", ".join(x for x in [g.get("name") or location, g.get("admin1") or "",
                                                      g.get("country_code") or g.get("country") or ""] if x), day)

    forecast_url = (
        "https://api.open-meteo.com/v1/forecast?"
        + urllib.parse.urlencode(
            {
                "latitude": lat,
                "longitude": lon,
                "current": ",".join(
                    [
                        "temperature_2m",
                        "apparent_temperature",
                        "relative_humidity_2m",
                        "wind_speed_10m",
                        "weather_code",
                    ]
                ),
                "timezone": "auto",
            }
        )
    )
    data = _get_json(forecast_url)
    cur = data.get("current") or {}

    place = g.get("name") or location
    admin = g.get("admin1") or ""
    country = g.get("country_code") or g.get("country") or ""
    label = ", ".join(x for x in [place, admin, country] if x)

    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    hum = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")
    code = cur.get("weather_code")
    desc = _weather_code_text(code)

    msg = (
        f"Weather for {label}: {temp}°C, feels like {feels}°C, "
        f"{desc}, humidity {hum}%, wind {wind} km/h."
    )

    return {
        "ok": True,
        "action": "GET_WEATHER",
        "content": msg,
        "response": msg,
        "location": label,
        "raw": data,
    }


def execute(action: str, args: dict | None = None) -> dict:
    args = args or {}
    if action != "GET_WEATHER":
        msg = f"Unsupported action: {action}"
        return {"ok": False, "action": action, "error": msg, "content": msg, "response": msg}
    location = args.get("location") or args.get("city") or args.get("query") or ""
    return get_weather(str(location))
