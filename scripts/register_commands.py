import os
import requests

APP_ID = os.environ["DISCORD_APP_ID"]
BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = os.environ["DISCORD_GUILD_ID"]

url = f"https://discord.com/api/v10/applications/{APP_ID}/guilds/{GUILD_ID}/commands"

commands = [
    {
        "name": "powder",
        "description": "Show powder-ish lift/resort picks right now"
    },
    {
        "name": "status",
        "description": "Check if liftwatch is alive"
    }
]

r = requests.put(
    url,
    json=commands,
    headers={"Authorization": f"Bot {BOT_TOKEN}"}
)
print(r.status_code, r.text)