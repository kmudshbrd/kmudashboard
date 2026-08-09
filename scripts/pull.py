#!/usr/bin/env python3
"""Meridian — data pull agent (Phase 1, local).

Fetches live weather, markets, and news; writes JSON into site/data/.
Later this logic moves into a Cloudflare Worker on a cron trigger.
All sources are free and keyless.
"""
import datetime as dt
import html
import http.cookiejar
import json
import pathlib
import re
import subprocess
import time
import urllib.request
import zoneinfo

TZ = zoneinfo.ZoneInfo("America/New_York")


def now_et():
    """Naive Eastern-time now — data timestamps must not depend on runner TZ."""
    return dt.datetime.now(TZ).replace(tzinfo=None)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "site" / "data"
DATA.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
RALEIGH = (35.7796, -78.6382)

def get(url, timeout=25, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# Yahoo Finance quirks, learned the hard way:
#  - python-urllib is rejected outright (TLS fingerprint) -> use curl
#  - a User-Agent claiming a real browser (e.g. Chrome/126) gets 429s, because
#    curl's TLS fingerprint doesn't match the claimed browser. A generic
#    "Mozilla/5.0 (...)" UA with no browser token is accepted.
#  - a session cookie helps; keep a persistent jar next to this script.
YAHOO_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
JAR = pathlib.Path(__file__).resolve().parent / ".yahoo_cookies"


def yahoo_get(url):
    if not JAR.exists():
        subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "--max-time", "15",
             "-A", YAHOO_UA, "-c", str(JAR), "https://fc.yahoo.com"],
            check=False,
        )
    p = subprocess.run(
        ["curl", "-s", "--max-time", "20", "-A", YAHOO_UA,
         "-b", str(JAR), "-c", str(JAR),
         "-w", "\n%{http_code}", url],
        capture_output=True, text=True, check=False,
    )
    body, _, code = p.stdout.rpartition("\n")
    if code != "200":
        raise RuntimeError(f"HTTP {code or 'error'}")
    return body


def jget(url):
    return json.loads(get(url))


