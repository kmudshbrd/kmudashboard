# Life Dashboard — Features & Build Plan

A personal, passcode-protected dashboard reachable from any device, refreshed automatically every 2–3 hours by scheduled agents, with an AI-written daily briefing.

---

## 1. Feature list

### Modules (agreed in discovery)

| Module | What it shows | Data source | How it updates |
|---|---|---|---|
| **AI Daily Briefing** | A personal morning brief: "what you need to know today," synthesized from every module below. Refreshed evening edition. | Claude API reads all pulled data | Scheduled agent, morning + evening |
| **Health** | Steps, sleep, workouts, heart rate, trends vs. last week | Apple Health via **Health Auto Export** app (or iOS Shortcut) pushing to the dashboard's API | Pushed from iPhone on a schedule |
| **Markets — Metals** | Gold, silver, copper spot/futures; platinum & crude oil as toggleable defaults | Yahoo Finance futures quotes (GC=F, SI=F, HG=F, PL=F, CL=F) | Every 2–3 h on trading days |
| **Markets — Watchlist** | Your custom tickers with price, day move, sparkline | Yahoo Finance quotes | Every 2–3 h |
| **Markets — India** | NIFTY 50, SENSEX, and any NSE/BSE tickers on your watchlist | Yahoo Finance (^NSEI, ^BSESN, `.NS` tickers) | Every 2–3 h |
| **News — General** | General news you should know: world headlines, business/economy, India, and Triangle local. No work/vendor feeds (Snowflake/AWS/GCP/data-industry explicitly removed 2026-08-09). | Google News RSS (World, Business, India edition, Triangle local query) | Every 2–3 h, AI-deduplicated & summarized |
| **"New in the Triangle"** | Newly announced events in Raleigh–Durham–Chapel Hill — concerts, festivals, meetups — surfaced when they're first announced, with on-sale/RSVP dates. The agent diffs each pull against what it's seen before, so you only see what's new. | Ticketmaster Discovery API (free key), venue calendars (DPAC, Red Hat Amph., Cat's Cradle…), Meetup RSS, Google News local query | Daily diff |
| **Calendar** | Today + next 7 days, merged from both calendars | Google Calendar API (direct) + Apple Calendar via iPhone Shortcut bridge | Google: every pull; Apple: pushed daily from iPhone |
| **Tasks** | Unified to-do list for the day | Apple Reminders via the same Shortcut bridge + built-in quick-add on the dashboard | Pushed daily + instant for built-in items |
| **Weather & commute** | Current conditions, hourly forecast, rain alerts, AQI | Open-Meteo + Open-Meteo Air Quality (free, no key needed) | Every pull |
| **Habits & journal** | Habit checkboxes with streaks; one-line daily journal / mood | Stored in the dashboard itself (KV storage), edited inline | Instant |

### Cross-cutting features
- **Works anywhere, any device** — responsive web app, installable as a PWA (icon on your phone home screen, feels like a native app).
- **Passcode lock** — one PIN/password on each new device, then remembered (signed cookie). Health/calendar data never publicly visible.
- **"Brief me" button** — regenerate the AI briefing on demand, any time.
- **Stale-data indicators** — every card shows "updated 12 min ago" so you always know freshness.
- **Later (v2+)**: push notifications for big market moves or rain (via ntfy.sh, free), weekly AI review of habits/health trends, natural-language "ask my dashboard" chat.

---

## 2. Design language — "Swiss luxury watch"

Codified from the approved direction (see `mockup.html` for the living reference). Masthead name: **MERIDIAN**.

**Page order (fixed):** 1. Time (masthead with live analog watch face + serif digital time) → 2. Weather → 3. The Day (calendar + tasks) → 4. Health & habits → 5. Morning Brief → 6. Markets → 7. News feed → 8. New in the Triangle. No news above the fold.

- **Ground**: warm white paper (`#FDFDFB`), near-black ink (`#161310`), **1px hairline rules** (`#E8E4DB`) between sections.
- **Enamel-dial color washes** (per user request for more color — soft, like enamel watch dials, never loud blocks): each module sits in a panel with a pale wash, a 2px colored top border, and matching colored numerals/labels. Sky `#EDF3F7`/`#33586E` for weather & Data-AI news; sage `#EEF4EE`/`#3E6B4F` for health; champagne `#F9F4EA`/gold for calendar & briefing; slate `#F4F4F1`/`#4A4A45` for tasks; blush `#F9F1ED`/terracotta `#A65A47` for Triangle events & India markets.
- **Masthead clock**: hairline-drawn SVG analog watch face (gold seconds hand, ticking live) beside a large Didot digital time — the "time is the hero" watch-brand gesture.
- **Typography, two voices**:
  - *Display serif* (Didot/Bodoni class — in production: **Playfair Display** or **Cormorant**, self-hosted) for headlines, numerals, and prices. All figures use **tabular lining numerals** so columns align like a date window.
  - *Precision grotesque* (Helvetica Neue class — in production: **Inter** or **Neue Haas**, self-hosted) for labels: 10–11px, uppercase, **letterspaced .18–.24em**, the "GENÈVE · SWISS MADE" voice.
