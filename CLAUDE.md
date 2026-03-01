# CLAUDE.md — liftwatch

## Project Overview

**liftwatch** is a Discord bot that monitors Niseko United ski resort lift and weather conditions. It does two things:

1. **Push alerts** — periodically checks for lift/weather updates and posts to Discord when conditions change.
2. **Slash commands** — responds to `/powder`, `/summary`, `/status` with formatted snapshots.

Hosted as a Python serverless function on **Vercel**. No frontend, no database — just a FastAPI app, Redis for deduplication, and Discord webhooks.

---

## Repository Structure

```
liftwatch/
├── api/
│   └── index.py              # FastAPI app — all HTTP endpoints
├── liftwatch/
│   ├── discord.py            # Discord signature verification + webhook posting
│   ├── formatter.py          # Message formatting for Discord output
│   ├── ski_area.py           # SkiArea IntEnum (the four Niseko United areas)
│   └── fetcher/
│       ├── fetcher.py        # Snapshot orchestrator — fetches all data concurrently
│       ├── facility.py       # LiftFacility dataclass + lift API fetch logic
│       └── weather.py        # WeatherPoint/ResortWeather dataclasses + weather API fetch
├── scripts/
│   └── register_commands.py  # One-off script to register Discord slash commands
├── requirements.txt
└── vercel.json               # Routes /api/* to api/index.py
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| HTTP framework | FastAPI 0.110 |
| ASGI server | Uvicorn 0.27 |
| Async HTTP | httpx 0.27 |
| Auth | PyNaCl 1.5 (Ed25519 sig verification) |
| Caching | Redis 5.0 |
| Scraping (unused in main path) | requests 2.31, BeautifulSoup4 4.12 |
| Hosting | Vercel (serverless) |
| Data source | Yukiyama API (`https://web-api.yukiyama.biz/web-api/`) |

---

## API Endpoints

### `GET /api/health`
Simple liveness check. Returns `{"ok": True, "service": "liftwatch"}`.

### `GET /api/cron` (and `HEAD /api/cron`)
Scheduled job endpoint. Requires `Authorization: Bearer <CRON_SECRET>`.

1. Fetches a full `Snapshot` (all lifts + weather for all 4 areas).
2. For each area, compares `update_date` timestamps against Redis keys.
3. If newer: posts formatted message to Discord webhook, updates Redis key.
4. Returns `{"ok": True, "updated": { "<area_id>": {"lifts": bool, "weather": bool} }}`.

The `HEAD` variant exists for Uptime Robot compatibility.

### `POST /api/interactions`
Discord Interactions endpoint.

1. Verifies Ed25519 signature from `X-Signature-Ed25519` / `X-Signature-Timestamp` headers.
2. Handles `type=1` (ping) with `{"type": 1}`.
3. Handles `type=2` (slash commands): `/powder`, `/summary`, `/status`.

---

## Data Flow

```
Yukiyama API ──httpx──> fetcher/facility.py  ──> LiftFacility list
                        fetcher/weather.py   ──> ResortWeather
                              │
                        fetcher/fetcher.py (Snapshot)
                              │
                    ┌─────────┴──────────┐
              formatter.py          Redis (dedup)
                    │                     │
             Discord response       Webhook POST
```

---

## Key Data Models

### `SkiArea` (`liftwatch/ski_area.py`)
`IntEnum` with four values matching Yukiyama API `skiareaId`:
- `ANNUPURI = 393`
- `NISEKO_VILLAGE = 394`
- `GRAND_HIRAFU = 390`
- `HANAZONO = 379`

Each has a `.label` property for human-readable output.

### `LiftFacility` (`liftwatch/fetcher/facility.py`)
Frozen dataclass. Key fields: `ski_area`, `facility_id`, `name`, `status`, `hours` (start/end), `grooming`, `update_date` (ISO string, JST).

Status values include: `OPERATING`, `OPERATING_SLOWED`, `STANDBY`, `SUSPENDED`, `CLOSED`.

### `ResortWeather` / `WeatherPoint` (`liftwatch/fetcher/weather.py`)
`ResortWeather` holds `peak` and `base` `WeatherPoint` objects plus `last_updated`.

`WeatherPoint` fields: `temperature_c`, `snow_cm`, `snow_diff_cm`, `wind`, `weather`, `snow_state`, `course_state`, `comment`.

