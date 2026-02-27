import os
import requests

APP_ID = os.environ["DISCORD_APP_ID"]
BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = os.environ["DISCORD_GUILD_ID"]

url = f"https://discord.com/api/v10/applications/{APP_ID}/guilds/{GUILD_ID}/commands"

commands = [
    {
        "name": "powder",
        "description": "Show resorts with a powder signal (snow_state / fresh snow delta)"
    },
    {
        "name": "summary",
        "description": "One-shot snapshot: lifts + peak/base weather for all resorts"
    },
    {
        "name": "status",
        "description": "Check if liftwatch is alive"
    },
    # Future ideas:
    # {"name": "closed", "description": "Show only lifts that are not operating"},
    # {"name": "alerts", "description": "Show what the cron is watching / last posted timestamps"},
]

resp = requests.put(
    url,
    json=commands,
    headers={"Authorization": f"Bot {BOT_TOKEN}"}
)

print(resp.status_code, resp.text)