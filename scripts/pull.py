#!/usr/bin/env python3
"""Meridian — data pull agent.

Fetches live weather, markets (2-year performance), news (4 deduplicated
sections), and Triangle events; writes JSON into site/data/.

Free/keyless sources throughout, except events: set TICKETMASTER_KEY in the
environment (free key from developer.ticketmaster.com) for real Triangle
events; without it, tagged sample data is kept.
"""
import datetime as dt
import html
import json
import os
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


def jget(url):
    return json.loads(get(url))


def write(name, obj):
    (DATA / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False))
    print(f"  wrote {name}.json")


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
    """Current price + 2-year performance (% change and weekly close series)."""
    try:
        d = json.loads(yahoo_get(
            f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(symbol)}?range=2y&interval=1wk"
        ))
    except Exception:
        if attempt < 1:
            time.sleep(30)  # let the per-IP rate-limit window decay
            return quote(symbol, attempt + 1)
        raise
    result = d["chart"]["result"][0]
    meta = result["meta"]
    closes = [c for c in result["indicators"]["quote"][0].get("close", []) if c is not None]
    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    pct = (price / closes[0] - 1) * 100 if price and closes else None
    # thin the weekly series to ~36 points for the sparkline
    step = max(1, len(closes) // 36)
    series = closes[::step]
    if price is not None:
        series = series[:-1] + [price] if series else [price]
    time.sleep(2)  # be polite between symbols
    return price, pct, series


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
    write("markets", {"meta": f"2-year performance · quotes as of {stamp} ET", "groups": groups})


# ---------------------------------------------------------------- news
def rss(url, n=12):
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
        stories.append({"title": title, "source": source, "time": ago,
                        "link": html.unescape(m_l.group(1)) if m_l else "#"})
        if len(stories) == n:
            break
    return stories


def pull_news():
    gn = "https://news.google.com/rss"
    sections = [
        ("USA", "var(--dial-slate)",
         f"{gn}/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en"),
        ("India", "var(--dial-blush)",
         f"{gn}/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en"),
        ("World", "var(--dial-sky)",
         f"{gn}/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en"),
        ("The Triangle", "var(--dial-sage)",
         f"{gn}/search?q=%22Raleigh%22%20OR%20%22Durham%22%20OR%20%22Chapel%20Hill%22%20NC&hl=en-US&gl=US&ceid=US:en"),
    ]

    seen = set()  # dedup across all four sections
    columns = []
    for label, color, url in sections:
        picked = []
        try:
            for s in rss(url, n=15):
                key = re.sub(r"[^a-z0-9]", "", s["title"].lower())[:64]
                if key in seen:
                    continue
                seen.add(key)
                picked.append(s)
                if len(picked) == 6:
                    break
        except Exception as e:
            print(f"  ! rss {label}: {e}")
        columns.append({"label": label, "color": color, "stories": picked})

    write("news", {"meta": "Four desks · deduplicated", "columns": columns})


# ---------------------------------------------------------------- events
EVENT_BUCKETS = ["This Week", "Next Week", "This Month", "This Year"]


def bucket_for(days_out):
    if days_out <= 7: return "This Week"
    if days_out <= 14: return "Next Week"
    if days_out <= 31: return "This Month"
    return "This Year"


def pull_events():
    key = os.environ.get("TICKETMASTER_KEY")
    if not key:
        print("  events: TICKETMASTER_KEY not set — keeping sample events")
        return

    lat, lon = RALEIGH
    d = jget(
        "https://app.ticketmaster.com/discovery/v2/events.json"
        f"?apikey={key}&latlong={lat},{lon}&radius=40&unit=miles"
        "&sort=date,asc&size=200"
    )
    today = now_et().date()
    groups = {b: [] for b in EVENT_BUCKETS}
    seen = set()
    for ev in d.get("_embedded", {}).get("events", []):
        name = ev.get("name", "").strip()
        norm = re.sub(r"[^a-z0-9]", "", name.lower())[:48]
        if not name or norm in seen:
            continue
        try:
            date = dt.date.fromisoformat(ev["dates"]["start"]["localDate"])
        except Exception:
            continue
        days_out = (date - today).days
        if days_out < 0 or date.year > today.year:
            continue
        b = bucket_for(days_out)
        if len(groups[b]) >= 8:
            continue
        seen.add(norm)
        venues = ev.get("_embedded", {}).get("venues", [{}])
        venue = venues[0].get("name", "")
        city = venues[0].get("city", {}).get("name", "")
        groups[b].append({
            "title": name,
            "where": " · ".join(x for x in [venue, city] if x),
            "line": date.strftime("%a · %b %-d"),
        })
    write("events", {
        "sample": False,
        "groups": [{"label": b, "items": groups[b]} for b in EVENT_BUCKETS],
    })


def write_sample_events():
    if (DATA / "events.json").exists():
        return
    write("events", {"sample": True, "groups": [
        {"label": "This Week", "items": [
            {"title": "Jazz at Sharp 9 Gallery", "where": "Sharp 9 Gallery · Durham", "line": "Fri · 8:00 PM"},
            {"title": "Durham Bulls vs. Norfolk Tides", "where": "Durham Bulls Athletic Park", "line": "Sat · 6:35 PM"},
            {"title": "Midtown Farmers Market", "where": "North Hills · Raleigh", "line": "Sat · 8:00 AM"},
            {"title": "Carolina Theatre classic film series", "where": "Carolina Theatre · Durham", "line": "Sun · 2:00 PM"},
            {"title": "Live bluegrass on the lawn", "where": "Weaver Street Market · Carrboro", "line": "Sun · 11:00 AM"},
        ]},
        {"label": "Next Week", "items": [
            {"title": "NC Symphony: Beethoven's Seventh", "where": "Meymandi Concert Hall · Raleigh", "line": "Fri · 7:30 PM"},
            {"title": "Touring Broadway series opens", "where": "DPAC · Durham", "line": "Tue – Sun"},
            {"title": "Third Friday Gallery Walk", "where": "Downtown Durham", "line": "Fri · 6:00 PM"},
            {"title": "Museum after-hours: night at the NCMA", "where": "NC Museum of Art · Raleigh", "line": "Sat · 7:00 PM"},
            {"title": "Indie rock at Cat's Cradle", "where": "Cat's Cradle · Carrboro", "line": "Thu · 8:00 PM"},
        ]},
        {"label": "This Month", "items": [
            {"title": "Hopscotch Music Festival", "where": "City Plaza · Raleigh", "line": "Sep 10 – 12"},
            {"title": "Bull City Food & Beer Experience", "where": "DPAC · Durham", "line": "Sep 20"},
            {"title": "SparkCON creativity festival", "where": "Fayetteville St · Raleigh", "line": "Sep 26 – 27"},
            {"title": "Carolina Hurricanes preseason opener", "where": "Lenovo Center · Raleigh", "line": "Sep 29"},
            {"title": "American Dance Festival gala", "where": "Page Auditorium · Durham", "line": "Sep 24"},
        ]},
        {"label": "This Year", "items": [
            {"title": "NC State Fair", "where": "State Fairgrounds · Raleigh", "line": "Oct 15 – 25"},
            {"title": "Art of Cool jazz festival", "where": "Downtown Durham", "line": "Oct 24 – 26"},
            {"title": "World of Bluegrass week", "where": "Downtown Raleigh", "line": "Nov 4 – 8"},
            {"title": "Chinese Lantern Festival", "where": "Koka Booth Amphitheatre · Cary", "line": "Nov 20 – Jan 11"},
            {"title": "First Night Raleigh", "where": "Fayetteville St · Raleigh", "line": "Dec 31"},
        ]},
    ]})


if __name__ == "__main__":
    print("Pulling live data…")
    for fn in (pull_weather, pull_markets, pull_news, pull_events):
        try:
            fn()
        except Exception as e:
            print(f"  !! {fn.__name__} failed: {e}")
    write_sample_events()
    write("meta", {"generated": dt.datetime.now(TZ).isoformat()})
    print("Done.")
