"""
Dashboard web pour le bot
oauth2 discord + flask + sqlite

faut que le redirect_uri soit EXACTEMENT le meme dans le .env et dans le dev portal discord
sinon ca boucle a l'infini (j'ai perdu 2h dessus mdr)
"""

import os
import sys
import sqlite3
import json
import time
import secrets
import logging
from functools import wraps
from pathlib import Path
from urllib.parse import quote

import requests
from flask import (
    Flask, render_template, redirect, url_for, request,
    session, flash, jsonify, abort
)
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('dashboard')

load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__)

# si y'a pas de secret dans le .env on en fait un random
# mais du coup les sessions sautent a chaque restart du serveur
_secret = os.getenv("DASHBOARD_SECRET")
if not _secret:
    _secret = secrets.token_hex(32)
    logger.warning("pas de DASHBOARD_SECRET, sessions vont sauter au restart")

app.secret_key = _secret
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["WTF_CSRF_TIME_LIMIT"] = 3600  # 1h avant expiration du token

# protection CSRF - empeche les attaques cross-site
# les forms doivent inclure {{ csrf_token() }}
csrf = CSRFProtect(app)

# rate limiting - evite le spam des API
# stockage en memoire (pour prod faudrait redis)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)


# ============ CONFIG ============

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
DISCORD_API = "https://discord.com/api/v10"
DATABASE_PATH = os.getenv("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "bot.db"))
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")

# l'url oauth - attention:
# - le redirect_uri doit etre encode (quote) sinon discord fait n'importe quoi
# - faut mettre %20 entre identify et guilds, pas un + (bug sur certains browsers)
OAUTH2_URL = (
    f"https://discord.com/api/oauth2/authorize"
    f"?client_id={DISCORD_CLIENT_ID}"
    f"&redirect_uri={quote(DISCORD_REDIRECT_URI, safe='')}"
    f"&response_type=code"
    f"&scope=identify%20guilds"
)

ADMIN_PERMISSION = 0x8  # bit admin discord

# cache en ram pour les guilds de l'user
# on peut pas les mettre dans le cookie parce que ca depasse 4KB facilement
# si t'es sur 50 serveurs ca explose direct
_user_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 min


# ============ ERROR HANDLERS ============

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """quand le token CSRF est invalide ou expire"""
    flash("Session expiree, recharge la page.", "error")
    return redirect(request.referrer or url_for("index"))


@app.errorhandler(429)
def handle_rate_limit(e):
    """quand on depasse le rate limit"""
    return jsonify({"error": "Trop de requetes, attends un peu"}), 429


# ============ DB ============

def get_db():
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.execute("PRAGMA busy_timeout = 5000")  # evite database locked
    return db


def db_fetchone(query, params=()):
    db = get_db()
    try:
        row = db.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def db_fetchall(query, params=()):
    db = get_db()
    try:
        return [dict(r) for r in db.execute(query, params).fetchall()]
    finally:
        db.close()


def db_execute(query, params=()):
    db = get_db()
    try:
        db.execute(query, params)
        db.commit()
    finally:
        db.close()


# ============ DISCORD API ============

def discord_request(endpoint, token=None, bot=False):
    """get sur l'api discord"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"{'Bot' if bot else 'Bearer'} {token}"
    
    try:
        resp = requests.get(f"{DISCORD_API}{endpoint}", headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"discord api {resp.status_code} sur {endpoint}")
        return None
    except Exception as e:
        logger.error(f"discord api crash: {e}")
        return None


def exchange_code(code):
    """echange le code oauth contre un token - c'est la que ca foire souvent"""
    try:
        resp = requests.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )
        
        if resp.status_code == 200:
            return resp.json()
        
        # log pour debug quand ca marche pas
        logger.error(f"token exchange {resp.status_code}: {resp.text}")
        return None
            
    except Exception as e:
        logger.error(f"token exchange crash: {e}")
        return None


def get_bot_guilds():
    if not BOT_TOKEN:
        return []
    return discord_request("/users/@me/guilds", BOT_TOKEN, bot=True) or []


def get_guild_channels(guild_id):
    if not BOT_TOKEN:
        return []
    return discord_request(f"/guilds/{guild_id}/channels", BOT_TOKEN, bot=True) or []


def get_guild_roles(guild_id):
    if not BOT_TOKEN:
        return []
    return discord_request(f"/guilds/{guild_id}/roles", BOT_TOKEN, bot=True) or []


# ============ CACHE ============

def cache_user_data(user_id: str, guilds: list):
    _user_cache[user_id] = {"guilds": guilds, "cached_at": time.time()}


