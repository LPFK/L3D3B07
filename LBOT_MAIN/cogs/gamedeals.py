"""
GameDeals Cog - Annonces de jeux gratuits et promotions (Steam, Epic Games)

Sources:
- Epic Games Store (API gratuite)
- Steam (RSS/API)
- IsThereAnyDeal (optionnel)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import json
import re

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    is_admin
)


class GameDeals(commands.Cog):
    """Annonces de jeux gratuits et promotions"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Cache pour éviter les doublons
        self.announced_deals: set = set()
    
    async def cog_load(self):
        """Initialize session and start tasks"""
        self.session = aiohttp.ClientSession()
        self.check_epic_free_games.start()
        self.check_steam_deals.start()
    
    async def cog_unload(self):
        """Cleanup"""
        self.check_epic_free_games.cancel()
        self.check_steam_deals.cancel()
        if self.session:
            await self.session.close()
    
    async def get_config(self, guild_id: int) -> dict:
        """Get deals config for guild"""
        row = await db.fetchone(
            "SELECT * FROM gamedeals_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO gamedeals_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM gamedeals_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    # ==================== EPIC GAMES FREE GAMES ====================
    
    @tasks.loop(hours=4)
    async def check_epic_free_games(self):
        """Check Epic Games Store for free games"""
        try:
            # Epic Games Store API
            url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
            params = {"locale": "fr", "country": "FR", "allowCountries": "FR"}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return
                
                data = await resp.json()
                games = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
                
                free_games = []
                for game in games:
                    # Check if actually free
                    promotions = game.get("promotions")
                    if not promotions:
                        continue
                    
                    promo_offers = promotions.get("promotionalOffers", [])
                    if not promo_offers:
                        continue
                    
                    for offer_group in promo_offers:
                        for offer in offer_group.get("promotionalOffers", []):
                            discount = offer.get("discountSetting", {}).get("discountPercentage", 0)
                            if discount == 0:  # 100% discount = free
                                end_date = offer.get("endDate")
                                free_games.append({
                                    "game": game,
                                    "end_date": end_date
                                })
                
                # Announce to all configured guilds
                guilds = await db.fetchall(
                    """SELECT gc.*, gs.guild_id FROM gamedeals_config gc
                       JOIN guild_settings gs ON gc.guild_id = gs.guild_id
                       WHERE gs.gamedeals_enabled = 1 AND gc.epic_channel_id IS NOT NULL"""
                )
                
                for guild_config in guilds:
                    guild = self.bot.get_guild(guild_config["guild_id"])
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(guild_config["epic_channel_id"])
                    if not channel:
                        continue
                    
                    for free_game in free_games:
                        await self.announce_epic_game(guild, channel, guild_config, free_game)
                        
        except Exception as e:
            print(f"Error checking Epic free games: {e}")
    
    @check_epic_free_games.before_loop
    async def before_check_epic(self):
        await self.bot.wait_until_ready()
    
    async def announce_epic_game(self, guild: discord.Guild, channel: discord.TextChannel, config: dict, free_game: dict):
        """Announce an Epic free game"""
        game = free_game["game"]
        game_id = game.get("id", "")
        cache_key = f"epic_{guild.id}_{game_id}"
        
        if cache_key in self.announced_deals:
            return
        
        # Check database
        existing = await db.fetchone(
            "SELECT * FROM announced_deals WHERE guild_id = ? AND deal_id = ?",
            (guild.id, f"epic_{game_id}")
        )
        if existing:
            self.announced_deals.add(cache_key)
            return
        
        # Create embed
        embed = discord.Embed(
            title=f"🎁 GRATUIT - {game.get('title', 'Unknown')}",
            description=game.get("description", "")[:500],
            color=discord.Color.gold()
        )
        
        # Get image
        images = game.get("keyImages", [])
        for img in images:
            if img.get("type") in ["OfferImageWide", "DieselStoreFrontWide", "Thumbnail"]:
                embed.set_image(url=img.get("url"))
                break
        
        # Store URL
        slug = game.get("productSlug") or game.get("urlSlug") or game.get("catalogNs", {}).get("mappings", [{}])[0].get("pageSlug", "")
        if slug:
            embed.url = f"https://store.epicgames.com/fr/p/{slug}"
        
        # End date
        end_date = free_game.get("end_date")
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                embed.add_field(
                    name="⏰ Disponible jusqu'au",
                    value=f"<t:{int(end_dt.timestamp())}:F>",
                    inline=True
                )
            except:
                pass
        
        # Original price
        price_info = game.get("price", {}).get("totalPrice", {})
        original = price_info.get("originalPrice", 0)
        if original > 0:
            embed.add_field(
                name="💰 Valeur",
                value=f"~~{original/100:.2f}€~~ → **GRATUIT**",
                inline=True
            )
        
        embed.set_footer(text="Epic Games Store • Offre limitée")
        embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/3/31/Epic_Games_logo.svg/1200px-Epic_Games_logo.svg.png")
        
        # Send
        role_mention = ""
        if config.get("epic_role_id"):
            role = guild.get_role(config["epic_role_id"])
            if role:
                role_mention = role.mention
        
        try:
            await channel.send(content=role_mention or None, embed=embed)
            
            await db.execute(
                "INSERT INTO announced_deals (guild_id, deal_id, platform, announced_at) VALUES (?, ?, 'epic', ?)",
                (guild.id, f"epic_{game_id}", time.time())
            )
            self.announced_deals.add(cache_key)
        except Exception as e:
            print(f"Error announcing Epic game: {e}")
    
    # ==================== STEAM DEALS ====================
    
    @tasks.loop(hours=6)
    async def check_steam_deals(self):
        """Check Steam for free games and major deals"""
        try:
            # Use Steam's unofficial API for deals
            # Get featured games (includes free promotions)
            url = "https://store.steampowered.com/api/featured/"
            
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return
                
                data = await resp.json()
            
            # Also check for free games specifically
            free_url = "https://store.steampowered.com/search/results/"
            free_params = {
                "maxprice": "free",
                "specials": 1,
                "json": 1
            }
            
            free_games = []
            
            # Check featured specials
            specials = data.get("specials", {}).get("items", [])
            for game in specials:
                discount = game.get("discount_percent", 0)
                if discount >= 75:  # Only announce 75%+ discounts
                    free_games.append({
                        "type": "deal",
                        "game": game,
                        "discount": discount
                    })
            
            # Check for completely free games
            large_caps = data.get("large_capsules", [])
            for game in large_caps:
                if game.get("discount_percent") == 100 or game.get("final_price") == 0:
                    free_games.append({
                        "type": "free",
                        "game": game,
                        "discount": 100
                    })
            
            # Announce to configured guilds
            guilds = await db.fetchall(
                """SELECT gc.*, gs.guild_id FROM gamedeals_config gc
                   JOIN guild_settings gs ON gc.guild_id = gs.guild_id
                   WHERE gs.gamedeals_enabled = 1 AND gc.steam_channel_id IS NOT NULL"""
            )
            
            for guild_config in guilds:
                guild = self.bot.get_guild(guild_config["guild_id"])
                if not guild:
                    continue
                
                channel = guild.get_channel(guild_config["steam_channel_id"])
                if not channel:
                    continue
                
                min_discount = guild_config.get("steam_min_discount") or 75
                
                for deal in free_games:
                    if deal["discount"] >= min_discount:
                        await self.announce_steam_deal(guild, channel, guild_config, deal)
                        
        except Exception as e:
            print(f"Error checking Steam deals: {e}")
    
    @check_steam_deals.before_loop
    async def before_check_steam(self):
        await self.bot.wait_until_ready()
    
    async def announce_steam_deal(self, guild: discord.Guild, channel: discord.TextChannel, config: dict, deal: dict):
        """Announce a Steam deal"""
        game = deal["game"]
        game_id = str(game.get("id", ""))
        discount = deal["discount"]
        cache_key = f"steam_{guild.id}_{game_id}_{discount}"
        
        if cache_key in self.announced_deals:
            return
        
        existing = await db.fetchone(
            "SELECT * FROM announced_deals WHERE guild_id = ? AND deal_id = ?",
            (guild.id, f"steam_{game_id}_{discount}")
        )
        if existing:
            self.announced_deals.add(cache_key)
            return
        
        # Create embed
        is_free = discount == 100 or game.get("final_price") == 0
        
        if is_free:
            embed = discord.Embed(
                title=f"🎁 GRATUIT - {game.get('name', 'Unknown')}",
                color=discord.Color.gold()
            )
        else:
            embed = discord.Embed(
                title=f"🔥 -{discount}% - {game.get('name', 'Unknown')}",
                color=discord.Color.blue()
            )
        
        # Image
        if game.get("large_capsule_image"):
            embed.set_image(url=game["large_capsule_image"])
        elif game.get("header_image"):
            embed.set_image(url=game["header_image"])
        
        # URL
        if game_id:
            embed.url = f"https://store.steampowered.com/app/{game_id}"
        
        # Price info
        original = game.get("original_price", 0)
        final = game.get("final_price", 0)
        
        if original > 0:
            original_str = f"{original/100:.2f}€"
            final_str = "GRATUIT" if final == 0 else f"{final/100:.2f}€"
            embed.add_field(
                name="💰 Prix",
                value=f"~~{original_str}~~ → **{final_str}**",
                inline=True
            )
        
        embed.add_field(name="🏷️ Réduction", value=f"-{discount}%", inline=True)
        
        # Discount end
        discount_expiry = game.get("discount_expiration")
        if discount_expiry:
            embed.add_field(
                name="⏰ Fin de l'offre",
                value=f"<t:{discount_expiry}:R>",
                inline=True
            )
        
        embed.set_footer(text="Steam")
        embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/thumb/8/83/Steam_icon_logo.svg/2048px-Steam_icon_logo.svg.png")
        
        # Send
        role_mention = ""
        if config.get("steam_role_id"):
            role = guild.get_role(config["steam_role_id"])
            if role:
                role_mention = role.mention
        
        try:
            await channel.send(content=role_mention or None, embed=embed)
            
            await db.execute(
                "INSERT INTO announced_deals (guild_id, deal_id, platform, announced_at) VALUES (?, ?, 'steam', ?)",
                (guild.id, f"steam_{game_id}_{discount}", time.time())
            )
            self.announced_deals.add(cache_key)
        except Exception as e:
            print(f"Error announcing Steam deal: {e}")
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="deals", aliases=["gamedeals", "freegames"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def deals(self, ctx: commands.Context):
        """Configure les annonces de deals/jeux gratuits"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT gamedeals_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        epic_channel = ctx.guild.get_channel(config.get("epic_channel_id"))
        steam_channel = ctx.guild.get_channel(config.get("steam_channel_id"))
        
        embed = create_embed(
            title="🎮 Configuration des deals",
            color=discord.Color.gold(),
            fields=[
                ("État", "✅ Activé" if settings and settings["gamedeals_enabled"] else "❌ Désactivé", True),
                ("🟣 Epic Games", epic_channel.mention if epic_channel else "Non configuré", True),
                ("🔵 Steam", steam_channel.mention if steam_channel else "Non configuré", True),
                ("Steam min. réduction", f"{config.get('steam_min_discount') or 75}%", True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`deals enable/disable` - Active/désactive
`deals epic #salon [@role]` - Salon Epic Games
`deals steam #salon [@role]` - Salon Steam
`deals steammin <pourcentage>` - Réduction min. Steam
`deals check` - Force une vérification
`deals free` - Affiche les jeux gratuits actuels
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @deals.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def deals_enable(self, ctx: commands.Context):
        """Active les annonces de deals"""
        await db.execute(
            "UPDATE guild_settings SET gamedeals_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Annonces de deals activées !"))
    
    @deals.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def deals_disable(self, ctx: commands.Context):
        """Désactive les annonces de deals"""
        await db.execute(
            "UPDATE guild_settings SET gamedeals_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Annonces de deals désactivées !"))
    
    @deals.command(name="epic")
    @commands.has_permissions(administrator=True)
    async def deals_epic(self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role = None):
        """Configure le salon Epic Games"""
        await self.get_config(ctx.guild.id)
        await db.execute(
            "UPDATE gamedeals_config SET epic_channel_id = ?, epic_role_id = ? WHERE guild_id = ?",
            (channel.id, role.id if role else None, ctx.guild.id)
        )
        
        msg = f"Salon Epic Games: {channel.mention}"
        if role:
            msg += f"\nRôle notifié: {role.mention}"
        await ctx.send(embed=success_embed(msg))
    
    @deals.command(name="steam")
    @commands.has_permissions(administrator=True)
    async def deals_steam(self, ctx: commands.Context, channel: discord.TextChannel, role: discord.Role = None):
        """Configure le salon Steam"""
        await db.execute(
            "UPDATE gamedeals_config SET steam_channel_id = ?, steam_role_id = ? WHERE guild_id = ?",
            (channel.id, role.id if role else None, ctx.guild.id)
        )
        
        msg = f"Salon Steam: {channel.mention}"
        if role:
            msg += f"\nRôle notifié: {role.mention}"
        await ctx.send(embed=success_embed(msg))
    
    @deals.command(name="steammin")
    @commands.has_permissions(administrator=True)
    async def deals_steammin(self, ctx: commands.Context, percentage: int):
        """Définit la réduction minimum pour annoncer (Steam)"""
        if percentage < 50 or percentage > 100:
            return await ctx.send(embed=error_embed("Le pourcentage doit être entre 50 et 100 !"))
        
        await db.execute(
            "UPDATE gamedeals_config SET steam_min_discount = ? WHERE guild_id = ?",
            (percentage, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Réduction minimum Steam: {percentage}%"))
    
    @deals.command(name="check")
    @commands.has_permissions(administrator=True)
    async def deals_check(self, ctx: commands.Context):
        """Force une vérification des deals"""
        await ctx.send(embed=info_embed("Vérification en cours..."))
        
        # Trigger checks manually
        await self.check_epic_free_games()
        await self.check_steam_deals()
        
        await ctx.send(embed=success_embed("Vérification terminée !"))
    
    @deals.command(name="free", aliases=["gratuit"])
    async def deals_free(self, ctx: commands.Context):
        """Affiche les jeux gratuits actuels"""
        await ctx.typing()
        
        embed = discord.Embed(
            title="🎁 Jeux gratuits actuels",
            color=discord.Color.gold()
        )
        
        # Epic Games
        try:
            url = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
            params = {"locale": "fr", "country": "FR", "allowCountries": "FR"}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    games = data.get("data", {}).get("Catalog", {}).get("searchStore", {}).get("elements", [])
                    
                    epic_games = []
                    for game in games:
                        promotions = game.get("promotions")
                        if not promotions:
                            continue
                        
                        promo_offers = promotions.get("promotionalOffers", [])
                        if promo_offers:
                            for offer_group in promo_offers:
                                for offer in offer_group.get("promotionalOffers", []):
                                    if offer.get("discountSetting", {}).get("discountPercentage") == 0:
                                        end_date = offer.get("endDate", "")
                                        epic_games.append(f"• **{game.get('title')}**")
                                        if end_date:
                                            try:
                                                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                                                epic_games[-1] += f" (jusqu'au <t:{int(end_dt.timestamp())}:d>)"
                                            except:
                                                pass
                    
                    if epic_games:
                        embed.add_field(
                            name="🟣 Epic Games Store",
                            value="\n".join(epic_games[:5]),
                            inline=False
                        )
                    else:
                        embed.add_field(
                            name="🟣 Epic Games Store",
                            value="Aucun jeu gratuit actuellement",
                            inline=False
                        )
        except:
            embed.add_field(
                name="🟣 Epic Games Store",
                value="Impossible de récupérer les données",
                inline=False
            )
        
        embed.set_footer(text="Utilisez les liens pour réclamer les jeux !")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GameDeals(bot))
