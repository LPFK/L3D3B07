"""
Birthdays Cog - Système d'anniversaires avec annonces automatiques
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
from datetime import datetime, timedelta
from typing import Optional
import calendar

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    format_message, is_admin
)


class Birthdays(commands.Cog):
    """Système d'anniversaires"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.announced_today = set()  # Track announced birthdays
    
    async def cog_load(self):
        """Start background task"""
        self.check_birthdays.start()
    
    async def cog_unload(self):
        """Stop background task"""
        self.check_birthdays.cancel()
    
    @tasks.loop(minutes=30)
    async def check_birthdays(self):
        """Check for birthdays to announce"""
        try:
            now = datetime.now()
            today_day = now.day
            today_month = now.month
            
            # Get all guilds with birthdays enabled
            guilds = await db.fetchall(
                """SELECT gs.guild_id, bc.* FROM guild_settings gs
                   JOIN birthday_config bc ON gs.guild_id = bc.guild_id
                   WHERE gs.birthdays_enabled = 1 AND bc.channel_id IS NOT NULL"""
            )
            
            for guild_config in guilds:
                guild = self.bot.get_guild(guild_config["guild_id"])
                if not guild:
                    continue
                
                # Check announce hour
                announce_hour = guild_config.get("announce_hour") or 9
                if now.hour != announce_hour:
                    continue
                
                # Get today's birthdays
                birthdays = await db.fetchall(
                    """SELECT * FROM user_birthdays 
                       WHERE guild_id = ? AND day = ? AND month = ?""",
                    (guild.id, today_day, today_month)
                )
                
                for bday in birthdays:
                    # Check if already announced today
                    announce_key = f"{guild.id}_{bday['user_id']}_{today_day}_{today_month}"
                    if announce_key in self.announced_today:
                        continue
                    
                    member = guild.get_member(bday["user_id"])
                    if not member:
                        continue
                    
                    await self.announce_birthday(member, guild_config, bday)
                    self.announced_today.add(announce_key)
            
            # Clear announced set at midnight
            if now.hour == 0 and now.minute < 30:
                self.announced_today.clear()
                
        except Exception as e:
            print(f"Error checking birthdays: {e}")
    
    @check_birthdays.before_loop
    async def before_check_birthdays(self):
        await self.bot.wait_until_ready()
    
    async def announce_birthday(self, member: discord.Member, config: dict, bday: dict):
        """Announce a birthday"""
        guild = member.guild
        channel = guild.get_channel(config["channel_id"])
        
        if not channel:
            return
        
        # Calculate age if year is set
        age_text = ""
        if bday.get("year"):
            age = datetime.now().year - bday["year"]
            age_text = f" ({age} ans)"
        
        # Custom message or default
        message_template = config.get("message") or "🎂 Joyeux anniversaire {user} !{age}"
        message = format_message(
            message_template,
            user=member.mention,
            age=age_text,
            server=guild.name
        )
        
        embed = create_embed(
            title="🎂 Joyeux anniversaire !",
            description=message,
            color=discord.Color.from_rgb(255, 182, 193),  # Pink
            thumbnail=member.display_avatar.url
        )
        
        try:
            await channel.send(embed=embed)
            
            # Give birthday role if configured
            if config.get("role_id"):
                role = guild.get_role(config["role_id"])
                if role and role < guild.me.top_role:
                    await member.add_roles(role, reason="Birthday role")
                    
                    # Schedule role removal (24h later)
                    # Note: In production, use a database-backed scheduler
                    self.bot.loop.create_task(
                        self.remove_birthday_role(member, role, 86400)
                    )
        except discord.Forbidden:
            pass
    
    async def remove_birthday_role(self, member: discord.Member, role: discord.Role, delay: int):
        """Remove birthday role after delay"""
        import asyncio
        await asyncio.sleep(delay)
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Birthday role expired")
        except:
            pass
    
    async def get_config(self, guild_id: int) -> dict:
        """Get birthday config"""
        row = await db.fetchone(
            "SELECT * FROM birthday_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO birthday_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM birthday_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    def parse_date(self, date_str: str) -> tuple:
        """Parse a date string (DD/MM or DD/MM/YYYY)"""
        parts = date_str.replace("-", "/").split("/")
        
        if len(parts) == 2:
            day, month = int(parts[0]), int(parts[1])
            year = None
        elif len(parts) == 3:
            day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            # Handle 2-digit years
            if year < 100:
                year += 1900 if year > 50 else 2000
        else:
            raise ValueError("Invalid date format")
        
        # Validate
        if not (1 <= month <= 12):
            raise ValueError("Invalid month")
        if not (1 <= day <= calendar.monthrange(2000, month)[1]):
            raise ValueError("Invalid day")
        if year and not (1900 <= year <= datetime.now().year):
            raise ValueError("Invalid year")
        
        return day, month, year
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="birthday", aliases=["anniversaire", "bday"], invoke_without_command=True)
    async def birthday(self, ctx: commands.Context):
        """Gère ton anniversaire"""
        # Show user's birthday
        bday = await db.fetchone(
            "SELECT * FROM user_birthdays WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, ctx.author.id)
        )
        
        if bday:
            date_str = f"{bday['day']:02d}/{bday['month']:02d}"
            if bday.get("year"):
                date_str += f"/{bday['year']}"
            
            embed = create_embed(
                title="🎂 Ton anniversaire",
                description=f"**Date:** {date_str}",
                color=discord.Color.from_rgb(255, 182, 193)
            )
        else:
            embed = info_embed(
                "Tu n'as pas encore défini ton anniversaire !\n\n"
                "Utilise `!birthday set JJ/MM` ou `!birthday set JJ/MM/AAAA`"
            )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`birthday set <date>` - Définit ton anniversaire