def write(name, obj):
    (DATA / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    print(f"  wrote {name}.json")


# ---------------------------------------------------------------- weather
WMO = {
    0: ("Clear sky", "☀︎"), 1: ("Mostly clear", "☀︎"), 2: ("Partly cloudy", "⛅︎"),
    3: ("Overcast", "☁︎"), 45: ("Foggy", "🌫"), 48: ("Freezing fog", "🌫"),
    51: ("Light drizzle", "🌦"), 53: ("Drizzle", "🌦"), 55: ("Heavy drizzle", "🌧"),
    61: ("Light rain", "🌦"), 63: ("Rain", "🌧"), 65: ("Heavy rain", "🌧"),
    66: ("Freezing rain", "🌧"), 67: ("Freezing rain", "🌧"),
    71: ("Light snow", "🌨"), 73: ("Snow", "🌨"), 75: ("Heavy snow", "🌨"), 77: ("Snow grains", "🌨"),
    80: ("Showers", "🌦"), 81: ("Showers", "🌧"), 82: ("Heavy showers", "🌧"),
    85: ("Snow showers", "🌨"), 86: ("Snow showers", "🌨"),
    95: ("Thunderstorms", "⛈"), 96: ("Thunderstorms, hail", "⛈"), 99: ("Thunderstorms, hail", "⛈"),
}


def aqi_label(v):
    if v is None: return ""
    for cut, name in [(50, "Good"), (100, "Moderate"), (150, "Unhealthy for some"), (200, "Unhealthy")]:
        if v <= cut: return name
    return "Hazardous"


def pull_weather():
    lat, lon = RALEIGH
    w = jget(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,apparent_temperature,weather_code"
        "&hourly=temperature_2m,precipitation_probability,weather_code"
        "&daily=sunrise,sunset&timezone=America%2FNew_York&forecast_days=2"
        "&temperature_unit=fahrenheit"
    )
    try:
        aq = jget(
            "https://air-quality-api.open-meteo.com/v1/air-quality"
            f"?latitude={lat}&longitude={lon}&current=us_aqi&timezone=America%2FNew_York"
        )
        aqi = round(aq["current"]["us_aqi"])
    except Exception:
        aqi = None

    cur = w["current"]
    desc_word, _ = WMO.get(cur["weather_code"], ("—", ""))
    now = now_et()  # Open-Meteo returns America/New_York-local times

    times = w["hourly"]["time"]
    temps = w["hourly"]["temperature_2m"]
    probs = w["hourly"]["precipitation_probability"]
    codes = w["hourly"]["weather_code"]
    hours = []
    for i, t in enumerate(times):
        ts = dt.datetime.fromisoformat(t)
        if ts >= now and ts.hour % 3 == 0:
            _, icon = WMO.get(codes[i], ("", "·"))
            hours.append({"h": f"{ts.hour:02d}h", "icon": icon, "t": temps[i], "p": probs[i] or 0})
        if len(hours) == 5:
            break

    rain_note = ""
    for i, t in enumerate(times):
        ts = dt.datetime.fromisoformat(t)
        if now <= ts <= now + dt.timedelta(hours=12) and (probs[i] or 0) >= 50:
            rain_note = f" Rain likely around {ts.hour:02d}:00."
            break

    feels = round(cur["apparent_temperature"])
    write("weather", {
        "temp": cur["temperature_2m"],
        "desc": f"{desc_word}, feels like {feels}°.{rain_note}",
        "aqi": aqi, "aqiLabel": aqi_label(aqi),
        "sunrise": w["daily"]["sunrise"][0][-5:],
        "sunset": w["daily"]["sunset"][0][-5:],
        "hours": hours,
    })


# ---------------------------------------------------------------- markets
METALS = [
    ("Gold", "COMEX · oz", "GC=F"), ("Silver", "COMEX · oz", "SI=F"),
    ("Copper", "COMEX · lb", "HG=F"), ("Platinum", "NYMEX · oz", "PL=F"),
]
WATCHLIST = [
    ("S&P 500", "Index", "^GSPC"),
    ("Russell 2000", "Index", "^RUT"),
    ("Nasdaq", "Composite", "^IXIC"),
    ("Total US Market", "VTI · Vanguard", "VTI"),
    ("Total World", "VT · Vanguard", "VT"),
    ("India Top 50", "INDY · iShares", "INDY"),
]
INDIA = [
    ("NIFTY 50", "NSE", "^NSEI"), ("SENSEX", "BSE", "^BSESN"),
    ("USD / INR", "Spot", "INR=X"),
]


def quote(symbol, attempt=0):
    try:
        d = json.loads(yahoo_get(
            f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?range=5d&interval=1d"
        ))
    except Exception:
        if attempt < 1:
            time.sleep(30)  # let the per-IP rate-limit window decay
            return quote(symbol, attempt + 1)
        raise
    result = d["chart"]["result"][0]
    meta = result["meta"]
    price = meta.get("regularMarketPrice")
    # meta's previousClose fields reflect the start of the requested range, not
    # the prior session — derive the true previous close from the daily series.
    closes = [c for c in result["indicators"]["quote"][0].get("close", []) if c is not None]
    if price is None and closes:
        price = closes[-1]
    # With interval=1d the final bar is the latest session (live or closed),
    # so the prior session's close is always the second-to-last bar.
    prev = closes[-2] if len(closes) >= 2 else (
        meta.get("regularMarketPreviousClose") or meta.get("previousClose"))
    pct = (price / prev - 1) * 100 if price and prev else None
    time.sleep(2)  # be polite between symbols
    return price, pct, closes[-6:]  # ≤5 sessions + today, for sparklines


def pull_markets():
    groups = []
    for label, color, rows in [
        ("Metals", "var(--gold)", METALS),
        ("Watchlist", "var(--dial-sky)", WATCHLIST),
        ("India", "var(--dial-blush)", INDIA),
    ]:
        out = []
        for name, sub, sym in rows:
            try:
                price, pct, series = quote(sym)
            except Exception as e:
                print(f"  ! {sym}: {e}")
                price, pct, series = None, None, []
            out.append({"name": name, "sub": sub, "price": price, "changePct": pct, "series": series})
        groups.append({"label": label, "color": color, "rows": out})
    stamp = now_et().strftime("%H:%M")
    write("markets", {"meta": f"Quotes as of {stamp} ET", "groups": groups})


# ---------------------------------------------------------------- news
def rss(url, kicker, n=4):
    xml = get(url)
    stories = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        m_t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        m_s = re.search(r"<source[^>]*>(.*?)</source>", it)
        m_d = re.search(r"<pubDate>(.*?)</pubDate>", it)
        m_l = re.search(r"<link/?>?\s*(\S+?)\s*</link>", it) or re.search(r"<link>(.*?)</link>", it, re.S)
        if not m_t:
            continue
        title = html.unescape(m_t.group(1)).strip()
        source = html.unescape(m_s.group(1)).strip() if m_s else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)]
        ago = ""
        if m_d:
            try:
                pub = dt.datetime.strptime(m_d.group(1).strip(), "%a, %d %b %Y %H:%M:%S %Z")
                hours = max(0, int((dt.datetime.utcnow() - pub).total_seconds() // 3600))
                ago = f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"
            except Exception:
                pass
        stories.append({"kicker": kicker, "title": title,
                        "source": source, "time": ago,
                        "link": html.unescape(m_l.group(1)) if m_l else "#"})
        if len(stories) == n:
            break
    return stories


def pull_news():
    gn = "https://news.google.com/rss"
    feeds_left = [
        (f"{gn}/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en", "World", 3),
        (f"{gn}/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en", "Business", 3),
    ]
    feeds_right = [
        (f"{gn}?hl=en-IN&gl=IN&ceid=IN:en", "India", 3),
        (f"{gn}/search?q=%22Raleigh%22%20OR%20%22Durham%22%20OR%20%22Chapel%20Hill%22%20NC&hl=en-US&gl=US&ceid=US:en", "Triangle", 3),
    ]

    def col(feeds):
        out = []
        for url, kicker, n in feeds:
            try:
                out += rss(url, kicker, n)
            except Exception as e:
                print(f"  ! rss {kicker}: {e}")
        return out

    write("news", {
        "meta": "General briefing · headlines only",
        "columns": [
            {"label": "World & Business", "color": "var(--dial-slate)", "stories": col(feeds_left)},
            {"label": "India & The Triangle", "color": "var(--dial-blush)", "stories": col(feeds_right)},
        ],
    })


# ---------------------------------------------------------------- samples
# Stand-ins until Phase 2 (calendar/tasks/brief) and Phase 3 (health/events).
def write_samples():
    if not (DATA / "events.json").exists():
        write("events", {"sample": True, "items": [
            {"title": "Sylvan Esso — homecoming show", "where": "DPAC, Durham · Nov 14", "line": "Announced yesterday · On sale Fri 10:00"},
            {"title": "Hopscotch Music Festival — late-night sets added", "where": "City Plaza, Raleigh · Sep 10–12", "line": "Lineup expanded Wed · Day passes available"},
            {"title": "Triangle Data Engineering meetup — Iceberg in production", "where": "Frontier RTP, Durham · Thu 18:30", "line": "Posted 2 days ago · RSVP open"},
        ]})
    if not (DATA / "brief.json").exists():
        write("brief", {"sample": True,
            "headline": "Your dashboard is alive — markets, weather, and news are real.",
            "paras": [
                "This brief is a preview: from Phase 2, Claude will write it twice a day from everything above and below — your sleep, your calendar, the metals board, and the morning's headlines.",
                "Weather, markets, and the news feed on this page are already live data, pulled by the agent script moments ago.",
            ],
            "signoff": "— composed by the build process, awaiting its API key"})


if __name__ == "__main__":
    print("Pulling live data…")
    for fn in (pull_weather, pull_markets, pull_news):
        try:
            fn()
        except Exception as e:
            print(f"  !! {fn.__name__} failed: {e}")
    write_samples()
    write("meta", {"generated": dt.datetime.now(TZ).isoformat()})
    print("Done.")
