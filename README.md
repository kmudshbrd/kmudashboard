# Meridian

A private, single-page life dashboard in a Swiss luxury-watch style: time, weather,
calendar, health, an AI morning brief, markets, general news, and newly announced
events around the Triangle (Raleigh–Durham–Chapel Hill, NC).

See [PLAN.md](PLAN.md) for the full feature list, architecture, and phased roadmap.
`mockup.html` is the original approved design reference; `site/` is the real app.

## Layout

```
site/            the dashboard (static — deploys anywhere)
  index.html     structure
  styles.css     the design system (enamel-dial panels, Didot numerals)
  app.js         renders every module from site/data/*.json
  data/          JSON written by the pull agent (live) + samples (pending phases)
scripts/
  pull.py        the data-pull agent: weather (Open-Meteo), markets (Yahoo),
                 news (Google News RSS) → site/data/. Free, keyless sources.
.github/workflows/
  pull.yml       scheduled pulls every 2h once this repo is pushed to GitHub
```

## Run locally

```bash
python3 scripts/pull.py                      # fetch fresh data
python3 -m http.server 8123 --directory site # then open http://localhost:8123
```

## Data status by module

| Module | Status |
|---|---|
| Time, Weather, Markets, News | **Live** (pull.py) |
| Calendar, Tasks | Sample — Phase 2 (Google Calendar OAuth + Apple Reminders bridge) |
| Morning Brief | Preview text — Phase 2 (Claude API) |
| Health, Habits | Sample — Phase 3 (Health Auto Export → ingest endpoint) |
| New in the Triangle | Sample — Phase 3 (Ticketmaster/venue feeds, daily diff) |

Markets watchlist symbols are placeholders — edit `WATCHLIST` in `scripts/pull.py`.

## Deploying (Phase 2)

1. **GitHub**: push this repo (`kmudshbrd/kmudashboard`). Two workflows run on
   cron: `pull.yml` (data refresh every 2h) and `brief.yml` (Claude-written
   brief at 6:07am/6:07pm ET). Add the `ANTHROPIC_API_KEY` repository secret
   (repo → Settings → Secrets and variables → Actions) to enable the brief.
2. **Cloudflare Worker**: create a Worker from this Git repo (Workers & Pages →
   Create → import repository). Build command: *(empty)*. Deploy command:
   `npx wrangler deploy`. `wrangler.jsonc` serves `site/` as static assets and
   `worker/index.js` is the passcode gate. Every push (including the data
   cron's commits) auto-deploys.
3. **Passcode gate**: in the Worker → Settings → Variables and Secrets, add
   secrets `PASSCODE` (what you'll type to unlock) and `COOKIE_SECRET` (any
   long random string). The gate is off until both exist, on afterwards —
   unlocked devices stay signed in for 90 days.

Never commit secrets to this repo.

Note: Yahoo Finance rate-limits aggressively per IP. `pull.py` spaces requests
and retries after a cooldown; on CI-runner IPs this is rarely an issue.
