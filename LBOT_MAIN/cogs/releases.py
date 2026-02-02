"""
Releases Cog - Annonces automatiques de sorties (Jeux, Anime, Séries, Films)

APIs utilisées:
- RAWG.io pour les jeux vidéo
- AniList (GraphQL) pour les anime
- TMDB pour les séries/films
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json
import os

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    format_message, is_admin
)


class Releases(commands.Cog):
    """Annonces automatiques de sorties médias"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        
        # API Keys (from .env or set via command)
        self.rawg_api_key = os.getenv("RAWG_API_KEY")
        self.tmdb_api_key = os.getenv("TMDB_API_KEY")
        
        # Cache pour éviter les doublons
        self.announced_cache: Dict[str, set] = {
            "games": set(),
            "anime": set(),
            "series": set(),
            "films": set()
        }
    
    async def cog_load(self):
        """Initialize session and start tasks"""
        self.session = aiohttp.ClientSession()
        self.check_releases.start()
    
    async def cog_unload(self):
        """Cleanup"""
        self.check_releases.cancel()
        if self.session:
            await self.session.close()
    
    async def get_config(self, guild_id: int) -> dict:
        """Get releases config for guild"""
        row = await db.fetchone(
            "SELECT * FROM releases_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO releases_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM releases_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    @tasks.loop(hours=6)
    async def check_releases(self):
        """Check for new releases periodically"""
        try:
            # Get all guilds with releases enabled
            guilds = await db.fetchall(
                """SELECT rc.*, gs.guild_id FROM releases_config rc
                   JOIN guild_settings gs ON rc.guild_id = gs.guild_id
                   WHERE gs.releases_enabled = 1"""
            )
            
            for config in guilds:
                guild = self.bot.get_guild(config["guild_id"])
                if not guild:
                    continue
                
                # Check each category
                if config.get("games_channel_id"):
                    await self.check_game_releases(guild, config)
                
                if config.get("anime_channel_id"):
                    await self.check_anime_releases(guild, config)
                
                if config.get("series_channel_id"):
                    await self.check_series_releases(guild, config)
                
                if config.get("films_channel_id"):
                    await self.check_film_releases(guild, config)
                    
        except Exception as e:
            print(f"Error checking releases: {e}")
    
    @check_releases.before_loop
    async def before_check_releases(self):
        await self.bot.wait_until_ready()
    
    # ==================== GAME RELEASES (RAWG API) ====================
    
    async def check_game_releases(self, guild: discord.Guild, config: dict):
        """Check for new game releases using RAWG API"""
        channel = guild.get_channel(config["games_channel_id"])
        if not channel:
            return
        
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            next_week = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
            
            url = f"https://api.rawg.io/api/games"
            params = {
                "dates": f"{today},{next_week}",
                "ordering": "-added",
                "page_size": 10
            }
            
            if self.rawg_api_key:
                params["key"] = self.rawg_api_key
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return
                
                data = await resp.json()
                games = data.get("results", [])
                
                for game in games:
                    game_id = str(game.get("id"))
                    cache_key = f"{guild.id}_{game_id}"
                    
                    if cache_key in self.announced_cache["games"]:
                        continue
                    
                    # Check if already announced in DB
                    existing = await db.fetchone(
                        "SELECT * FROM announced_releases WHERE guild_id = ? AND item_id = ? AND category = 'game'",
                        (guild.id, game_id)
                    )
                    if existing:
                        self.announced_cache["games"].add(cache_key)
                        continue
                    
                    # Announce
                    embed = self.create_game_embed(game)
                    
                    role_mention = ""
                    if config.get("games_role_id"):
                        role = guild.get_role(config["games_role_id"])
                        if role:
                            role_mention = role.mention
                    
                    try:
                        await channel.send(content=role_mention or None, embed=embed)
                        
                        # Mark as announced
                        await db.execute(
                            "INSERT INTO announced_releases (guild_id, category, item_id, announced_at) VALUES (?, 'game', ?, ?)",
                            (guild.id, game_id, time.time())
                        )
                        self.announced_cache["games"].add(cache_key)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error checking game releases: {e}")
    
    def create_game_embed(self, game: dict) -> discord.Embed:
        """Create embed for a game release"""
        embed = discord.Embed(
            title=f"🎮 {game.get('name', 'Unknown')}",
            color=discord.Color.blue(),
            url=f"https://rawg.io/games/{game.get('slug', '')}"
        )
        
        if game.get("background_image"):
            embed.set_image(url=game["background_image"])
        
        if game.get("released"):
            embed.add_field(name="📅 Date de sortie", value=game["released"], inline=True)
        
        if game.get("metacritic"):
            embed.add_field(name="⭐ Metacritic", value=str(game["metacritic"]), inline=True)
        
        platforms = game.get("platforms", [])
        if platforms:
            platform_names = [p.get("platform", {}).get("name", "") for p in platforms[:5]]
            embed.add_field(name="🖥️ Plateformes", value=", ".join(platform_names), inline=False)
        
        genres = game.get("genres", [])
        if genres:
            genre_names = [g.get("name", "") for g in genres[:4]]
            embed.add_field(name="🏷️ Genres", value=", ".join(genre_names), inline=True)
        
        embed.set_footer(text="Données via RAWG.io")
        return embed
    
    # ==================== ANIME RELEASES (AniList API) ====================
    
    async def check_anime_releases(self, guild: discord.Guild, config: dict):
        """Check for new anime releases using AniList GraphQL API"""
        channel = guild.get_channel(config["anime_channel_id"])
        if not channel:
            return
        
        try:
            # AniList GraphQL query for airing anime this season
            query = """
            query {
                Page(page: 1, perPage: 10) {
                    media(type: ANIME, status: RELEASING, sort: POPULARITY_DESC) {
                        id
                        title {
                            romaji
                            english
                        }
                        description
                        coverImage {
                            large
                        }
                        episodes
                        nextAiringEpisode {
                            episode
                            airingAt
                        }
                        genres
                        averageScore
                        siteUrl
                    }
                }
            }
            """
            
            url = "https://graphql.anilist.co"
            
            async with self.session.post(url, json={"query": query}) as resp:
                if resp.status != 200:
                    return
                
                data = await resp.json()
                animes = data.get("data", {}).get("Page", {}).get("media", [])
                
                for anime in animes:
                    # Only announce if new episode is airing soon (within 24h)
                    next_ep = anime.get("nextAiringEpisode")
                    if not next_ep:
                        continue
                    
                    airing_at = next_ep.get("airingAt", 0)
                    if airing_at - time.time() > 86400 or airing_at < time.time():
                        continue
                    
                    anime_id = str(anime.get("id"))
                    episode = next_ep.get("episode", 1)
                    cache_key = f"{guild.id}_{anime_id}_ep{episode}"
                    
                    if cache_key in self.announced_cache["anime"]:
                        continue
                    
                    existing = await db.fetchone(
                        "SELECT * FROM announced_releases WHERE guild_id = ? AND item_id = ? AND category = 'anime'",
                        (guild.id, f"{anime_id}_ep{episode}")
                    )
                    if existing:
                        self.announced_cache["anime"].add(cache_key)
                        continue
                    
                    embed = self.create_anime_embed(anime)
                    
                    role_mention = ""
                    if config.get("anime_role_id"):
                        role = guild.get_role(config["anime_role_id"])
                        if role:
                            role_mention = role.mention
                    
                    try:
                        await channel.send(content=role_mention or None, embed=embed)
                        
                        await db.execute(
                            "INSERT INTO announced_releases (guild_id, category, item_id, announced_at) VALUES (?, 'anime', ?, ?)",
                            (guild.id, f"{anime_id}_ep{episode}", time.time())
                        )
                        self.announced_cache["anime"].add(cache_key)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error checking anime releases: {e}")
    
    def create_anime_embed(self, anime: dict) -> discord.Embed:
        """Create embed for an anime episode"""
        title = anime.get("title", {})
        name = title.get("english") or title.get("romaji") or "Unknown"
        
        next_ep = anime.get("nextAiringEpisode", {})
        episode = next_ep.get("episode", "?")
        airing_at = next_ep.get("airingAt", 0)
        
        embed = discord.Embed(
            title=f"📺 {name} - Épisode {episode}",
            color=discord.Color.purple(),
            url=anime.get("siteUrl", "")
        )
        
        cover = anime.get("coverImage", {}).get("large")
        if cover:
            embed.set_thumbnail(url=cover)
        
        if airing_at:
            airing_time = datetime.fromtimestamp(airing_at)
            embed.add_field(
                name="📅 Diffusion",
                value=f"<t:{airing_at}:R>",
                inline=True
            )
        
        if anime.get("episodes"):
            embed.add_field(
                name="📊 Épisodes",
                value=f"{episode}/{anime['episodes']}",
                inline=True
            )
        
        if anime.get("averageScore"):
            embed.add_field(
                name="⭐ Score",
                value=f"{anime['averageScore']}/100",
                inline=True
            )
        
        genres = anime.get("genres", [])
        if genres:
            embed.add_field(name="🏷️ Genres", value=", ".join(genres[:4]), inline=False)
        
        # Clean description (remove HTML)
        desc = anime.get("description", "")
        if desc:
            import re
            desc = re.sub(r'<[^>]+>', '', desc)
            if len(desc) > 200:
                desc = desc[:200] + "..."
            embed.description = desc
        
        embed.set_footer(text="Données via AniList")
        return embed
    
    # ==================== SERIES/FILMS RELEASES (TMDB API) ====================
    
    async def check_series_releases(self, guild: discord.Guild, config: dict):
        """Check for new series releases using TMDB API"""
        if not self.tmdb_api_key:
            return
        
        channel = guild.get_channel(config["series_channel_id"])
        if not channel:
            return
        
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            url = f"https://api.themoviedb.org/3/tv/on_the_air"
            params = {
                "api_key": self.tmdb_api_key,
                "language": "fr-FR",
                "page": 1
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return
                
                data = await resp.json()
                series_list = data.get("results", [])[:10]
                
                for series in series_list:
                    series_id = str(series.get("id"))
                    cache_key = f"{guild.id}_{series_id}"
                    
                    if cache_key in self.announced_cache["series"]:
                        continue
                    
                    existing = await db.fetchone(
                        "SELECT * FROM announced_releases WHERE guild_id = ? AND item_id = ? AND category = 'series'",
                        (guild.id, series_id)
                    )
                    if existing:
                        self.announced_cache["series"].add(cache_key)
                        continue
                    
                    embed = self.create_series_embed(series)
                    
                    role_mention = ""
                    if config.get("series_role_id"):
                        role = guild.get_role(config["series_role_id"])
                        if role:
                            role_mention = role.mention
                    
                    try:
                        await channel.send(content=role_mention or None, embed=embed)
                        
                        await db.execute(
                            "INSERT INTO announced_releases (guild_id, category, item_id, announced_at) VALUES (?, 'series', ?, ?)",
                            (guild.id, series_id, time.time())
                        )
                        self.announced_cache["series"].add(cache_key)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error checking series releases: {e}")
    
    async def check_film_releases(self, guild: discord.Guild, config: dict):
        """Check for new film releases using TMDB API"""
        if not self.tmdb_api_key:
            return
        
        channel = guild.get_channel(config["films_channel_id"])
        if not channel:
            return
        
        try:
            url = f"https://api.themoviedb.org/3/movie/now_playing"
            params = {
                "api_key": self.tmdb_api_key,
                "language": "fr-FR",
                "region": "FR",
                "page": 1
            }
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return
                
                data = await resp.json()
                films = data.get("results", [])[:10]
                
                for film in films:
                    film_id = str(film.get("id"))
                    cache_key = f"{guild.id}_{film_id}"
                    
                    if cache_key in self.announced_cache["films"]:
                        continue
                    
                    existing = await db.fetchone(
                        "SELECT * FROM announced_releases WHERE guild_id = ? AND item_id = ? AND category = 'film'",
                        (guild.id, film_id)
                    )
                    if existing:
                        self.announced_cache["films"].add(cache_key)
                        continue
                    
                    embed = self.create_film_embed(film)
                    
                    role_mention = ""
                    if config.get("films_role_id"):
                        role = guild.get_role(config["films_role_id"])
                        if role:
                            role_mention = role.mention
                    
                    try:
                        await channel.send(content=role_mention or None, embed=embed)
                        
                        await db.execute(
                            "INSERT INTO announced_releases (guild_id, category, item_id, announced_at) VALUES (?, 'film', ?, ?)",
                            (guild.id, film_id, time.time())
                        )
                        self.announced_cache["films"].add(cache_key)
                    except:
                        pass
                        
        except Exception as e:
            print(f"Error checking film releases: {e}")
    
    def create_series_embed(self, series: dict) -> discord.Embed:
        """Create embed for a series"""
        embed = discord.Embed(
            title=f"📺 {series.get('name', 'Unknown')}",
            description=series.get("overview", "")[:300] + "..." if len(series.get("overview", "")) > 300 else series.get("overview", ""),
            color=discord.Color.green(),
            url=f"https://www.themoviedb.org/tv/{series.get('id')}"
        )
        
        if series.get("poster_path"):
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w300{series['poster_path']}")
        
        if series.get("backdrop_path"):
            embed.set_image(url=f"https://image.tmdb.org/t/p/w780{series['backdrop_path']}")
        
        if series.get("first_air_date"):
            embed.add_field(name="📅 Première diffusion", value=series["first_air_date"], inline=True)
        
        if series.get("vote_average"):
            embed.add_field(name="⭐ Note", value=f"{series['vote_average']:.1f}/10", inline=True)
        
        embed.set_footer(text="Données via TMDB")
        return embed
    
    def create_film_embed(self, film: dict) -> discord.Embed:
        """Create embed for a film"""
        embed = discord.Embed(
            title=f"🎬 {film.get('title', 'Unknown')}",
            description=film.get("overview", "")[:300] + "..." if len(film.get("overview", "")) > 300 else film.get("overview", ""),
            color=discord.Color.red(),
            url=f"https://www.themoviedb.org/movie/{film.get('id')}"
        )
        
        if film.get("poster_path"):
            embed.set_thumbnail(url=f"https://image.tmdb.org/t/p/w300{film['poster_path']}")
        
        if film.get("backdrop_path"):
            embed.set_image(url=f"https://image.tmdb.org/t/p/w780{film['backdrop_path']}")
        
        if film.get("release_date"):
            embed.add_field(name="📅 Sortie", value=film["release_date"], inline=True)
        
        if film.get("vote_average"):
            embed.add_field(name="⭐ Note", value=f"{film['vote_average']:.1f}/10", inline=True)
        
        embed.set_footer(text="Données via TMDB")
        return embed
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="releases", aliases=["sorties"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def releases(self, ctx: commands.Context):
        """Configure les annonces de sorties"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT releases_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        games_channel = ctx.guild.get_channel(config.get("games_channel_id"))
        anime_channel = ctx.guild.get_channel(config.get("anime_channel_id"))
        series_channel = ctx.guild.get_channel(config.get("series_channel_id"))
        films_channel = ctx.guild.get_channel(config.get("films_channel_id"))
        
        embed = create_embed(
            title="🎬 Configuration des sorties",
            color=discord.Color.blue(),
            fields=[
                ("État", "✅ Activé" if settings and settings["releases_enabled"] else "❌ Désactivé", True),
                ("🎮 Jeux", games_channel.mention if games_channel else "Non configuré", True),
                ("📺 Anime", anime_channel.mention if anime_channel else "Non configuré", True),
                ("📺 Séries", series_channel.mention if series_channel else "Non configuré", True),
                ("🎬 Films", films_channel.mention if films_channel else "Non configuré", True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`releases enable/disable` - Active/désactive
`releases games #salon [@role]` - Salon jeux
`releases anime #salon [@role]` - Salon anime
`releases series #salon [@role]` - Salon séries
`releases films #salon [@role]` - Salon films
`releases check` - Force une vérification
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @releases.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def releases_enable(self, ctx: commands.Context):
        """Active les annonces de sorties"""
        await db.execute(
            "UPDATE guild_settings SET releases_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Annonces de sorties activées !"))
    
    @releases.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def releases_disable(self, ctx: commands.Context):
        """Désactive les annonces de sorties"""
        await db.execute(
            "UPDATE guild_settings SET releases_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Annonces de sorties désactivées !"))
    
    @releases.command(name="games", aliases=["jeux"])
    @commands.has_permissions(administrator=True)
    async def releases_games(self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role = None):
        """Configure le salon des sorties de jeux"""
        await self.get_config(ctx.guild.id)
        await db.execute(
            "UPDATE releases_config SET games_channel_id = ?, games_role_id = ? WHERE guild_id = ?",
            (channel.id, role.id if role else None, ctx.guild.id)
        )
        
        msg = f"Salon des sorties jeux: {channel.mention}"
        if role:
            msg += f"\nRôle notifié: {role.mention}"
        await ctx.send(embed=success_embed(msg))
    
    @releases.command(name="anime")
    @commands.has_permissions(administrator=True)
    async def releases_anime(self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role = None):
        """Configure le salon des sorties anime"""
        await db.execute(
            "UPDATE releases_config SET anime_channel_id = ?, anime_role_id = ? WHERE guild_id = ?",
            (channel.id, role.id if role else None, ctx.guild.id)
        )
        
        msg = f"Salon des sorties anime: {channel.mention}"
        if role:
            msg += f"\nRôle notifié: {role.mention}"
        await ctx.send(embed=success_embed(msg))
    
    @releases.command(name="series")
    @commands.has_permissions(administrator=True)
    async def releases_series(self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role = None):
        """Configure le salon des sorties séries"""
        await db.execute(
            "UPDATE releases_config SET series_channel_id = ?, series_role_id = ? WHERE guild_id = ?",
            (channel.id, role.id if role else None, ctx.guild.id)
        )
        
        msg = f"Salon des sorties séries: {channel.mention}"
        if role:
            msg += f"\nRôle notifié: {role.mention}"
        await ctx.send(embed=success_embed(msg))
    
    @releases.command(name="films")
    @commands.has_permissions(administrator=True)
    async def releases_films(self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role = None):
        """Configure le salon des sorties films"""
        await db.execute(
            "UPDATE releases_config SET films_channel_id = ?, films_role_id = ? WHERE guild_id = ?",
            (channel.id, role.id if role else None, ctx.guild.id)
        )
        
        msg = f"Salon des sorties films: {channel.mention}"
        if role:
            msg += f"\nRôle notifié: {role.mention}"
        await ctx.send(embed=success_embed(msg))
    
    @releases.command(name="check")
    @commands.has_permissions(administrator=True)
    async def releases_check(self, ctx: commands.Context):
        """Force une vérification des sorties"""
        await ctx.send(embed=info_embed("Vérification en cours..."))
        
        config = await self.get_config(ctx.guild.id)
        
        if config.get("games_channel_id"):
            await self.check_game_releases(ctx.guild, config)
        if config.get("anime_channel_id"):
            await self.check_anime_releases(ctx.guild, config)
        if config.get("series_channel_id"):
            await self.check_series_releases(ctx.guild, config)
        if config.get("films_channel_id"):
            await self.check_film_releases(ctx.guild, config)
        
        await ctx.send(embed=success_embed("Vérification terminée !"))
    
    @releases.command(name="apikey")
    @commands.has_permissions(administrator=True)
    async def releases_apikey(self, ctx: commands.Context, api: str, key: str):
        """Configure une clé API (rawg ou tmdb)
        
        Usage: !releases apikey tmdb YOUR_API_KEY
        """
        api = api.lower()
        
        if api == "tmdb":
            self.tmdb_api_key = key
            await ctx.message.delete()  # Delete message with key
            await ctx.send(embed=success_embed("Clé API TMDB configurée ! (nécessaire pour séries/films)"))
        elif api == "rawg":
            self.rawg_api_key = key
            await ctx.message.delete()
            await ctx.send(embed=success_embed("Clé API RAWG configurée ! (optionnel pour jeux)"))
        else:
            await ctx.send(embed=error_embed("API invalide ! Utilise `tmdb` ou `rawg`."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Releases(bot))