`birthday remove` - Supprime ton anniversaire
`birthday list` - Prochains anniversaires
`birthday user @membre` - Voir l'anniversaire d'un membre
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @birthday.command(name="set")
    async def birthday_set(self, ctx: commands.Context, date: str):
        """Définit ton anniversaire (JJ/MM ou JJ/MM/AAAA)"""
        try:
            day, month, year = self.parse_date(date)
        except ValueError as e:
            return await ctx.send(embed=error_embed(f"Date invalide ! Utilise JJ/MM ou JJ/MM/AAAA"))
        
        # Check if birthday changes are allowed
        config = await self.get_config(ctx.guild.id)
        
        existing = await db.fetchone(
            "SELECT * FROM user_birthdays WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, ctx.author.id)
        )
        
        if existing and not config.get("allow_changes"):
            # Check if last change was recent
            last_change = existing.get("updated_at") or 0
            if time.time() - last_change < 86400 * 30:  # 30 days
                return await ctx.send(embed=error_embed(
                    "Tu ne peux changer ton anniversaire qu'une fois par mois !"
                ))
        
        await db.execute(
            """INSERT OR REPLACE INTO user_birthdays 
               (guild_id, user_id, day, month, year, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ctx.guild.id, ctx.author.id, day, month, year, time.time())
        )
        
        date_str = f"{day:02d}/{month:02d}"
        if year:
            date_str += f"/{year}"
        
        await ctx.send(embed=success_embed(f"Anniversaire défini au **{date_str}** ! 🎂"))
    
    @birthday.command(name="remove", aliases=["delete"])
    async def birthday_remove(self, ctx: commands.Context):
        """Supprime ton anniversaire"""
        await db.execute(
            "DELETE FROM user_birthdays WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, ctx.author.id)
        )
        await ctx.send(embed=success_embed("Anniversaire supprimé !"))
    
    @birthday.command(name="user", aliases=["check"])
    async def birthday_user(self, ctx: commands.Context, member: discord.Member):
        """Voir l'anniversaire d'un membre"""
        bday = await db.fetchone(
            "SELECT * FROM user_birthdays WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id)
        )
        
        if not bday:
            return await ctx.send(embed=info_embed(f"{member.display_name} n'a pas défini son anniversaire."))
        
        date_str = f"{bday['day']:02d}/{bday['month']:02d}"
        
        # Calculate days until birthday
        now = datetime.now()
        next_bday = datetime(now.year, bday["month"], bday["day"])
        if next_bday < now:
            next_bday = datetime(now.year + 1, bday["month"], bday["day"])
        days_until = (next_bday - now).days
        
        embed = create_embed(
            title=f"🎂 Anniversaire de {member.display_name}",
            description=f"**Date:** {date_str}\n**Dans:** {days_until} jour(s)",
            color=discord.Color.from_rgb(255, 182, 193),
            thumbnail=member.display_avatar.url
        )
        
        await ctx.send(embed=embed)
    
    @birthday.command(name="list", aliases=["upcoming"])
    async def birthday_list(self, ctx: commands.Context):
        """Affiche les prochains anniversaires"""
        birthdays = await db.fetchall(
            "SELECT * FROM user_birthdays WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        if not birthdays:
            return await ctx.send(embed=info_embed("Aucun anniversaire enregistré !"))
        
        now = datetime.now()
        upcoming = []
        
        for bday in birthdays:
            member = ctx.guild.get_member(bday["user_id"])
            if not member:
                continue
            
            next_bday = datetime(now.year, bday["month"], bday["day"])
            if next_bday < now:
                next_bday = datetime(now.year + 1, bday["month"], bday["day"])
            
            days_until = (next_bday - now).days
            upcoming.append((member, bday, days_until))
        
        # Sort by days until
        upcoming.sort(key=lambda x: x[2])
        
        description = ""
        for member, bday, days in upcoming[:15]:
            date_str = f"{bday['day']:02d}/{bday['month']:02d}"
            
            if days == 0:
                description += f"🎂 **{member.display_name}** - Aujourd'hui !\n"
            elif days == 1:
                description += f"🎁 **{member.display_name}** - Demain ({date_str})\n"
            else:
                description += f"📅 **{member.display_name}** - {date_str} (dans {days}j)\n"
        
        embed = create_embed(
            title="🎂 Prochains anniversaires",
            description=description or "Aucun anniversaire à venir.",
            color=discord.Color.from_rgb(255, 182, 193)
        )
        
        await ctx.send(embed=embed)
    
    @birthday.command(name="today")
    async def birthday_today(self, ctx: commands.Context):
        """Affiche les anniversaires du jour"""
        now = datetime.now()
        
        birthdays = await db.fetchall(
            "SELECT * FROM user_birthdays WHERE guild_id = ? AND day = ? AND month = ?",
            (ctx.guild.id, now.day, now.month)
        )
        
        if not birthdays:
            return await ctx.send(embed=info_embed("Aucun anniversaire aujourd'hui !"))
        
        members = []
        for bday in birthdays:
            member = ctx.guild.get_member(bday["user_id"])
            if member:
                age_text = ""
                if bday.get("year"):
                    age = now.year - bday["year"]
                    age_text = f" ({age} ans)"
                members.append(f"🎂 {member.mention}{age_text}")
        
        embed = create_embed(
            title="🎂 Anniversaires du jour",
            description="\n".join(members) if members else "Aucun anniversaire aujourd'hui.",
            color=discord.Color.from_rgb(255, 182, 193)
        )
        
        await ctx.send(embed=embed)
    
    # ==================== ADMIN COMMANDS ====================
    
    @birthday.group(name="config", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def birthday_config(self, ctx: commands.Context):
        """Configure le système d'anniversaires"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT birthdays_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        channel = ctx.guild.get_channel(config.get("channel_id"))
        role = ctx.guild.get_role(config.get("role_id"))
        
        embed = create_embed(
            title="🎂 Configuration des anniversaires",
            color=discord.Color.from_rgb(255, 182, 193),
            fields=[
                ("État", "✅ Activé" if settings and settings["birthdays_enabled"] else "❌ Désactivé", True),
                ("Salon", channel.mention if channel else "Non configuré", True),
                ("Rôle", role.mention if role else "Non configuré", True),
                ("Heure d'annonce", f"{config.get('announce_hour') or 9}h", True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`birthday config enable/disable` - Active/désactive
`birthday config channel #salon` - Salon d'annonces
`birthday config role @role` - Rôle d'anniversaire
`birthday config hour <heure>` - Heure d'annonce (0-23)
`birthday config message <message>` - Message personnalisé
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @birthday_config.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def birthday_enable(self, ctx: commands.Context):
        """Active le système d'anniversaires"""
        await db.execute(
            "UPDATE guild_settings SET birthdays_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système d'anniversaires activé !"))
    
    @birthday_config.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def birthday_disable(self, ctx: commands.Context):
        """Désactive le système d'anniversaires"""
        await db.execute(
            "UPDATE guild_settings SET birthdays_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système d'anniversaires désactivé !"))
    
    @birthday_config.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def birthday_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon d'annonces"""
        await self.get_config(ctx.guild.id)
        await db.execute(
            "UPDATE birthday_config SET channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon d'anniversaires: {channel.mention}"))
    
    @birthday_config.command(name="role")
    @commands.has_permissions(administrator=True)
    async def birthday_role(self, ctx: commands.Context, role: discord.Role):
        """Définit le rôle d'anniversaire (donné pendant 24h)"""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Je ne peux pas donner ce rôle !"))
        
        await db.execute(
            "UPDATE birthday_config SET role_id = ? WHERE guild_id = ?",
            (role.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Rôle d'anniversaire: {role.mention}"))
    
    @birthday_config.command(name="hour")
    @commands.has_permissions(administrator=True)
    async def birthday_hour(self, ctx: commands.Context, hour: int):
        """Définit l'heure d'annonce (0-23)"""
        if not (0 <= hour <= 23):
            return await ctx.send(embed=error_embed("L'heure doit être entre 0 et 23 !"))
        
        await db.execute(
            "UPDATE birthday_config SET announce_hour = ? WHERE guild_id = ?",
            (hour, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Heure d'annonce: {hour}h"))
    
    @birthday_config.command(name="message")
    @commands.has_permissions(administrator=True)
    async def birthday_message(self, ctx: commands.Context, *, message: str):
        """Définit le message d'anniversaire
        
        Variables: {user}, {age}, {server}
        """
        await db.execute(
            "UPDATE birthday_config SET message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        
        preview = format_message(message, user=ctx.author.mention, age=" (20 ans)", server=ctx.guild.name)
        await ctx.send(embed=success_embed(f"Message défini !\n\n**Aperçu:**\n{preview}"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthdays(bot))