def get_cached_guilds(user_id: str) -> list:
    if user_id not in _user_cache:
        return []
    
    entry = _user_cache[user_id]
    if time.time() - entry["cached_at"] > CACHE_TTL:
        del _user_cache[user_id]
        return []
    
    return entry["guilds"]


def clear_user_cache(user_id: str):
    _user_cache.pop(user_id, None)


# ============ DECORATORS ============

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def guild_admin_required(f):
    """check que l'user est admin du serveur"""
    @wraps(f)
    def decorated(guild_id, *args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        
        guilds = get_cached_guilds(session["user_id"])
        
        if not guilds:
            session.clear()
            flash("Session expiree.", "error")
            return redirect(url_for("login"))
        
        guild = next((g for g in guilds if str(g["id"]) == str(guild_id)), None)
        if not guild:
            flash("Serveur pas trouve.", "error")
            return redirect(url_for("servers"))
        
        perms = int(guild.get("permissions", 0))
        if not (guild.get("owner") or (perms & ADMIN_PERMISSION)):
            flash("T'es pas admin la-dessus.", "error")
            return redirect(url_for("servers"))
        
        return f(guild_id, *args, **kwargs)
    return decorated


# ============ AUTH ============

@app.route("/")
def index():
    if "user_id" in session and get_cached_guilds(session["user_id"]):
        return redirect(url_for("servers"))
    session.clear()
    return render_template("login.html")


@app.route("/login")
def login():
    return redirect(OAUTH2_URL)


@app.route("/callback")
def callback():
    # discord renvoie parfois direct une erreur
    if request.args.get("error"):
        logger.error(f"oauth error: {request.args.get('error')}")
        flash("Discord a refuse.", "error")
        return redirect(url_for("index"))
    
    code = request.args.get("code")
    if not code:
        flash("Pas de code.", "error")
        return redirect(url_for("index"))
    
    # echange code -> token
    token_data = exchange_code(code)
    if not token_data or "access_token" not in token_data:
        flash("Impossible de recuperer le token.", "error")
        return redirect(url_for("index"))
    
    access_token = token_data["access_token"]
    
    # recup infos user
    user = discord_request("/users/@me", access_token)
    if not user:
        flash("Impossible de te trouver sur discord.", "error")
        return redirect(url_for("index"))
    
    guilds = discord_request("/users/@me/guilds", access_token) or []
    
    # stocke le minimum dans la session
    session["user_id"] = str(user["id"])
    session["user"] = {
        "id": user["id"],
        "username": user.get("username"),
        "global_name": user.get("global_name"),
        "avatar": user.get("avatar"),
    }
    
    # guilds en cache memoire (pas dans le cookie)
    cache_user_data(str(user["id"]), guilds)
    
    logger.info(f"login: {user.get('username')} ({len(guilds)} serveurs)")
    return redirect(url_for("servers"))


@app.route("/logout")
def logout():
    if "user_id" in session:
        clear_user_cache(session["user_id"])
    session.clear()
    return redirect(url_for("index"))


# ============ SERVERS ============

@app.route("/servers")
@login_required
def servers():
    user_guilds = get_cached_guilds(session["user_id"])
    
    if not user_guilds:
        session.clear()
        return redirect(url_for("index"))
    
    # serveurs ou le bot est
    bot_guild_ids = {str(g["id"]) for g in get_bot_guilds()}
    
    # filtre les serveurs ou l'user est admin
    manageable = []
    for g in user_guilds:
        perms = int(g.get("permissions", 0))
        if g.get("owner") or (perms & ADMIN_PERMISSION):
            g["bot_in_server"] = str(g["id"]) in bot_guild_ids
            g["icon_url"] = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png" if g.get("icon") else None
            manageable.append(g)
    
    # trie: bot present en premier
    manageable.sort(key=lambda x: (not x["bot_in_server"], x["name"].lower()))
    
    return render_template("servers.html", guilds=manageable, user=session["user"])


# ============ DASHBOARD ============

@app.route("/dashboard/<int:guild_id>")
@guild_admin_required
def dashboard(guild_id):
    # cree la row settings si elle existe pas
    settings = db_fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
    if not settings:
        db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
        settings = db_fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
    
    # info serveur depuis le cache
    guilds = get_cached_guilds(session["user_id"])
    guild_info = next((g for g in guilds if str(g["id"]) == str(guild_id)), {"name": "?", "id": guild_id})
    
    # channels et roles via api discord
    channels = get_guild_channels(guild_id)
    roles = get_guild_roles(guild_id)
    
    text_channels = sorted([c for c in channels if c.get("type") == 0], key=lambda c: c.get("position", 0))
    voice_channels = sorted([c for c in channels if c.get("type") == 2], key=lambda c: c.get("position", 0))
    categories = sorted([c for c in channels if c.get("type") == 4], key=lambda c: c.get("position", 0))
    roles = sorted([r for r in roles if r.get("name") != "@everyone"], key=lambda r: -r.get("position", 0))
    
    # charge les configs de chaque module
    configs = {}
    for table in ["levels_config", "economy_config", "mod_config", "welcome_config",
                  "ticket_config", "starboard_config", "birthday_config", "invite_config",
                  "releases_config", "gamedeals_config", "bump_config"]:
        row = db_fetchone(f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,))
        if not row:
            try:
                db_execute(f"INSERT OR IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
                row = db_fetchone(f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,))
            except:
                row = {}
        configs[table.replace("_config", "")] = row or {}
    
    # autres trucs
    auto_messages = db_fetchall("SELECT * FROM auto_messages WHERE guild_id = ? ORDER BY id", (guild_id,))
    level_rewards = db_fetchall("SELECT * FROM level_rewards WHERE guild_id = ? ORDER BY level", (guild_id,))
    shop_items = db_fetchall("SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price", (guild_id,))
    
    # stats
    stats = {
        "members_tracked": (db_fetchone("SELECT COUNT(*) as c FROM user_levels WHERE guild_id = ?", (guild_id,)) or {"c": 0}),
        "mod_cases": (db_fetchone("SELECT COUNT(*) as c FROM mod_cases WHERE guild_id = ?", (guild_id,)) or {"c": 0}),
        "giveaways_active": (db_fetchone("SELECT COUNT(*) as c FROM giveaways WHERE guild_id = ? AND ended = 0", (guild_id,)) or {"c": 0}),
        "tickets_open": (db_fetchone("SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,)) or {"c": 0}),
    }
    
    return render_template("dashboard.html",
        guild=guild_info, guild_id=guild_id, settings=settings, configs=configs,
        channels=text_channels, voice_channels=voice_channels, categories=categories,
        roles=roles, auto_messages=auto_messages, level_rewards=level_rewards,
        shop_items=shop_items, stats=stats, user=session["user"]
    )


# ============ API ============

@app.route("/api/<int:guild_id>/settings", methods=["POST"])
@limiter.limit("10 per minute")
@guild_admin_required
def api_settings(guild_id):
    data = request.json
    
    allowed = {"prefix", "levels_enabled", "economy_enabled", "welcome_enabled",
               "moderation_enabled", "tickets_enabled", "starboard_enabled",
               "suggestions_enabled", "birthdays_enabled", "temp_voice_enabled",
               "invites_enabled", "releases_enabled", "gamedeals_enabled"}
    
    updates = {k: v for k, v in data.items() if k in allowed}
    if not updates:
        return jsonify({"error": "rien a save"}), 400
    
    set_clause = ", ".join(f'"{k}" = ?' for k in updates)
    db_execute(f'UPDATE guild_settings SET {set_clause} WHERE guild_id = ?',
               tuple(list(updates.values()) + [guild_id]))
    
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/config/<module>", methods=["POST"])
@limiter.limit("10 per minute")
@guild_admin_required
def api_module_config(guild_id, module):
    data = request.json
    
    tables = {
        "levels": "levels_config", "economy": "economy_config", "moderation": "mod_config",
        "welcome": "welcome_config", "tickets": "ticket_config", "starboard": "starboard_config",
        "birthdays": "birthday_config", "invites": "invite_config", "releases": "releases_config",
        "gamedeals": "gamedeals_config", "bump": "bump_config",
    }
    
    table = tables.get(module)
    if not table:
        return jsonify({"error": "module inconnu"}), 400
    
    # recup les colonnes valides
    db = get_db()
    try:
        valid = {r["name"] for r in db.execute(f"PRAGMA table_info({table})").fetchall()} - {"guild_id"}
    finally:
        db.close()
    
    updates = {k: v for k, v in data.items() if k in valid}
    if not updates:
        return jsonify({"error": "rien a save"}), 400
    
    db_execute(f"INSERT OR IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
    set_clause = ", ".join(f'"{k}" = ?' for k in updates)
    db_execute(f'UPDATE {table} SET {set_clause} WHERE guild_id = ?',
               tuple(list(updates.values()) + [guild_id]))
    
    return jsonify({"success": True})


# --- automessages ---

@app.route("/api/<int:guild_id>/automessages", methods=["GET"])
@limiter.limit("30 per minute")
@guild_admin_required
def api_automessages_list(guild_id):
    return jsonify(db_fetchall("SELECT * FROM auto_messages WHERE guild_id = ? ORDER BY id", (guild_id,)))


@app.route("/api/<int:guild_id>/automessages", methods=["POST"])
@limiter.limit("5 per minute")
@guild_admin_required
def api_automessages_create(guild_id):
    data = request.json
    content = data.get("content", "").strip()
    channel_id = data.get("channel_id")
    interval = int(data.get("interval", 7200))
    
    if not content or not channel_id:
        return jsonify({"error": "manque contenu ou channel"}), 400
    if interval < 300:
        return jsonify({"error": "min 5 minutes"}), 400
    
    now = time.time()
    db_execute(
        "INSERT INTO auto_messages (guild_id, channel_id, content, interval, next_run, created_at, enabled) VALUES (?, ?, ?, ?, ?, ?, 1)",
        (guild_id, int(channel_id), content, interval, now + interval, now)
    )
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/automessages/<int:msg_id>", methods=["DELETE"])
@limiter.limit("10 per minute")
@guild_admin_required
def api_automessages_delete(guild_id, msg_id):
    db_execute("DELETE FROM auto_messages WHERE id = ? AND guild_id = ?", (msg_id, guild_id))
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/automessages/<int:msg_id>/toggle", methods=["POST"])
@limiter.limit("10 per minute")
@guild_admin_required
def api_automessages_toggle(guild_id, msg_id):
    msg = db_fetchone("SELECT enabled FROM auto_messages WHERE id = ? AND guild_id = ?", (msg_id, guild_id))
    if not msg:
        return jsonify({"error": "existe pas"}), 404
    
    new_state = 0 if msg["enabled"] else 1
    db_execute("UPDATE auto_messages SET enabled = ? WHERE id = ?", (new_state, msg_id))
    return jsonify({"success": True, "enabled": new_state})


# --- level rewards ---

@app.route("/api/<int:guild_id>/levelrewards", methods=["POST"])
@limiter.limit("5 per minute")
@guild_admin_required
def api_levelrewards_create(guild_id):
    data = request.json
    level = int(data.get("level", 0))
    role_id = int(data.get("role_id", 0))
    
    if level < 1 or not role_id:
        return jsonify({"error": "level et role requis"}), 400
    
    db_execute("INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)",
               (guild_id, level, role_id))
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/levelrewards/<int:reward_id>", methods=["DELETE"])
@limiter.limit("10 per minute")
@guild_admin_required
def api_levelrewards_delete(guild_id, reward_id):
    db_execute("DELETE FROM level_rewards WHERE id = ? AND guild_id = ?", (reward_id, guild_id))
    return jsonify({"success": True})


# --- shop ---

@app.route("/api/<int:guild_id>/shopitems", methods=["POST"])
@limiter.limit("5 per minute")
@guild_admin_required
def api_shopitems_create(guild_id):
    data = request.json
    name = data.get("name", "").strip()
    price = int(data.get("price", 0))
    
    if not name or price < 1:
        return jsonify({"error": "nom et prix requis"}), 400
    
    db_execute(
        "INSERT INTO shop_items (guild_id, name, description, price, role_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (guild_id, name, data.get("description", ""), price,
         int(data["role_id"]) if data.get("role_id") else None, time.time())
    )
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/shopitems/<int:item_id>", methods=["DELETE"])
@limiter.limit("10 per minute")
@guild_admin_required
def api_shopitems_delete(guild_id, item_id):
    db_execute("DELETE FROM shop_items WHERE id = ? AND guild_id = ?", (item_id, guild_id))
    return jsonify({"success": True})


# ============ MAIN ============

if __name__ == "__main__":
    print("=" * 40)
    print("  Dashboard L3D3B07")
    print("=" * 40)
    
    # check config
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        print("\n  [X] CLIENT_ID ou CLIENT_SECRET manquant")
        print("      -> remplis le .env")
        sys.exit(1)
    
    if not BOT_TOKEN:
        print("  [!] DISCORD_TOKEN manquant (channels/roles vont pas marcher)")
    
    print(f"\n  redirect uri: {DISCORD_REDIRECT_URI}")
    print(f"  db: {DATABASE_PATH}")
    print(f"\n  -> http://localhost:5000")
    print("=" * 40)
    
    app.run(host="0.0.0.0", port=5000, debug=True)