### `Snapshot` (`liftwatch/fetcher/fetcher.py`)
Dataclass combining:
- `lifts_by_area: dict[SkiArea, list[LiftFacility]]`
- `weather_by_area: dict[SkiArea, ResortWeather]`

---

## Environment Variables

| Variable | Required | Used in |
|---|---|---|
| `REDIS_URL` | Yes (cron) | `api/index.py` — change detection |
| `CRON_SECRET` | Yes (cron) | `api/index.py` — Bearer token auth |
| `DISCORD_PUBLIC_KEY` | Yes | `liftwatch/discord.py` — sig verification |
| `DISCORD_FACILITIES_WEBHOOK_URL` | Yes | `liftwatch/discord.py` — lift alerts |
| `DISCORD_WEATHER_WEBHOOK_URL` | Yes | `liftwatch/discord.py` — weather alerts |
| `DISCORD_APP_ID` | Scripts only | `scripts/register_commands.py` |
| `DISCORD_BOT_TOKEN` | Scripts only | `scripts/register_commands.py` |
| `DISCORD_GUILD_ID` | Scripts only | `scripts/register_commands.py` |

---

## Redis Key Schema

```
lw:last_posted:lifts:<area_id>    # ISO timestamp of last posted lift update
lw:last_posted:weather:<area_id>  # ISO timestamp of last posted weather update
```

`<area_id>` is the integer value of `SkiArea` (e.g. `390` for Grand Hirafu).

Timestamps are compared lexicographically (ISO 8601 strings sort correctly).

---

## Discord Commands

| Command | Handler | Description |
|---|---|---|
| `/powder` | `powder_summary(snap)` | Lists resorts with powder signals (positive `snow_diff_cm` or powder snow state keywords) |
| `/summary` | `summary_message(snap)` | Full lift + weather snapshot for all four areas |
| `/status` | Inline string | Liveness confirmation |

Powder detection logic lives in `liftwatch/formatter.py:has_powder_signal()`. It checks for Japanese keywords: `パウダー`, `新雪`, `深雪`.

---

## Code Conventions

- **Style**: Standard Python. Snake_case for functions/variables, CamelCase for classes/dataclasses, ALL_CAPS for module-level constants.
- **Dataclasses**: Frozen (`frozen=True`) for immutability. Used for all data models.
- **Async**: All data fetching uses `async/await` with `httpx.AsyncClient`. Concurrent fetches use `asyncio.gather()`. Do not introduce blocking I/O in async paths.
- **Type hints**: Used throughout. Include `from __future__ import annotations` at the top of new files.
- **No test suite**: There are no tests. When adding new logic, write it to be easily unit-testable (pure functions preferred, side effects isolated).

---

## Local Development

```bash
pip install -r requirements.txt
uvicorn api.index:app --reload
```

Endpoints will be at `http://localhost:8000`.

For cron testing, pass `Authorization: Bearer <your-CRON_SECRET>` in the request header.

To register Discord commands (one-time setup):
```bash
DISCORD_APP_ID=... DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... python scripts/register_commands.py
```

---

## Deployment

Deployed to Vercel. `vercel.json` routes all `/api/*` traffic to `api/index.py`. No build step required. Set all environment variables in the Vercel project settings.

The cron job must be triggered externally (e.g. Uptime Robot, GitHub Actions schedule, or Vercel Cron Jobs) by hitting `GET /api/cron` with the correct Bearer token.

---

## Common Gotchas

- **Redis is required for cron** — if `REDIS_URL` is unset the cron endpoint returns a 500.
- **Timestamps are JST** — the Yukiyama API returns JST timestamps. Time formatting in `formatter.py` uses `pytz` (implicit via `datetime`) to convert to JST for display.
- **Lexicographic timestamp comparison** — `_is_newer()` in `api/index.py` compares ISO strings directly. This works correctly for ISO 8601 but will break if the API ever changes timestamp format.
- **Weather point normalization** — The Yukiyama API returns point names in both English and Japanese. `fetcher/weather.py` normalizes these to `"Base"` and `"Peak"` explicitly.
- **Discord PING must return `{"type": 1}`** — Discord verifies the endpoint by sending a type=1 interaction; the handler must return the correct JSON immediately.
