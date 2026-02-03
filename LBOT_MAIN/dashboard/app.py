"""
Dashboard Web - Interface de configuration pour le bot Discord
Flask + Discord OAuth2 + SQLite partagé avec le bot
"""

import os
import sys
import sqlite3
import json
import time
import secrets
from functools import wraps
from pathlib import Path

import requests
from flask import (
    Flask, render_template, redirect, url_for, request,
    session, flash, jsonify, abort
)
from dotenv import load_dotenv

# Load .env from parent directory
load_dotenv(Path(__file__).parent.parent / ".env")

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET", secrets.token_hex(32))

# ==================== CONFIG ====================

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
DISCORD_API = "https://discord.com/api/v10"
DATABASE_PATH = os.getenv("DATABASE_PATH", str(Path(__file__).parent.parent / "data" / "bot.db"))
BOT_TOKEN = os.getenv("DISCORD_TOKEN", "")

# Discord OAuth2 URLs
OAUTH2_URL = (
    f"https://discord.com/api/oauth2/authorize"
    f"?client_id={DISCORD_CLIENT_ID}"
    f"&redirect_uri={DISCORD_REDIRECT_URI}"
    f"&response_type=code"
    f"&scope=identify+guilds"
)

# Admin permission bit
ADMIN_PERMISSION = 0x8


# ==================== DATABASE ====================

def get_db():
    """Get a database connection"""
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
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
        rows = db.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        db.close()


def db_execute(query, params=()):
    db = get_db()
    try:
        db.execute(query, params)
        db.commit()
    finally:
        db.close()


# ==================== DISCORD API HELPERS ====================

def discord_request(endpoint, token=None, bot=False):
    """Make a request to Discord API"""
    headers = {}
    if token:
        prefix = "Bot" if bot else "Bearer"
        headers["Authorization"] = f"{prefix} {token}"
    
    resp = requests.get(f"{DISCORD_API}{endpoint}", headers=headers)
    if resp.status_code == 200:
        return resp.json()
    return None


def exchange_code(code):
    """Exchange OAuth2 code for access token"""
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    resp = requests.post(f"{DISCORD_API}/oauth2/token", data=data)
    if resp.status_code == 200:
        return resp.json()
    return None


def get_bot_guilds():
    """Get guilds the bot is in"""
    if not BOT_TOKEN:
        return []
    data = discord_request("/users/@me/guilds", BOT_TOKEN, bot=True)
    return data or []


def get_guild_channels(guild_id):
    """Get channels for a guild via Bot token"""
    if not BOT_TOKEN:
        return []
    data = discord_request(f"/guilds/{guild_id}/channels", BOT_TOKEN, bot=True)
    return data or []


def get_guild_roles(guild_id):
    """Get roles for a guild via Bot token"""
    if not BOT_TOKEN:
        return []
    data = discord_request(f"/guilds/{guild_id}/roles", BOT_TOKEN, bot=True)
    return data or []


# ==================== AUTH DECORATORS ====================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def guild_admin_required(f):
    """Check user has admin permission on the guild"""
    @wraps(f)
    def decorated(guild_id, *args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        
        # Check if user is admin of guild
        guilds = session.get("guilds", [])
        guild = next((g for g in guilds if str(g["id"]) == str(guild_id)), None)
        
        if not guild:
            flash("Serveur introuvable.", "error")
            return redirect(url_for("servers"))
        
        permissions = int(guild.get("permissions", 0))
        is_owner = guild.get("owner", False)
        
        if not (is_owner or (permissions & ADMIN_PERMISSION)):
            flash("Tu n'as pas la permission d'accéder à ce serveur.", "error")
            return redirect(url_for("servers"))
        
        return f(guild_id, *args, **kwargs)
    return decorated


# ==================== AUTH ROUTES ====================

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("servers"))
    return render_template("login.html")


