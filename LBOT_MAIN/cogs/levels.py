"""
Levels Cog - XP system, leveling, rewards, leaderboard, rank cards
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import json
import random
from io import BytesIO
from typing import Optional

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    xp_for_level, level_from_xp, xp_progress, progress_bar,
    format_message, Paginator, is_admin, chunk_list
)

# Try to import PIL for rank cards
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class Levels(commands.Cog):
    """Système de niveaux et d'XP"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.xp_cooldowns: dict[tuple[int, int], float] = {}  # (guild_id, user_id) -> timestamp
        self.voice_tracking: dict[tuple[int, int], float] = {}  # (guild_id, user_id) -> join_time
    
    async def cog_load(self):
        """Start background tasks"""
        self.voice_xp_task.start()
    
    async def cog_unload(self):
        """Stop background tasks"""
        self.voice_xp_task.cancel()
    
    async def get_config(self, guild_id: int) -> dict:
        """Get level config for a guild"""
        row = await db.fetchone(
            "SELECT * FROM levels_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        # Create default config
        await db.execute(
            "INSERT OR IGNORE INTO levels_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM levels_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    async def get_user_data(self, guild_id: int, user_id: int) -> dict:
        """Get user level data"""
        row = await db.fetchone(
            "SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        if row:
            return dict(row)
        
        # Create new user entry
        await db.execute(
            "INSERT OR IGNORE INTO user_levels (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id)
        )
        return {
            "guild_id": guild_id, "user_id": user_id,
            "xp": 0, "level": 0, "total_messages": 0,
            "voice_time": 0, "last_xp_time": 0
        }
    
    async def add_xp(self, member: discord.Member, amount: int) -> Optional[int]:
        """Add XP to a user, returns new level if leveled up"""
        config = await self.get_config(member.guild.id)
        user_data = await self.get_user_data(member.guild.id, member.id)
        
        old_level = user_data["level"]
        new_xp = user_data["xp"] + amount
        new_level = level_from_xp(new_xp)
        
        # Check max level
        max_level = config.get("max_level", 0)
        if max_level > 0 and new_level > max_level:
            new_level = max_level
            new_xp = xp_for_level(max_level)
        
        await db.execute(
            """UPDATE user_levels 
               SET xp = ?, level = ?, total_messages = total_messages + 1, last_xp_time = ?
               WHERE guild_id = ? AND user_id = ?""",
            (new_xp, new_level, time.time(), member.guild.id, member.id)
        )
        
        if new_level > old_level:
            return new_level
        return None
    
    async def check_rewards(self, member: discord.Member, level: int):
        """Give level rewards"""
        rewards = await db.fetchall(
            "SELECT * FROM level_rewards WHERE guild_id = ? AND level <= ? ORDER BY level",
            (member.guild.id, level)
        )
        
        roles_to_add = []
        roles_to_remove = []
        
        for reward in rewards:
            role = member.guild.get_role(reward["role_id"])
            if role:
                if reward["level"] == level:
                    roles_to_add.append(role)
                elif reward["remove_previous"]:
                    roles_to_remove.append(role)
        
        try:
            if roles_to_add:
                await member.add_roles(*roles_to_add, reason="Level reward")
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Level reward replaced")
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Handle XP gain from messages"""
        if message.author.bot or not message.guild:
            return
        
        # Check if guild has levels enabled
        settings = await db.fetchone(
            "SELECT levels_enabled FROM guild_settings WHERE guild_id = ?",
            (message.guild.id,)
        )
        if not settings or not settings["levels_enabled"]:
            return
        
        config = await self.get_config(message.guild.id)
        
        # Check ignored channels
        ignored_channels = json.loads(config.get("ignored_channels", "[]"))
        if message.channel.id in ignored_channels:
            return
        
        # Check ignored roles
        ignored_roles = json.loads(config.get("ignored_roles", "[]"))
        if any(role.id in ignored_roles for role in message.author.roles):
            return
        
        # Check cooldown
        key = (message.guild.id, message.author.id)
        cooldown = config.get("xp_cooldown", 60)
        if key in self.xp_cooldowns:
            if time.time() - self.xp_cooldowns[key] < cooldown:
                return
        
        self.xp_cooldowns[key] = time.time()
        
        # Calculate XP with boosters
        base_xp = config.get("xp_per_message", 15)
        booster_roles = json.loads(config.get("booster_roles", "{}"))
        
        multiplier = 1.0
        for role in message.author.roles:
            if str(role.id) in booster_roles:
                multiplier = max(multiplier, booster_roles[str(role.id)])
        
        xp_amount = int(base_xp * multiplier * random.uniform(0.8, 1.2))
        
        # Add XP and check for level up
        new_level = await self.add_xp(message.author, xp_amount)
        
        if new_level:
            await self.check_rewards(message.author, new_level)
            
            # Send level up message
            channel_id = config.get("level_up_channel_id")
            channel = message.guild.get_channel(channel_id) if channel_id else message.channel
            
            if channel:
                level_msg = format_message(
                    config.get("level_up_message", "GG {user} ! Niveau **{level}** ! 🎉"),
                    user=message.author.mention,
                    level=new_level
                )
                
                color = discord.Color.from_str(config.get("color", "#5865F2"))
                embed = create_embed(
                    title="🎉 Level Up!",
                    description=level_msg,
                    color=color
                )
                
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """Track voice channel time for XP"""
        if member.bot:
            return
        
        key = (member.guild.id, member.id)
        
        # User joined voice
        if before.channel is None and after.channel is not None:
            self.voice_tracking[key] = time.time()
        
        # User left voice
        elif before.channel is not None and after.channel is None:
            if key in self.voice_tracking:
                del self.voice_tracking[key]
    
    @tasks.loop(minutes=1)
    async def voice_xp_task(self):
        """Give XP for voice channel time"""
        for (guild_id, user_id), join_time in list(self.voice_tracking.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            member = guild.get_member(user_id)
            if not member or not member.voice or not member.voice.channel:
                del self.voice_tracking[(guild_id, user_id)]
                continue
            
            # Don't give XP if alone or muted/deafened
            voice_members = [m for m in member.voice.channel.members if not m.bot]
            if len(voice_members) < 2 or member.voice.self_mute or member.voice.self_deaf:
                continue
            
            config = await self.get_config(guild_id)
            xp_per_min = config.get("xp_voice_per_minute", 5)
            
            if xp_per_min > 0:
                await self.add_xp(member, xp_per_min)
                
                # Update voice time
                await db.execute(
                    "UPDATE user_levels SET voice_time = voice_time + 60 WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id)
                )
    
    @voice_xp_task.before_loop
    async def before_voice_xp(self):
        await self.bot.wait_until_ready()
    
    # ==================== COMMANDS ====================
    
    @commands.hybrid_command(name="rank", aliases=["niveau", "level"])
    @app_commands.describe(member="Le membre dont tu veux voir le niveau")
    async def rank(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche ton niveau et ton XP"""
        member = member or ctx.author
        
        if member.bot:
            return await ctx.send(embed=error_embed("Les bots n'ont pas de niveau !"))
        
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, member.id)
        
        # Get rank
        rank_row = await db.fetchone(
            """SELECT COUNT(*) + 1 as rank FROM user_levels 
               WHERE guild_id = ? AND xp > (SELECT xp FROM user_levels WHERE guild_id = ? AND user_id = ?)""",
            (ctx.guild.id, ctx.guild.id, member.id)
        )
        rank = rank_row["rank"] if rank_row else 1
        
        level = user_data["level"]
        xp = user_data["xp"]
        current_xp, needed_xp = xp_progress(xp, level)
        
        color = discord.Color.from_str(config.get("color", "#5865F2"))
        bar = progress_bar(current_xp, needed_xp, 15)
        
        embed = create_embed(
            title=f"Niveau de {member.display_name}",
            color=color,
            thumbnail=member.display_avatar.url
        )
        embed.add_field(name="Rang", value=f"#{rank}", inline=True)
        embed.add_field(name="Niveau", value=str(level), inline=True)
        embed.add_field(name="XP Total", value=f"{xp:,}", inline=True)
        embed.add_field(
            name="Progression",
            value=f"{bar}\n{current_xp:,} / {needed_xp:,} XP",
            inline=False
        )
        embed.add_field(name="Messages", value=f"{user_data['total_messages']:,}", inline=True)
        embed.add_field(name="Temps vocal", value=f"{user_data['voice_time'] // 60} min", inline=True)
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="leaderboard", aliases=["lb", "top", "classement"])
    @app_commands.describe(page="Numéro de page")
    async def leaderboard(self, ctx: commands.Context, page: int = 1):
        """Affiche le classement des niveaux"""
        per_page = 10
        offset = (page - 1) * per_page
        
        rows = await db.fetchall(
            """SELECT user_id, xp, level FROM user_levels 
               WHERE guild_id = ? ORDER BY xp DESC LIMIT ? OFFSET ?""",
            (ctx.guild.id, per_page, offset)
        )
        
        total = await db.fetchone(
            "SELECT COUNT(*) as count FROM user_levels WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        total_pages = (total["count"] // per_page) + 1
        
        if not rows:
            return await ctx.send(embed=info_embed("Aucun membre dans le classement !"))
        
        config = await self.get_config(ctx.guild.id)
        color = discord.Color.from_str(config.get("color", "#5865F2"))
        
        description = ""
        for i, row in enumerate(rows, start=offset + 1):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else f"Utilisateur inconnu"
            
            medal = ""
            if i == 1: medal = "🥇 "
            elif i == 2: medal = "🥈 "
            elif i == 3: medal = "🥉 "
            
            description += f"{medal}**#{i}** {name}\n"
            description += f"└ Niveau {row['level']} • {row['xp']:,} XP\n\n"
        
        embed = create_embed(
            title=f"🏆 Classement de {ctx.guild.name}",
            description=description,
            color=color,
            footer=f"Page {page}/{total_pages}"
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="rewards", aliases=["recompenses"])
    async def rewards(self, ctx: commands.Context):
        """Affiche les récompenses de niveau"""
        rows = await db.fetchall(
            "SELECT * FROM level_rewards WHERE guild_id = ? ORDER BY level",
            (ctx.guild.id,)
        )
        
        if not rows:
            return await ctx.send(embed=info_embed("Aucune récompense configurée !"))
        
        config = await self.get_config(ctx.guild.id)
        color = discord.Color.from_str(config.get("color", "#5865F2"))
        
        description = ""
        for row in rows:
            role = ctx.guild.get_role(row["role_id"])
            role_name = role.mention if role else "Rôle supprimé"
            description += f"**Niveau {row['level']}** → {role_name}\n"
        
        embed = create_embed(
            title="🎁 Récompenses de niveau",
            description=description,
            color=color
        )
        
        await ctx.send(embed=embed)
    
    # ==================== ADMIN COMMANDS ====================
    
    @commands.group(name="leveladmin", aliases=["la"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def leveladmin(self, ctx: commands.Context):
        """Commandes d'administration des niveaux"""
        embed = create_embed(
            title="⚙️ Administration des niveaux",
            description="Commandes disponibles :",
            fields=[
                ("Récompenses", "`leveladmin reward add <niveau> <@role>`\n`leveladmin reward remove <niveau>`", False),
                ("XP", "`leveladmin setxp <@membre> <xp>`\n`leveladmin addxp <@membre> <xp>`\n`leveladmin resetuser <@membre>`", False),
                ("Config", "`leveladmin xppermsg <montant>`\n`leveladmin cooldown <secondes>`\n`leveladmin channel <#salon>`\n`leveladmin message <message>`", False),
                ("Boosters", "`leveladmin booster add <@role> <multiplicateur>`\n`leveladmin booster remove <@role>`", False),
            ]
        )
        await ctx.send(embed=embed)
    
    @leveladmin.group(name="reward", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def level_reward(self, ctx: commands.Context):
        """Gère les récompenses de niveau"""
        await ctx.invoke(self.rewards)
    
    @level_reward.command(name="add")
    @commands.has_permissions(administrator=True)
    async def reward_add(self, ctx: commands.Context, level: int, role: discord.Role):
        """Ajoute une récompense de niveau"""
        await db.execute(
            "INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id) VALUES (?, ?, ?)",
            (ctx.guild.id, level, role.id)
        )
        await ctx.send(embed=success_embed(
            f"Le rôle {role.mention} sera donné au niveau **{level}** !"
        ))
    
    @level_reward.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def reward_remove(self, ctx: commands.Context, level: int):
        """Supprime une récompense de niveau"""
        await db.execute(
            "DELETE FROM level_rewards WHERE guild_id = ? AND level = ?",
            (ctx.guild.id, level)
        )
        await ctx.send(embed=success_embed(f"Récompense du niveau {level} supprimée !"))
    
    @leveladmin.command(name="setxp")
    @commands.has_permissions(administrator=True)
    async def setxp(self, ctx: commands.Context, member: discord.Member, xp: int):
        """Définit l'XP d'un membre"""
        level = level_from_xp(xp)
        await db.execute(
            """INSERT INTO user_levels (guild_id, user_id, xp, level) VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?""",
            (ctx.guild.id, member.id, xp, level, xp, level)
        )
        await ctx.send(embed=success_embed(
            f"XP de {member.mention} défini à **{xp:,}** (niveau {level})"
        ))
    
    @leveladmin.command(name="addxp")
    @commands.has_permissions(administrator=True)
    async def addxp_cmd(self, ctx: commands.Context, member: discord.Member, xp: int):
        """Ajoute de l'XP à un membre"""
        new_level = await self.add_xp(member, xp)
        user_data = await self.get_user_data(ctx.guild.id, member.id)
        
        msg = f"**{xp:,}** XP ajouté à {member.mention} ! (Total: {user_data['xp']:,})"
        if new_level:
            msg += f"\n🎉 Level up ! Niveau **{new_level}**"
        
        await ctx.send(embed=success_embed(msg))
    
    @leveladmin.command(name="resetuser")
    @commands.has_permissions(administrator=True)
    async def resetuser(self, ctx: commands.Context, member: discord.Member):
        """Remet à zéro l'XP d'un membre"""
        await db.execute(
            "DELETE FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id)
        )
        await ctx.send(embed=success_embed(f"XP de {member.mention} remis à zéro !"))
    
    @leveladmin.command(name="xppermsg")
    @commands.has_permissions(administrator=True)
    async def xppermsg(self, ctx: commands.Context, amount: int):
        """Définit l'XP gagné par message"""
        await db.execute(
            "UPDATE levels_config SET xp_per_message = ? WHERE guild_id = ?",
            (amount, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"XP par message défini à **{amount}**"))
    
    @leveladmin.command(name="cooldown")
    @commands.has_permissions(administrator=True)
    async def set_cooldown(self, ctx: commands.Context, seconds: int):
        """Définit le cooldown entre les gains d'XP"""
        await db.execute(
            "UPDATE levels_config SET xp_cooldown = ? WHERE guild_id = ?",
            (seconds, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Cooldown XP défini à **{seconds}** secondes"))
    
    @leveladmin.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Définit le salon des annonces de level up"""
        channel_id = channel.id if channel else None
        await db.execute(
            "UPDATE levels_config SET level_up_channel_id = ? WHERE guild_id = ?",
            (channel_id, ctx.guild.id)
        )
        
        if channel:
            await ctx.send(embed=success_embed(f"Annonces de level up dans {channel.mention}"))
        else:
            await ctx.send(embed=success_embed("Les annonces seront dans le salon du message"))
    
    @leveladmin.command(name="message")
    @commands.has_permissions(administrator=True)
    async def set_message(self, ctx: commands.Context, *, message: str):
        """Définit le message de level up"""
        await db.execute(
            "UPDATE levels_config SET level_up_message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        
        preview = format_message(message, user=ctx.author.mention, level=10)
        await ctx.send(embed=success_embed(f"Message défini !\n\n**Aperçu:**\n{preview}"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