- **Accent**: a single muted gold (`#A5804A`) used only for meaning — the current calendar event, section kickers, streaks, the masthead diamond. Never decorative flourishes.
- **Signals**: market up/down in desaturated green (`#3E6B4F`) / oxblood (`#93392F`) with ▲▼ glyphs — visible but never loud.
- **Structure**: centered masthead (monogram in a hairline circle, letterspaced wordmark, date line), then a 12-column grid at max-width 1180px with generous 48px gutters; collapses to a single elegant column on mobile.
- **Details**: "updated 07:42" provenance lines everywhere, italic serif sign-offs ("*composed at dawn, from 214 sources*"), habit checkmarks as tiny watch-crown circles.

---

## 3. Architecture (free tier, low maintenance)

```
┌─ iPhone ────────────────┐
│ Health Auto Export      │──POST──┐
│ Shortcut (Reminders/Cal)│──POST──┤
└─────────────────────────┘        ▼
                        ┌─────────────────────────┐
  GitHub repo ──deploy─▶│  Cloudflare Pages        │◀── you, from any device
  (code)                │  (static frontend, PWA)  │    (passcode → cookie)
                        │  + Pages Functions (API) │
                        └─────────┬───────────────┘
                                  │ reads/writes
                        ┌─────────▼───────────────┐
                        │  Cloudflare KV (storage) │
                        └─────────▲───────────────┘
                                  │ writes
                        ┌─────────┴───────────────┐
                        │  Cloudflare Worker       │──▶ Yahoo Finance, RSS feeds,
                        │  Cron Triggers           │    Open-Meteo, Google Calendar,
                        │  (every 2–3 h + daily)   │    Ticketmaster, Claude API
                        └─────────────────────────┘
```

**Why this stack:**
- **Cloudflare Pages + Workers + KV** — genuinely $0 at personal scale (100k requests/day free), no servers, global CDN so it's fast from anywhere, cron triggers built in. One vendor, one dashboard, one deploy.
- **GitHub** — code lives here; pushing to `main` auto-deploys to Pages. GitHub Actions available as a backup cron if ever needed.
- **Claude API** — the only paid piece: ~$1–3/month using Haiku/Sonnet for 2 briefings a day.
- **Frontend** — Vite + React (or plain TypeScript), static export. No backend framework to maintain.

**Secrets** (stored as encrypted Worker secrets, never in code): passcode hash, Google Calendar refresh token, Claude API key, Ticketmaster key, iPhone-push bearer token.

**Apple bridges (one-time phone setup):**
1. *Health*: install **Health Auto Export** app → point it at `https://<your-dashboard>/api/ingest/health` with the bearer token → auto-sync daily (or hourly).
2. *Reminders + Apple Calendar*: an iOS **Shortcut** (I'll generate it) that collects today's reminders/events as JSON and POSTs to `/api/ingest/apple`; runs via a personal automation every morning.

---

## 4. Agentic update design

| Schedule (cron) | Job | What it does |
|---|---|---|
| Every 2 h, 6am–9pm | `pull-fast` | Markets (metals, watchlist, India), all news RSS, weather/AQI, Google Calendar → normalize → write JSON to KV |
| Daily 5:30 am | `pull-daily` | Local events scan, subscription-worthy long reads, housekeeping (prune old data) |
| Daily 6:00 am | `brief-morning` | Claude reads everything in KV (health pushed overnight, calendar, markets, news, weather, habits streaks) → writes the morning briefing |
| Daily 6:00 pm | `brief-evening` | Shorter evening update: market close, tomorrow's calendar, evening events |
| On demand | `brief-now` | Same as briefing, triggered by the "Brief me" button |

The briefing prompt is personalized: it knows your watchlist, your work domain (Data & AI), your city, and your calendar — so it says things like *"Copper is up 2% ahead of your 10am supplier call"* rather than generic summaries.

---

## 5. Build plan (phased)

**Phase 1 — Skeleton online (first session)**
- Repo + Vite frontend + Cloudflare Pages deploy + passcode auth
- Weather card, metals + watchlist + India markets cards (live data)
- Raw news feeds card
- ✅ *Milestone: dashboard reachable from your phone with live market/weather data*

**Phase 2 — Calendar, tasks, AI brain**
- Google Calendar OAuth + events card
- Built-in tasks + quick add
- Cron Workers + KV pipeline + Claude briefing (morning/evening + Brief-me button)
- ✅ *Milestone: wake up to an AI briefing*

**Phase 3 — Apple bridges + life modules**
- Health Auto Export ingestion + health card with trends
- iOS Shortcut for Reminders/Apple Calendar
- Habits & journal module, local events module
- ✅ *Milestone: full life coverage*

**Phase 4 — Polish**
- PWA install, dark mode, stale-data indicators, layout customization
- Optional: push notifications (ntfy.sh), weekly AI health/habit review

---

## 6. What I still need from you
1. ~~Your city~~ ✓ The Triangle, NC (weather anchored to Raleigh–Durham; events cover Raleigh, Durham, Chapel Hill)
2. ~~Your ticker watchlist~~ ✓ S&P 500 (^GSPC), Russell 2000 (^RUT), Nasdaq (^IXIC), Vanguard Total US (VTI), Vanguard Total World (VT), iShares India 50 (INDY)
3. Accounts to create when we start building (all free): **Cloudflare**, **GitHub** (if you don't have one), **Anthropic API key** (console.anthropic.com), **Ticketmaster developer key** (for events)
