#!/usr/bin/env python3
"""Meridian — data pull agent.

Fetches live weather, markets (2-year performance), news (4 deduplicated
sections), and Triangle events; writes JSON into site/data/.

Free/keyless sources throughout. Events cover the Triangle (Wake + Orange
county towns) via the Visit Raleigh and Visit Chapel Hill calendar APIs;
set TICKETMASTER_KEY (free, developer.ticketmaster.com) to add Durham venues
and big ticketed shows (DPAC, arenas).
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
EVENT_BUCKETS = ["Today", "This Week", "This Month", "This Year"]


def bucket_for(days_out):
    if days_out == 0: return "Today"
    if days_out <= 7: return "This Week"
    if days_out <= 31: return "This Month"
    return "This Year"


def parse_sv_dates(desc):
    """Extract (start, end) from a Simpleview RSS description blob."""
    found = re.findall(r"(\d{2}/\d{2}/\d{4})", desc)
    if not found:
        return None, None
    dates = []
    for f in found[:2]:
        m, d, y = f.split("/")
        dates.append(dt.date(int(y), int(m), int(d)))
    return dates[0], (dates[1] if len(dates) > 1 else dates[0])


def sv_api_events(base, fallback_city):
    """Events from a Simpleview tourism site's REST API (public token).

    Queries by nextDate (the next occurrence), which handles recurring series
    cleanly and lets date windows reach the rest of the year. Each doc carries
    its real city (Cary, Morrisville, ...) and venue in `location`.
    """
    token = get(f"{base}/plugins/core/get_simple_token/").strip()
    today = now_et().date()
    year_end = dt.date(today.year, 12, 31)

    def window(lo, hi, limit):
        query = json.dumps({
            "filter": {
                "active": True,
                "nextDate": {"$gte": {"$date": f"{lo.isoformat()}T00:00:00.000Z"},
                             "$lte": {"$date": f"{hi.isoformat()}T23:59:59.000Z"}},
            },
            "options": {
                "limit": limit,
                "fields": {"title": 1, "nextDate": 1, "endDate": 1,
                           "location": 1, "city": 1},
                "sort": {"nextDate": 1},
            },
        })
        d = json.loads(get(
            f"{base}/includes/rest_v2/plugins_events_events/find/"
            f"?json={urllib.request.quote(query)}&token={token}"
        ))
        docs = d.get("docs") or []
        return docs.get("docs", []) if isinstance(docs, dict) else docs

    def et_date(s):
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ).date()

    out = []
    near = window(today, min(today + dt.timedelta(days=31), year_end), 300)
    far = window(today + dt.timedelta(days=32), year_end, 80) if today + dt.timedelta(days=32) <= year_end else []
    for doc in near + far:
        title = html.unescape(doc.get("title", "")).strip()
        if not title:
            continue
        try:
            s = et_date(doc["nextDate"])
            e = et_date(doc["endDate"])
        except Exception:
            continue
        if e < s:
            e = s
        if (e - s).days > 90:
            e = s  # long-running recurring series -> show as its next occurrence
        out.append({"title": title,
                    "city": (doc.get("city") or fallback_city).strip(),
                    "cat": (doc.get("location") or "").strip(),
                    "start": s, "end": e})
    return out


def sv_rss_events(url, city):
    """Fallback: near-term events from the Simpleview RSS feed."""
    xml = get(url)
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        m_t = re.search(r"<title>(.*?)</title>", it, re.S)
        if not m_t:
            continue
        title = html.unescape(html.unescape(m_t.group(1))).strip()
        cats = [html.unescape(c).strip() for c in re.findall(r"<category><!\[CDATA\[(.*?)\]\]></category>", it)]
        s, e = parse_sv_dates(it)
        if not s:
            continue
        out.append({"title": title, "city": city, "cat": cats[0] if cats else "", "start": s, "end": e})
    return out


def fmt_line(s, e, today):
    if s == e == today:
        return "Today"
    if s <= today < e:
        return f"Through {e.strftime('%b %-d')}"
    if s == e:
        return s.strftime("%a · %b %-d")
    return f"{s.strftime('%b %-d')} – {e.strftime('%b %-d')}"


def bucket_events(raw):
    today = now_et().date()
    groups = {b: [] for b in EVENT_BUCKETS}
    seen = set()
    for ev in sorted(raw, key=lambda x: (max(x["start"], today), (x["end"] - x["start"]).days)):
        norm = re.sub(r"[^a-z0-9]", "", ev["title"].lower())[:48]
        if norm in seen or ev["end"] < today or ev["start"] > today + dt.timedelta(days=365):
            continue
        days_out = (max(ev["start"], today) - today).days
        b = bucket_for(days_out)
        if len(groups[b]) >= 8:
            continue
        seen.add(norm)
        where = " · ".join(x for x in [ev.get("cat", ""), ev["city"]] if x)
        groups[b].append({"title": ev["title"], "where": where,
                          "line": fmt_line(ev["start"], ev["end"], today)})
    return groups


def pull_events():
    raw = []
    key = os.environ.get("TICKETMASTER_KEY")
    if key:
        lat, lon = RALEIGH
        d = jget(
            "https://app.ticketmaster.com/discovery/v2/events.json"
            f"?apikey={key}&latlong={lat},{lon}&radius=40&unit=miles"
            "&sort=date,asc&size=200"
        )
        for ev in d.get("_embedded", {}).get("events", []):
            name = ev.get("name", "").strip()
            try:
                date = dt.date.fromisoformat(ev["dates"]["start"]["localDate"])
            except Exception:
                continue
            venues = ev.get("_embedded", {}).get("venues", [{}])
            venue = venues[0].get("name", "")
            city = venues[0].get("city", {}).get("name", "")
            raw.append({"title": name, "city": " · ".join(x for x in [venue, city] if x),
                        "cat": "", "start": date, "end": date})
        # sv_events uses city as the trailing where-part; TM entries carry venue in "city"

    for base, city in [
        ("https://www.visitraleigh.com", "Raleigh"),
        ("https://www.visitchapelhill.org", "Chapel Hill"),
    ]:
        try:
            raw += sv_api_events(base, city)
        except Exception as e:
            print(f"  ! events API {city}: {e} — trying RSS")
            try:
                raw += sv_rss_events(f"{base}/event/rss/", city)
            except Exception as e2:
                print(f"  ! events RSS {city}: {e2}")

    groups = bucket_events(raw)
    if not any(groups.values()):
        print("  events: nothing fetched — keeping existing events.json")
        return
    write("events", {
        "sample": False,
        "groups": [{"label": b, "items": groups[b]} for b in EVENT_BUCKETS],
    })


if __name__ == "__main__":
    print("Pulling live data…")
    for fn in (pull_weather, pull_markets, pull_news, pull_events):
        try:
            fn()
        except Exception as e:
            print(f"  !! {fn.__name__} failed: {e}")
    write("meta", {"generated": dt.datetime.now(TZ).isoformat()})
    print("Done.")
