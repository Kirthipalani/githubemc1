from django.shortcuts import render
from django.conf import settings
import requests
from datetime import datetime, timedelta, timezone
from collections import defaultdict


def _fetch_current_weather(city_name: str):
    base_url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city_name,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric",
    }
    response = requests.get(base_url, params=params, timeout=10)
    if response.status_code != 200:
        return None, f"City '{city_name}' not found or API error."
    data = response.json()
    current = {
        "city": data.get("name"),
        "country": data.get("sys", {}).get("country"),
        "temperature": data.get("main", {}).get("temp"),
        "humidity": data.get("main", {}).get("humidity"),
        "wind_speed": data.get("wind", {}).get("speed"),
        "condition": data.get("weather", [{}])[0].get("description", ""),
        "icon": data.get("weather", [{}])[0].get("icon", "01d"),
        "coord": data.get("coord", {}),
    }
    return current, None


def _fetch_5day_forecast(city_name: str):
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": city_name,
        "appid": settings.OPENWEATHER_API_KEY,
        "units": "metric",
    }
    response = requests.get(url, params=params, timeout=10)
    if response.status_code != 200:
        return None, "Unable to fetch forecast."
    data = response.json()

    # Group by date (YYYY-MM-DD), compute min/max temp and choose midday icon
    buckets = defaultdict(list)
    for entry in data.get("list", []):
        dt_txt = entry.get("dt_txt")
        if not dt_txt:
            continue
        date_key = dt_txt.split(" ")[0]
        buckets[date_key].append(entry)

    forecast_days = []
    for date_key in sorted(buckets.keys()):
        day_entries = buckets[date_key]
        temps = [e.get("main", {}).get("temp") for e in day_entries if e.get("main")]
        temp_min = min([e.get("main", {}).get("temp_min") for e in day_entries if e.get("main")], default=None)
        temp_max = max([e.get("main", {}).get("temp_max") for e in day_entries if e.get("main")], default=None)

        # Choose an icon closest to 12:00:00
        target_hour = "12:00:00"
        mid = None
        for e in day_entries:
            if e.get("dt_txt", "").endswith(target_hour):
                mid = e
                break
        if mid is None and day_entries:
            mid = day_entries[len(day_entries) // 2]

        weather = (mid or day_entries[0]).get("weather", [{}])[0]
        icon = weather.get("icon", "01d")
        description = weather.get("description", "")

        forecast_days.append({
            "date": date_key,
            "temp_min": temp_min,
            "temp_max": temp_max,
            "icon": icon,
            "description": description,
            "humidity": (mid or day_entries[0]).get("main", {}).get("humidity"),
            "wind_speed": (mid or day_entries[0]).get("wind", {}).get("speed"),
        })

    # Return only the next 5 days
    return forecast_days[:5], None


def _fetch_past_5_days(lat: float, lon: float):
    results = []
    errors = []
    for days_ago in range(1, 6):
        dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
        unix_ts = int(dt.timestamp())
        url = "https://api.openweathermap.org/data/3.0/onecall/timemachine"
        params = {
            "lat": lat,
            "lon": lon,
            "dt": unix_ts,
            "appid": settings.OPENWEATHER_API_KEY,
            "units": "metric",
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            errors.append(f"Historical data unavailable for {dt.date()}.")
            continue
        data = response.json()
        # Choose the hourly record closest to midday, or fallback to first
        hourly = data.get("hourly", [])
        chosen = None
        target_hour = 12
        min_diff = 24
        for h in hourly:
            hdt = datetime.fromtimestamp(h.get("dt", unix_ts), tz=timezone.utc)
            diff = abs(hdt.hour - target_hour)
            if diff < min_diff:
                min_diff = diff
                chosen = h
        if not chosen and hourly:
            chosen = hourly[0]
        if not chosen:
            errors.append(f"No hourly data for {dt.date()}.")
            continue
        weather = (chosen.get("weather") or [{}])[0]
        results.append({
            "date": dt.date().isoformat(),
            "temperature": chosen.get("temp"),
            "humidity": chosen.get("humidity"),
            "wind_speed": chosen.get("wind_speed"),
            "icon": weather.get("icon", "01d"),
            "description": weather.get("description", ""),
        })
    return results, (" ".join(errors) if errors else None)


def index(request):
    city = request.GET.get("city", "").strip()
    context = {"city": city}
    if not city:
        return render(request, "weather_app/index.html", context)

    current, err = _fetch_current_weather(city)
    if err:
        context["error"] = err
        return render(request, "weather_app/index.html", context)

    forecast, forecast_err = _fetch_5day_forecast(city)

    historical = []
    historical_err = None
    coord = current.get("coord") or {}
    lat = coord.get("lat")
    lon = coord.get("lon")
    if lat is not None and lon is not None:
        historical, historical_err = _fetch_past_5_days(lat, lon)
    else:
        historical_err = "Coordinates unavailable for historical data."

    context.update({
        "current": current,
        "forecast_daily": forecast or [],
        "historical_daily": historical or [],
        "forecast_error": forecast_err,
        "historical_error": historical_err,
    })

    return render(request, "weather_app/index.html", context)

# Create your views here.