@app.route("/login")
def login():
    return redirect(OAUTH2_URL)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("Erreur d'authentification.", "error")
        return redirect(url_for("index"))
    
    # Exchange code for token
    token_data = exchange_code(code)
    if not token_data:
        flash("Erreur lors de l'échange du token.", "error")
        return redirect(url_for("index"))
    
    access_token = token_data["access_token"]
    
    # Get user info
    user = discord_request("/users/@me", access_token)
    if not user:
        flash("Impossible de récupérer les infos utilisateur.", "error")
        return redirect(url_for("index"))
    
    # Get user guilds
    guilds = discord_request("/users/@me/guilds", access_token)
    
    # Store in session
    session["user"] = user
    session["access_token"] = access_token
    session["guilds"] = guilds or []
    
    return redirect(url_for("servers"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ==================== SERVER SELECTION ====================

@app.route("/servers")
@login_required
def servers():
    user_guilds = session.get("guilds", [])
    bot_guild_ids = set()
    
    # Get bot's guilds
    try:
        bot_guilds = get_bot_guilds()
        bot_guild_ids = {str(g["id"]) for g in bot_guilds}
    except:
        pass
    
    # Filter: user is admin + bot is in server
    manageable = []
    for guild in user_guilds:
        permissions = int(guild.get("permissions", 0))
        is_owner = guild.get("owner", False)
        is_admin = is_owner or (permissions & ADMIN_PERMISSION)
        
        if is_admin:
            guild["bot_in_server"] = str(guild["id"]) in bot_guild_ids
            guild["icon_url"] = (
                f"https://cdn.discordapp.com/icons/{guild['id']}/{guild['icon']}.png"
                if guild.get("icon") else None
            )
            manageable.append(guild)
    
    # Sort: bot in server first, then alphabetical
    manageable.sort(key=lambda g: (not g["bot_in_server"], g["name"].lower()))
    
    return render_template("servers.html", guilds=manageable, user=session["user"])


# ==================== DASHBOARD ====================

@app.route("/dashboard/<int:guild_id>")
@guild_admin_required
def dashboard(guild_id):
    # Ensure guild_settings exists
    settings = db_fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
    if not settings:
        db_execute("INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)", (guild_id,))
        settings = db_fetchone("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
    
    # Get guild info
    guild_info = next(
        (g for g in session.get("guilds", []) if str(g["id"]) == str(guild_id)),
        {"name": "Serveur", "icon": None, "id": guild_id}
    )
    
    # Get channels and roles
    channels = get_guild_channels(guild_id)
    roles = get_guild_roles(guild_id)
    
    # Sort channels/roles
    text_channels = sorted(
        [c for c in channels if c.get("type") == 0],
        key=lambda c: c.get("position", 0)
    )
    voice_channels = sorted(
        [c for c in channels if c.get("type") == 2],
        key=lambda c: c.get("position", 0)
    )
    categories = sorted(
        [c for c in channels if c.get("type") == 4],
        key=lambda c: c.get("position", 0)
    )
    roles = sorted(
        [r for r in roles if r.get("name") != "@everyone"],
        key=lambda r: -r.get("position", 0)
    )
    
    # Get all configs
    configs = {}
    config_tables = [
        "levels_config", "economy_config", "mod_config", "welcome_config",
        "ticket_config", "starboard_config", "birthday_config", "invite_config",
        "releases_config", "gamedeals_config", "bump_config"
    ]
    
    for table in config_tables:
        row = db_fetchone(f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,))
        if not row:
            try:
                db_execute(f"INSERT OR IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
                row = db_fetchone(f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,))
            except:
                row = {}
        configs[table.replace("_config", "").replace("config", "general")] = row or {}
    
    # Get auto messages
    auto_messages = db_fetchall(
        "SELECT * FROM auto_messages WHERE guild_id = ? ORDER BY id", (guild_id,)
    )
    
    # Get level rewards
    level_rewards = db_fetchall(
        "SELECT * FROM level_rewards WHERE guild_id = ? ORDER BY level", (guild_id,)
    )
    
    # Get shop items
    shop_items = db_fetchall(
        "SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price", (guild_id,)
    )
    
    # Stats
    stats = {
        "members_tracked": db_fetchone(
            "SELECT COUNT(*) as c FROM user_levels WHERE guild_id = ?", (guild_id,)
        ) or {"c": 0},
        "mod_cases": db_fetchone(
            "SELECT COUNT(*) as c FROM mod_cases WHERE guild_id = ?", (guild_id,)
        ) or {"c": 0},
        "giveaways_active": db_fetchone(
            "SELECT COUNT(*) as c FROM giveaways WHERE guild_id = ? AND ended = 0", (guild_id,)
        ) or {"c": 0},
        "tickets_open": db_fetchone(
            "SELECT COUNT(*) as c FROM tickets WHERE guild_id = ? AND status = 'open'", (guild_id,)
        ) or {"c": 0},
    }
    
    return render_template(
        "dashboard.html",
        guild=guild_info,
        guild_id=guild_id,
        settings=settings,
        configs=configs,
        channels=text_channels,
        voice_channels=voice_channels,
        categories=categories,
        roles=roles,
        auto_messages=auto_messages,
        level_rewards=level_rewards,
        shop_items=shop_items,
        stats=stats,
        user=session["user"]
    )


# ==================== API ROUTES ====================

@app.route("/api/<int:guild_id>/settings", methods=["POST"])
@guild_admin_required
def api_settings(guild_id):
    """Update guild settings (module toggles, prefix)"""
    data = request.json
    
    allowed_fields = {
        "prefix", "levels_enabled", "economy_enabled", "welcome_enabled",
        "moderation_enabled", "tickets_enabled", "starboard_enabled",
        "suggestions_enabled", "birthdays_enabled", "temp_voice_enabled",
        "invites_enabled", "releases_enabled", "gamedeals_enabled"
    }
    
    updates = {k: v for k, v in data.items() if k in allowed_fields}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    
    set_clause = ", ".join(f'"{k}" = ?' for k in updates)
    values = list(updates.values()) + [guild_id]
    
    db_execute(
        f'UPDATE guild_settings SET {set_clause} WHERE guild_id = ?',
        tuple(values)
    )
    
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/config/<module>", methods=["POST"])
@guild_admin_required
def api_module_config(guild_id, module):
    """Update module configuration"""
    data = request.json
    
    # Map module to table
    table_map = {
        "levels": "levels_config",
        "economy": "economy_config",
        "moderation": "mod_config",
        "welcome": "welcome_config",
        "tickets": "ticket_config",
        "starboard": "starboard_config",
        "birthdays": "birthday_config",
        "invites": "invite_config",
        "releases": "releases_config",
        "gamedeals": "gamedeals_config",
        "bump": "bump_config",
    }
    
    table = table_map.get(module)
    if not table:
        return jsonify({"error": "Module invalide"}), 400
    
    # Get valid columns for this table
    db = get_db()
    try:
        cursor = db.execute(f"PRAGMA table_info({table})")
        valid_columns = {row["name"] for row in cursor.fetchall()} - {"guild_id"}
    finally:
        db.close()
    
    updates = {k: v for k, v in data.items() if k in valid_columns}
    if not updates:
        return jsonify({"error": "No valid fields"}), 400
    
    # Ensure config row exists
    db_execute(f"INSERT OR IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
    
    set_clause = ", ".join(f'"{k}" = ?' for k in updates)
    values = list(updates.values()) + [guild_id]
    
    db_execute(
        f'UPDATE {table} SET {set_clause} WHERE guild_id = ?',
        tuple(values)
    )
    
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/automessages", methods=["GET"])
@guild_admin_required
def api_automessages_list(guild_id):
    """List auto messages"""
    messages = db_fetchall(
        "SELECT * FROM auto_messages WHERE guild_id = ? ORDER BY id", (guild_id,)
    )
    return jsonify(messages)


@app.route("/api/<int:guild_id>/automessages", methods=["POST"])
@guild_admin_required
def api_automessages_create(guild_id):
    """Create an auto message"""
    data = request.json
    
    content = data.get("content", "").strip()
    channel_id = data.get("channel_id")
    interval = int(data.get("interval", 7200))
    
    if not content or not channel_id:
        return jsonify({"error": "Contenu et salon requis"}), 400
    
    if interval < 300:
        return jsonify({"error": "Intervalle minimum: 5 minutes"}), 400
    
    now = time.time()
    db_execute(
        """INSERT INTO auto_messages 
           (guild_id, channel_id, content, interval, next_run, created_at, enabled)
           VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (guild_id, int(channel_id), content, interval, now + interval, now)
    )
    
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/automessages/<int:msg_id>", methods=["DELETE"])
@guild_admin_required
def api_automessages_delete(guild_id, msg_id):
    """Delete an auto message"""
    db_execute(
        "DELETE FROM auto_messages WHERE id = ? AND guild_id = ?",
        (msg_id, guild_id)
    )
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/automessages/<int:msg_id>/toggle", methods=["POST"])
@guild_admin_required
def api_automessages_toggle(guild_id, msg_id):
    """Toggle an auto message"""
    msg = db_fetchone(
        "SELECT enabled FROM auto_messages WHERE id = ? AND guild_id = ?",
        (msg_id, guild_id)
    )
    if not msg:
        return jsonify({"error": "Not found"}), 404
    
    new_state = 0 if msg["enabled"] else 1
    db_execute(
        "UPDATE auto_messages SET enabled = ? WHERE id = ?",
        (new_state, msg_id)
    )
    return jsonify({"success": True, "enabled": new_state})


@app.route("/api/<int:guild_id>/levelrewards", methods=["POST"])
@guild_admin_required
def api_levelrewards_create(guild_id):
    """Add a level reward"""
    data = request.json
    level = int(data.get("level", 0))
    role_id = int(data.get("role_id", 0))
    
    if level < 1 or not role_id:
        return jsonify({"error": "Niveau et rôle requis"}), 400
    
    db_execute(
        "INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)",
        (guild_id, level, role_id)
    )
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/levelrewards/<int:reward_id>", methods=["DELETE"])
@guild_admin_required
def api_levelrewards_delete(guild_id, reward_id):
    """Delete a level reward"""
    db_execute(
        "DELETE FROM level_rewards WHERE id = ? AND guild_id = ?",
        (reward_id, guild_id)
    )
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/shopitems", methods=["POST"])
@guild_admin_required
def api_shopitems_create(guild_id):
    """Add a shop item"""
    data = request.json
    name = data.get("name", "").strip()
    price = int(data.get("price", 0))
    role_id = data.get("role_id")
    description = data.get("description", "")
    
    if not name or price < 1:
        return jsonify({"error": "Nom et prix requis"}), 400
    
    db_execute(
        """INSERT INTO shop_items (guild_id, name, description, price, role_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (guild_id, name, description, price, int(role_id) if role_id else None, time.time())
    )
    return jsonify({"success": True})


@app.route("/api/<int:guild_id>/shopitems/<int:item_id>", methods=["DELETE"])
@guild_admin_required
def api_shopitems_delete(guild_id, item_id):
    """Delete a shop item"""
    db_execute(
        "DELETE FROM shop_items WHERE id = ? AND guild_id = ?",
        (item_id, guild_id)
    )
    return jsonify({"success": True})


# ==================== RUN ====================

if __name__ == "__main__":
    print(f"Dashboard starting on http://localhost:5000")
    print(f"Database: {DATABASE_PATH}")
    print(f"OAuth2 URL: {OAUTH2_URL}")
    app.run(host="0.0.0.0", port=5000, debug=True)
