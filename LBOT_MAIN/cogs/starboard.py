"""
Starboard Cog - Système de mise en avant des messages populaires
"""

import discord
from discord.ext import commands
from discord import app_commands
import time
from typing import Optional

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    is_admin
)


class Starboard(commands.Cog):
    """Système de starboard"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.star_emoji = "⭐"
    
    async def get_config(self, guild_id: int) -> dict:
        """Get starboard config"""
        row = await db.fetchone(
            "SELECT * FROM starboard_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO starboard_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM starboard_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handle reaction add for starboard"""
        if not payload.guild_id:
            return
        
        # Check if starboard is enabled
        settings = await db.fetchone(
            "SELECT starboard_enabled FROM guild_settings WHERE guild_id = ?",
            (payload.guild_id,)
        )
        if not settings or not settings["starboard_enabled"]:
            return
        
        config = await self.get_config(payload.guild_id)
        
        # Check emoji
        emoji = str(payload.emoji)
        required_emoji = config.get("emoji") or self.star_emoji
        if emoji != required_emoji:
            return
        
        # Check if starboard channel is configured
        if not config.get("channel_id"):
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        # Ignore starboard channel itself
        if channel.id == config["channel_id"]:
            return
        
        # Check if channel is ignored
        ignored_channels = config.get("ignored_channels")
        if ignored_channels:
            ignored_list = [int(c) for c in ignored_channels.split(",") if c]
            if channel.id in ignored_list:
                return
        
        # Get the message
        try:
            message = await channel.fetch_message(payload.message_id)
        except:
            return
        
        # Don't star bot messages (optional)
        if config.get("ignore_bots") and message.author.bot:
            return
        
        # Self-star check
        if not config.get("self_star") and payload.user_id == message.author.id:
            return
        
        # Count stars
        star_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == required_emoji:
                star_count = reaction.count
                # Remove self-star from count if needed
                if not config.get("self_star"):
                    users = [u async for u in reaction.users()]
                    if message.author in users:
                        star_count -= 1
                break
        
        threshold = config.get("threshold") or 3
        
        if star_count >= threshold:
            await self.add_to_starboard(message, star_count, config)
        else:
            # Update existing starboard message if exists
            await self.update_starboard_message(message, star_count, config)
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Handle reaction remove for starboard"""
        if not payload.guild_id:
            return
        
        settings = await db.fetchone(
            "SELECT starboard_enabled FROM guild_settings WHERE guild_id = ?",
            (payload.guild_id,)
        )
        if not settings or not settings["starboard_enabled"]:
            return
        
        config = await self.get_config(payload.guild_id)
        
        emoji = str(payload.emoji)
        required_emoji = config.get("emoji") or self.star_emoji
        if emoji != required_emoji:
            return
        
        if not config.get("channel_id"):
            return
        
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        try:
            message = await channel.fetch_message(payload.message_id)
        except:
            return
        
        # Count stars
        star_count = 0
        for reaction in message.reactions:
            if str(reaction.emoji) == required_emoji:
                star_count = reaction.count
                if not config.get("self_star"):
                    users = [u async for u in reaction.users()]
                    if message.author in users:
                        star_count -= 1
                break
        
        threshold = config.get("threshold") or 3
        
        if star_count < threshold:
            # Remove from starboard if below threshold
            await self.remove_from_starboard(message, config)
        else:
            # Update count
            await self.update_starboard_message(message, star_count, config)
    
    async def add_to_starboard(self, message: discord.Message, star_count: int, config: dict):
        """Add or update a message in the starboard"""
        guild = message.guild
        starboard_channel = guild.get_channel(config["channel_id"])
        
        if not starboard_channel:
            return
        
        # Check if already in starboard
        existing = await db.fetchone(
            "SELECT * FROM starboard_messages WHERE original_message_id = ?",
            (message.id,)
        )
        
        emoji = config.get("emoji") or self.star_emoji
        
        if existing:
            # Update existing
            await self.update_starboard_message(message, star_count, config)
        else:
            # Create new starboard entry
            embed = self.create_starboard_embed(message, star_count, emoji)
            
            try:
                starboard_msg = await starboard_channel.send(embed=embed)
                
                await db.execute(
                    """INSERT INTO starboard_messages 
                       (guild_id, channel_id, original_message_id, starboard_message_id, star_count, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (guild.id, message.channel.id, message.id, starboard_msg.id, star_count, time.time())
                )
            except discord.Forbidden:
                pass
    
    async def update_starboard_message(self, message: discord.Message, star_count: int, config: dict):
        """Update an existing starboard message"""
        existing = await db.fetchone(
            "SELECT * FROM starboard_messages WHERE original_message_id = ?",
            (message.id,)
        )
        
        if not existing:
            return
        
        guild = message.guild
        starboard_channel = guild.get_channel(config["channel_id"])
        
        if not starboard_channel:
            return
        
        try:
            starboard_msg = await starboard_channel.fetch_message(existing["starboard_message_id"])
            
            emoji = config.get("emoji") or self.star_emoji
            embed = self.create_starboard_embed(message, star_count, emoji)
            
            await starboard_msg.edit(embed=embed)
            
            await db.execute(
                "UPDATE starboard_messages SET star_count = ? WHERE original_message_id = ?",
                (star_count, message.id)
            )
        except:
            pass
    
    async def remove_from_starboard(self, message: discord.Message, config: dict):
        """Remove a message from starboard"""
        existing = await db.fetchone(
            "SELECT * FROM starboard_messages WHERE original_message_id = ?",
            (message.id,)
        )
        
        if not existing:
            return
        
        guild = message.guild
        starboard_channel = guild.get_channel(config["channel_id"])
        
        if starboard_channel:
            try:
                starboard_msg = await starboard_channel.fetch_message(existing["starboard_message_id"])
                await starboard_msg.delete()
            except:
                pass
        
        await db.execute(
            "DELETE FROM starboard_messages WHERE original_message_id = ?",
            (message.id,)
        )
    
    def create_starboard_embed(self, message: discord.Message, star_count: int, emoji: str) -> discord.Embed:
        """Create the starboard embed"""
        embed = discord.Embed(
            description=message.content[:2048] if message.content else None,
            color=discord.Color.gold(),
            timestamp=message.created_at
        )
        
        embed.set_author(
            name=message.author.display_name,
            icon_url=message.author.display_avatar.url
        )
        
        # Add image if present
        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith("image"):
                embed.set_image(url=attachment.url)
        
        # Check for embeds with images
        if message.embeds:
            for msg_embed in message.embeds:
                if msg_embed.image:
                    embed.set_image(url=msg_embed.image.url)
                    break
                elif msg_embed.thumbnail:
                    embed.set_image(url=msg_embed.thumbnail.url)
                    break
        
        embed.add_field(
            name="Source",
            value=f"[Aller au message]({message.jump_url})",
            inline=True
        )
        
        embed.set_footer(text=f"{emoji} {star_count} | #{message.channel.name}")
        
        return embed
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="starboard", aliases=["sb"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def starboard(self, ctx: commands.Context):
        """Configure le starboard"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT starboard_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        channel = ctx.guild.get_channel(config.get("channel_id"))
        emoji = config.get("emoji") or self.star_emoji
        
        # Get stats
        stats = await db.fetchone(
            "SELECT COUNT(*) as count, SUM(star_count) as total_stars FROM starboard_messages WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        embed = create_embed(
            title="⭐ Configuration du Starboard",
            color=discord.Color.gold(),
            fields=[
                ("État", "✅ Activé" if settings and settings["starboard_enabled"] else "❌ Désactivé", True),
                ("Salon", channel.mention if channel else "Non configuré", True),
                ("Emoji", emoji, True),
                ("Seuil", str(config.get("threshold") or 3) + " réactions", True),
                ("Self-star", "✅ Oui" if config.get("self_star") else "❌ Non", True),
                ("Ignorer bots", "✅ Oui" if config.get("ignore_bots") else "❌ Non", True),
                ("Messages starred", str(stats["count"] or 0), True),
                ("Total étoiles", str(stats["total_stars"] or 0), True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`starboard enable/disable` - Active/désactive
`starboard channel #salon` - Définit le salon
`starboard threshold <nombre>` - Seuil minimum
`starboard emoji <emoji>` - Change l'emoji
`starboard selfstar on/off` - Self-star
`starboard ignorebots on/off` - Ignorer les bots
`starboard ignore #salon` - Ignore un salon
`starboard random` - Message aléatoire
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @starboard.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def starboard_enable(self, ctx: commands.Context):
        """Active le starboard"""
        await db.execute(
            "UPDATE guild_settings SET starboard_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Starboard activé !"))
    
    @starboard.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def starboard_disable(self, ctx: commands.Context):
        """Désactive le starboard"""
        await db.execute(
            "UPDATE guild_settings SET starboard_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Starboard désactivé !"))
    
    @starboard.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def starboard_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon du starboard"""
        await self.get_config(ctx.guild.id)  # Ensure config exists
        await db.execute(
            "UPDATE starboard_config SET channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon starboard: {channel.mention}"))
    
    @starboard.command(name="threshold")
    @commands.has_permissions(administrator=True)
    async def starboard_threshold(self, ctx: commands.Context, threshold: int):
        """Définit le nombre minimum de réactions"""
        if threshold < 1 or threshold > 100:
            return await ctx.send(embed=error_embed("Le seuil doit être entre 1 et 100 !"))
        
        await db.execute(
            "UPDATE starboard_config SET threshold = ? WHERE guild_id = ?",
            (threshold, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Seuil défini à {threshold} réactions !"))
    
    @starboard.command(name="emoji")
    @commands.has_permissions(administrator=True)
    async def starboard_emoji(self, ctx: commands.Context, emoji: str):
        """Change l'emoji du starboard"""
        # Validate emoji
        try:
            await ctx.message.add_reaction(emoji)
            await ctx.message.remove_reaction(emoji, ctx.me)
        except:
            return await ctx.send(embed=error_embed("Emoji invalide !"))
        
        await db.execute(
            "UPDATE starboard_config SET emoji = ? WHERE guild_id = ?",
            (emoji, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Emoji changé en {emoji} !"))
    
    @starboard.command(name="selfstar")
    @commands.has_permissions(administrator=True)
    async def starboard_selfstar(self, ctx: commands.Context, toggle: str):
        """Active/désactive le self-star"""
        if toggle.lower() in ["on", "yes", "oui", "true", "1"]:
            value = 1
        elif toggle.lower() in ["off", "no", "non", "false", "0"]:
            value = 0
        else:
            return await ctx.send(embed=error_embed("Utilise `on` ou `off` !"))
        
        await db.execute(
            "UPDATE starboard_config SET self_star = ? WHERE guild_id = ?",
            (value, ctx.guild.id)
        )
        
        status = "activé" if value else "désactivé"
        await ctx.send(embed=success_embed(f"Self-star {status} !"))
    
    @starboard.command(name="ignorebots")
    @commands.has_permissions(administrator=True)
    async def starboard_ignorebots(self, ctx: commands.Context, toggle: str):
        """Active/désactive l'ignorance des bots"""
        if toggle.lower() in ["on", "yes", "oui", "true", "1"]:
            value = 1
        elif toggle.lower() in ["off", "no", "non", "false", "0"]:
            value = 0
        else:
            return await ctx.send(embed=error_embed("Utilise `on` ou `off` !"))
        
        await db.execute(
            "UPDATE starboard_config SET ignore_bots = ? WHERE guild_id = ?",
            (value, ctx.guild.id)
        )
        
        status = "ignorés" if value else "inclus"
        await ctx.send(embed=success_embed(f"Messages de bots {status} !"))
    
    @starboard.command(name="ignore")
    @commands.has_permissions(administrator=True)
    async def starboard_ignore(self, ctx: commands.Context, channel: discord.TextChannel):
        """Ignore/réactive un salon pour le starboard"""
        config = await self.get_config(ctx.guild.id)
        
        ignored = config.get("ignored_channels") or ""
        ignored_list = [c for c in ignored.split(",") if c]
        
        channel_str = str(channel.id)
        
        if channel_str in ignored_list:
            ignored_list.remove(channel_str)
            await ctx.send(embed=success_embed(f"{channel.mention} n'est plus ignoré !"))
        else:
            ignored_list.append(channel_str)
            await ctx.send(embed=success_embed(f"{channel.mention} est maintenant ignoré !"))
        
        await db.execute(
            "UPDATE starboard_config SET ignored_channels = ? WHERE guild_id = ?",
            (",".join(ignored_list), ctx.guild.id)
        )
    
    @starboard.command(name="random")
    async def starboard_random(self, ctx: commands.Context):
        """Affiche un message aléatoire du starboard"""
        starred = await db.fetchone(
            """SELECT * FROM starboard_messages 
               WHERE guild_id = ? 
               ORDER BY RANDOM() LIMIT 1""",
            (ctx.guild.id,)
        )
        
        if not starred:
            return await ctx.send(embed=info_embed("Aucun message dans le starboard !"))
        
        channel = ctx.guild.get_channel(starred["channel_id"])
        if not channel:
            return await ctx.send(embed=error_embed("Salon original introuvable !"))
        
        try:
            message = await channel.fetch_message(starred["original_message_id"])
            config = await self.get_config(ctx.guild.id)
            emoji = config.get("emoji") or self.star_emoji
            
            embed = self.create_starboard_embed(message, starred["star_count"], emoji)
            await ctx.send(embed=embed)
        except:
            await ctx.send(embed=error_embed("Message introuvable !"))
    
    @starboard.command(name="stats")
    async def starboard_stats(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche les stats du starboard"""
        member = member or ctx.author
        
        # User stats
        user_starred = await db.fetchall(
            """SELECT sm.* FROM starboard_messages sm
               JOIN (SELECT original_message_id FROM starboard_messages WHERE guild_id = ?) as sub
               ON sm.original_message_id = sub.original_message_id
               WHERE sm.guild_id = ?""",
            (ctx.guild.id, ctx.guild.id)
        )
        
        # This is a simplified approach - would need message author tracking in a production bot
        embed = create_embed(
            title=f"⭐ Stats Starboard",
            color=discord.Color.gold(),
            fields=[
                ("Total messages", str(len(user_starred)), True),
            ]
        )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Starboard(bot))
