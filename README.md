# liftwatch 🏂⛷️

A Discord-first lift status watcher for Niseko United.

**liftwatch** does two things:
1) **Push alerts** to a Discord channel when lift status changes (so you stop doom-refreshing).
2) Answer **slash commands** like `/powder`, `/status`, `/lift <name>` with fast, readable summaries.

Built for a crew living together in Niseko: quick decisions, less scrolling, more riding.

---

## What it does

### ✅ Automatic lift updates (push, no manual checking)
- Checks the official Niseko United lift status page on an interval
- Detects meaningful changes (ex: “+7 lifts opened”, “upper mountain back online”, “wind hold lifted”)
- Posts a single clean update message to Discord via webhook

### ✅ Slash commands in Discord
- `/status` — health check (“is liftwatch alive?”)
- `/powder` — “powder-ish” picks based on open lifts + predefined zones/heuristics
- `/lift <query>` — search a lift by name and return current status + resort
- `/open` — list open lifts by resort (optional)
- `/night` — night skiing status (optional)

> Note: “Powder” is a practical heuristic (open alpine/upper access + relevant lifts), not a meteorology model.

---

## Architecture

- **Hosting:** Vercel (Python serverless function)
- **Bot interface:** Discord Interactions (slash commands)
- **Alerts:** Discord webhooks (simple POST)
- **Data source:** Official Niseko United lift status page (scraped + cached)

Flow (commands):
`User runs /powder → Discord sends Interaction → /api/interactions → liftwatch responds`

Flow (alerts):
`Scheduled job → scrape + diff → webhook POST → #liftwatch channel`

---

## Tech stack

- Python
- FastAPI (HTTP endpoint)
- PyNaCl (Discord signature verification)
- Requests + BeautifulSoup (scraping)

---

## Local development (optional)

1. Install deps:
   ```bash
   pip install -r requirements.txt