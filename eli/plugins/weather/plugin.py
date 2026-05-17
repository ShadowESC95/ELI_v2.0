from __future__ import annotations

import json
import urllib.parse
import urllib.request


PLUGIN_ID = "weather"
ACTIONS = ["GET_WEATHER"]


def _get_json(url: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ELI-Weather/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


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


def get_weather(location: str) -> dict:
    location = str(location or "").strip()
    if not location:
        msg = "Missing location"
        return {"ok": False, "action": "GET_WEATHER", "error": msg, "content": msg, "response": msg}

    g = _geocode(location)
    lat = g["latitude"]
    lon = g["longitude"]

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
