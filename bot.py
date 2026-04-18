import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os, json, asyncio, logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from scraper import fetch_vinted_items

print("🔥 BOT FILE LOADED 🔥")

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("data/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ---------- ENV ----------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ROLE_NAME = os.getenv("ADMIN_ROLE", "Admin")

# ---------- INTENTS ----------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------- FILES ----------
CONFIG_FILE = "config.json"
SEEN_FILE = "data/seen_items.json"
os.makedirs("data", exist_ok=True)

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

config = load_json(CONFIG_FILE, {"brands": {}})
seen_items = set(load_json(SEEN_FILE, [])[-500:])

# Executor pour lancer Playwright sans bloquer Discord
executor = ThreadPoolExecutor(max_workers=2)

# ---------- HELPERS ----------
def is_admin():
    async def predicate(ctx):
        return any(r.name == ADMIN_ROLE_NAME for r in ctx.author.roles)
    return commands.check(predicate)

async def run_scraper(url):
    """Lance le scraper dans un thread séparé pour ne pas bloquer Discord."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, lambda: asyncio.run(fetch_vinted_items(url)))

# ---------- EVENTS ----------
@bot.event
async def on_ready():
    log.info(f"✅ Connecté en tant que {bot.user} (ID: {bot.user.id})")
    check_vinted.start()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ Tu n'as pas la permission d'utiliser cette commande.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Argument manquant : `{error.param.name}`")
    else:
        log.error(f"Erreur commande {ctx.command}: {error}")

# ---------- LOOP PRINCIPALE ----------
@tasks.loop(minutes=5)
async def check_vinted():
    global seen_items
    for brand, data in config.get("brands", {}).items():
        try:
            channel = bot.get_channel(data["channel_id"])
            if not channel:
                log.warning(f"Salon introuvable pour {brand} (ID: {data['channel_id']})")
                continue

            log.info(f"🔍 Vérification de {brand}...")
            items = await run_scraper(data["search_url"])

            nouveaux = 0
            for item in items:
                item_id = item["url"]
                if item_id not in seen_items:
                    seen_items.add(item_id)
                    save_json(SEEN_FILE, list(seen_items)[-500:])

                    embed = discord.Embed(
                        title=f"🆕 {item.get('title', 'Nouvel article')[:50]}",
                        url=item["url"],
                        color=discord.Color.green(),
                        timestamp=datetime.now(timezone.utc)
                    )
                    embed.add_field(name="💰 Prix", value=item.get("price", "N/A"), inline=True)
                    embed.add_field(name="📦 Taille", value=item.get("size", "N/A"), inline=True)
                    embed.add_field(name="🏷️ Marque", value=brand.upper(), inline=True)
                    if item.get("image"):
                        embed.set_thumbnail(url=item["image"])
                    embed.set_footer(text="Vinted • Achat/Revente Server")

                    await channel.send(embed=embed)
                    await asyncio.sleep(1)
                    nouveaux += 1

            log.info(f"✅ {brand}: {nouveaux} nouveau(x) article(s)")

        except Exception as e:
            log.error(f"Erreur lors du check de {brand}: {e}")

        # Pause entre chaque marque pour ne pas surcharger
        await asyncio.sleep(5)

@check_vinted.before_loop
async def before_check():
    await bot.wait_until_ready()

# ---------- COMMANDES ADMIN ----------
@bot.command(name="addmarque")
@is_admin()
async def add_brand(ctx, brand: str, channel: discord.TextChannel, *, search_url: str):
    """Usage: !addmarque nike #salon-nike https://www.vinted.fr/catalog?..."""
    config.setdefault("brands", {})[brand.lower()] = {
        "channel_id": channel.id,
        "search_url": search_url
    }
    save_json(CONFIG_FILE, config)
    await ctx.send(f"✅ Marque **{brand.upper()}** ajoutée → {channel.mention}")

@bot.command(name="delmarque")
@is_admin()
async def del_brand(ctx, brand: str):
    if brand.lower() in config.get("brands", {}):
        del config["brands"][brand.lower()]
        save_json(CONFIG_FILE, config)
        await ctx.send(f"🗑️ Marque **{brand.upper()}** supprimée.")
    else:
        await ctx.send(f"❌ Marque **{brand}** introuvable.")

@bot.command(name="marques")
async def list_brands(ctx):
    brands = config.get("brands", {})
    if not brands:
        await ctx.send("Aucune marque configurée.")
        return
    embed = discord.Embed(title="📋 Marques surveillées", color=discord.Color.blue())
    for brand, data in brands.items():
        channel = bot.get_channel(data["channel_id"])
        chan_mention = channel.mention if channel else f"ID: {data['channel_id']}"
        embed.add_field(name=brand.upper(), value=chan_mention, inline=False)
    await ctx.send(embed=embed)

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latence: {round(bot.latency * 1000)}ms")

# ---------- RUN ----------
bot.run(TOKEN)
