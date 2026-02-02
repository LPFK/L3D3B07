"""
AutoMessages Cog - Messages récurrents automatiques

Features:
- Messages programmés récurrents (intervalle personnalisable)
- Rappels de bump (Disboard, top.gg, etc.)
- Messages d'annonce planifiés
- Support des embeds personnalisés
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
from datetime import datetime, timedelta
from typing import Optional, List
import json
import asyncio

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    parse_duration, format_duration, is_admin
)


class AutoMessages(commands.Cog):
    """Messages automatiques récurrents"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bump_cooldowns: dict = {}  # guild_id: last_bump_time
    
    async def cog_load(self):
        """Start background tasks"""
        self.check_automessages.start()
        self.check_bump_reminders.start()
    
    async def cog_unload(self):
        """Stop background tasks"""
        self.check_automessages.cancel()
        self.check_bump_reminders.cancel()
    
    @tasks.loop(minutes=1)
    async def check_automessages(self):
        """Check for scheduled messages to send"""
        try:
            now = time.time()
            
            # Get messages that need to be sent
            messages = await db.fetchall(
                """SELECT * FROM auto_messages 
                   WHERE enabled = 1 AND next_run <= ?""",
                (now,)
            )
            
            for msg in messages:
                guild = self.bot.get_guild(msg["guild_id"])
                if not guild:
                    continue
                
                channel = guild.get_channel(msg["channel_id"])
                if not channel:
                    continue
                
                await self.send_auto_message(channel, msg)
                
                # Update next run time
                next_run = now + msg["interval"]
                await db.execute(
                    "UPDATE auto_messages SET next_run = ?, last_run = ? WHERE id = ?",
                    (next_run, now, msg["id"])
                )
                
        except Exception as e:
            print(f"Error checking auto messages: {e}")
    
    @check_automessages.before_loop
    async def before_check_automessages(self):
        await self.bot.wait_until_ready()
    
    async def send_auto_message(self, channel: discord.TextChannel, msg: dict):
        """Send an automatic message"""
        try:
            content = msg.get("content")
            
            # Check if it's an embed
            if msg.get("embed_json"):
                try:
                    embed_data = json.loads(msg["embed_json"])
                    embed = discord.Embed.from_dict(embed_data)
                    await channel.send(content=content, embed=embed)
                except:
                    if content:
                        await channel.send(content)
            else:
                if content:
                    await channel.send(content)
                    
            # Mention role if configured
            if msg.get("mention_role_id"):
                role = channel.guild.get_role(msg["mention_role_id"])
                if role:
                    # Send role mention separately to ensure notification
                    mention_msg = await channel.send(role.mention)
                    await asyncio.sleep(1)
                    await mention_msg.delete()
                    
        except discord.Forbidden:
            pass
        except Exception as e:
            print(f"Error sending auto message: {e}")
    
    # ==================== BUMP REMINDERS ====================
    
    @tasks.loop(minutes=1)
    async def check_bump_reminders(self):
        """Check for bump reminders to send"""
        try:
            now = time.time()
            
            # Get guilds with bump reminders enabled
            configs = await db.fetchall(
                """SELECT * FROM bump_config 
                   WHERE enabled = 1 AND channel_id IS NOT NULL"""
            )
            
            for config in configs:
                guild_id = config["guild_id"]
                last_bump = config.get("last_bump") or 0
                cooldown = config.get("cooldown") or 7200  # 2 hours default (Disboard)
                last_reminder = config.get("last_reminder") or 0
                
                # Check if cooldown has passed and we haven't reminded recently
                if now - last_bump >= cooldown and now - last_reminder >= 300:  # 5 min between reminders
                    guild = self.bot.get_guild(guild_id)
                    if not guild:
                        continue
                    
                    channel = guild.get_channel(config["channel_id"])
                    if not channel:
                        continue
                    
                    await self.send_bump_reminder(guild, channel, config)
                    
                    await db.execute(
                        "UPDATE bump_config SET last_reminder = ? WHERE guild_id = ?",
                        (now, guild_id)
                    )
                    
        except Exception as e:
            print(f"Error checking bump reminders: {e}")
    
    @check_bump_reminders.before_loop
    async def before_check_bump(self):
        await self.bot.wait_until_ready()
    
    async def send_bump_reminder(self, guild: discord.Guild, channel: discord.TextChannel, config: dict):
        """Send a bump reminder"""
        message = config.get("message") or "⏰ Il est temps de bump le serveur ! Utilisez `/bump`"
        
        embed = create_embed(
            title="📢 Rappel de Bump",
            description=message,
            color=discord.Color.orange()
        )
        
        # Mention role if configured
        role_mention = ""
        if config.get("role_id"):
            role = guild.get_role(config["role_id"])
            if role:
                role_mention = role.mention
        
        try:
            await channel.send(content=role_mention or None, embed=embed)
        except:
            pass
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Detect bump success messages from bump bots"""
        if not message.guild:
            return
        
        # Check if it's from a bump bot
        bump_bots = [
            302050872383242240,  # Disboard
            315926021457051650,  # bump.gg (ServerHound)
        ]
        
        if message.author.id not in bump_bots:
            return
        
        # Check for successful bump indicators
        bump_success = False
        
        # Disboard success detection
        if message.author.id == 302050872383242240:
            if message.embeds:
                for embed in message.embeds:
                    if embed.description and "bump done" in embed.description.lower():
                        bump_success = True
                        break
                    if embed.description and "bumped" in embed.description.lower():
                        bump_success = True
                        break
        
        if bump_success:
            await db.execute(
                """INSERT INTO bump_config (guild_id, last_bump) 
                   VALUES (?, ?)
                   ON CONFLICT(guild_id) DO UPDATE SET last_bump = ?""",
                (message.guild.id, time.time(), time.time())
            )
            
            # Send thank you message if configured
            config = await db.fetchone(
                "SELECT * FROM bump_config WHERE guild_id = ?",
                (message.guild.id,)
            )
            
            if config and config.get("thank_message"):
                # Find who bumped (check recent messages)
                async for msg in message.channel.history(limit=5, before=message):
                    if msg.content.lower().startswith("/bump") or msg.content.lower().startswith("!d bump"):
                        try:
                            thank_msg = config["thank_message"].replace("{user}", msg.author.mention)
                            await message.channel.send(thank_msg)
                        except:
                            pass
                        break
    
    # ==================== AUTO MESSAGES COMMANDS ====================
    
    @commands.group(name="automsg", aliases=["automessage", "scheduled"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def automsg(self, ctx: commands.Context):
        """Gère les messages automatiques"""
        messages = await db.fetchall(
            "SELECT * FROM auto_messages WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        embed = create_embed(
            title="📨 Messages automatiques",
            color=discord.Color.blue()
        )
        
        if messages:
            for msg in messages[:10]:
                channel = ctx.guild.get_channel(msg["channel_id"])
                status = "✅" if msg["enabled"] else "❌"
                interval = format_duration(msg["interval"])
                
                content_preview = (msg.get("content") or "[Embed]")[:50]
                if len(content_preview) == 50:
                    content_preview += "..."
                
                embed.add_field(
                    name=f"{status} #{msg['id']} - {channel.name if channel else 'Inconnu'}",
                    value=f"**Intervalle:** {interval}\n**Message:** {content_preview}",
                    inline=False
                )
        else:
            embed.description = "Aucun message automatique configuré."
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`automsg add #salon <intervalle> <message>` - Ajoute un message
`automsg remove <id>` - Supprime un message
`automsg enable/disable <id>` - Active/désactive
`automsg list` - Liste les messages
`automsg test <id>` - Teste un message
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @automsg.command(name="add", aliases=["create"])
    @commands.has_permissions(administrator=True)
    async def automsg_add(self, ctx: commands.Context, channel: discord.TextChannel, interval: str, *, message: str):
        """Ajoute un message automatique
        
        Exemples:
        - !automsg add #général 2h N'oubliez pas de bump !
        - !automsg add #annonces 24h Message quotidien
        """
        seconds = parse_duration(interval)
        if not seconds or seconds < 300:  # Minimum 5 minutes
            return await ctx.send(embed=error_embed("Intervalle invalide ! (minimum 5 minutes)"))
        
        if seconds > 604800:  # Maximum 1 week
            return await ctx.send(embed=error_embed("Intervalle trop long ! (maximum 1 semaine)"))
        
        now = time.time()
        
        await db.execute(
            """INSERT INTO auto_messages 
               (guild_id, channel_id, content, interval, next_run, created_at, enabled)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (ctx.guild.id, channel.id, message, seconds, now + seconds, now)
        )
        
        # Get the ID
        result = await db.fetchone(
            "SELECT id FROM auto_messages WHERE guild_id = ? ORDER BY id DESC LIMIT 1",
            (ctx.guild.id,)
        )
        
        await ctx.send(embed=success_embed(
            f"Message automatique #{result['id']} créé !\n\n"
            f"**Salon:** {channel.mention}\n"
            f"**Intervalle:** {format_duration(seconds)}\n"
            f"**Prochain envoi:** <t:{int(now + seconds)}:R>"
        ))
    
    @automsg.command(name="addembed")
    @commands.has_permissions(administrator=True)
    async def automsg_addembed(self, ctx: commands.Context, channel: discord.TextChannel, interval: str, *, embed_json: str):
        """Ajoute un message automatique avec embed (JSON)
        
        Utilisez un générateur d'embed Discord pour créer le JSON
        """
        seconds = parse_duration(interval)
        if not seconds or seconds < 300:
            return await ctx.send(embed=error_embed("Intervalle invalide ! (minimum 5 minutes)"))
        
        # Validate JSON
        try:
            embed_data = json.loads(embed_json)
            # Test creating embed
            discord.Embed.from_dict(embed_data)
        except json.JSONDecodeError:
            return await ctx.send(embed=error_embed("JSON invalide !"))
        except:
            return await ctx.send(embed=error_embed("Format d'embed invalide !"))
        
        now = time.time()
        
        await db.execute(
            """INSERT INTO auto_messages 
               (guild_id, channel_id, embed_json, interval, next_run, created_at, enabled)
               VALUES (?, ?, ?, ?, ?, ?, 1)""",
            (ctx.guild.id, channel.id, embed_json, seconds, now + seconds, now)
        )
        
        result = await db.fetchone(
            "SELECT id FROM auto_messages WHERE guild_id = ? ORDER BY id DESC LIMIT 1",
            (ctx.guild.id,)
        )
        
        await ctx.send(embed=success_embed(f"Message automatique embed #{result['id']} créé !"))
    
    @automsg.command(name="remove", aliases=["delete"])
    @commands.has_permissions(administrator=True)
    async def automsg_remove(self, ctx: commands.Context, msg_id: int):
        """Supprime un message automatique"""
        result = await db.fetchone(
            "SELECT * FROM auto_messages WHERE id = ? AND guild_id = ?",
            (msg_id, ctx.guild.id)
        )
        
        if not result:
            return await ctx.send(embed=error_embed("Message non trouvé !"))
        
        await db.execute("DELETE FROM auto_messages WHERE id = ?", (msg_id,))
        await ctx.send(embed=success_embed(f"Message #{msg_id} supprimé !"))
    
    @automsg.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def automsg_enable(self, ctx: commands.Context, msg_id: int):
        """Active un message automatique"""
        result = await db.fetchone(
            "SELECT * FROM auto_messages WHERE id = ? AND guild_id = ?",
            (msg_id, ctx.guild.id)
        )
        
        if not result:
            return await ctx.send(embed=error_embed("Message non trouvé !"))
        
        await db.execute(
            "UPDATE auto_messages SET enabled = 1, next_run = ? WHERE id = ?",
            (time.time() + result["interval"], msg_id)
        )
        await ctx.send(embed=success_embed(f"Message #{msg_id} activé !"))
    
    @automsg.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def automsg_disable(self, ctx: commands.Context, msg_id: int):
        """Désactive un message automatique"""
        result = await db.fetchone(
            "SELECT * FROM auto_messages WHERE id = ? AND guild_id = ?",
            (msg_id, ctx.guild.id)
        )
        
        if not result:
            return await ctx.send(embed=error_embed("Message non trouvé !"))
        
        await db.execute("UPDATE auto_messages SET enabled = 0 WHERE id = ?", (msg_id,))
        await ctx.send(embed=success_embed(f"Message #{msg_id} désactivé !"))
    
    @automsg.command(name="test")
    @commands.has_permissions(administrator=True)
    async def automsg_test(self, ctx: commands.Context, msg_id: int):
        """Teste un message automatique"""
        result = await db.fetchone(
            "SELECT * FROM auto_messages WHERE id = ? AND guild_id = ?",
            (msg_id, ctx.guild.id)
        )
        
        if not result:
            return await ctx.send(embed=error_embed("Message non trouvé !"))
        
        channel = ctx.guild.get_channel(result["channel_id"])
        if not channel:
            return await ctx.send(embed=error_embed("Salon introuvable !"))
        
        await self.send_auto_message(channel, result)
        await ctx.send(embed=success_embed(f"Message #{msg_id} envoyé dans {channel.mention} !"))
    
    @automsg.command(name="list")
    @commands.has_permissions(administrator=True)
    async def automsg_list(self, ctx: commands.Context):
        """Liste tous les messages automatiques"""
        await self.automsg(ctx)
    
    @automsg.command(name="interval")
    @commands.has_permissions(administrator=True)
    async def automsg_interval(self, ctx: commands.Context, msg_id: int, interval: str):
        """Change l'intervalle d'un message"""
        seconds = parse_duration(interval)
        if not seconds or seconds < 300:
            return await ctx.send(embed=error_embed("Intervalle invalide ! (minimum 5 minutes)"))
        
        result = await db.fetchone(
            "SELECT * FROM auto_messages WHERE id = ? AND guild_id = ?",
            (msg_id, ctx.guild.id)
        )
        
        if not result:
            return await ctx.send(embed=error_embed("Message non trouvé !"))
        
        await db.execute(
            "UPDATE auto_messages SET interval = ?, next_run = ? WHERE id = ?",
            (seconds, time.time() + seconds, msg_id)
        )
        await ctx.send(embed=success_embed(f"Intervalle du message #{msg_id} changé à {format_duration(seconds)} !"))
    
    # ==================== BUMP REMINDER COMMANDS ====================
    
    @commands.group(name="bump", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def bump(self, ctx: commands.Context):
        """Configure les rappels de bump"""
        config = await db.fetchone(
            "SELECT * FROM bump_config WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        if not config:
            await db.execute(
                "INSERT INTO bump_config (guild_id) VALUES (?)",
                (ctx.guild.id,)
            )
            config = {"enabled": 0, "channel_id": None, "cooldown": 7200}
        
        channel = ctx.guild.get_channel(config.get("channel_id")) if config.get("channel_id") else None
        role = ctx.guild.get_role(config.get("role_id")) if config.get("role_id") else None
        
        last_bump = config.get("last_bump") or 0
        cooldown = config.get("cooldown") or 7200
        
        if last_bump:
            next_bump = last_bump + cooldown
            if next_bump > time.time():
                next_bump_text = f"<t:{int(next_bump)}:R>"
            else:
                next_bump_text = "Maintenant !"
        else:
            next_bump_text = "Jamais bumpé"
        
        embed = create_embed(
            title="📢 Configuration Bump",
            color=discord.Color.orange(),
            fields=[
                ("État", "✅ Activé" if config.get("enabled") else "❌ Désactivé", True),
                ("Salon", channel.mention if channel else "Non configuré", True),
                ("Rôle", role.mention if role else "Non configuré", True),
                ("Cooldown", format_duration(cooldown), True),
                ("Prochain bump", next_bump_text, True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`bump enable/disable` - Active/désactive
`bump channel #salon` - Salon des rappels
`bump role @role` - Rôle à mentionner
`bump cooldown <durée>` - Temps entre les bumps
`bump message <message>` - Message personnalisé
`bump thank <message>` - Message de remerciement
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @bump.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def bump_enable(self, ctx: commands.Context):
        """Active les rappels de bump"""
        await db.execute(
            """INSERT INTO bump_config (guild_id, enabled) 
               VALUES (?, 1)
               ON CONFLICT(guild_id) DO UPDATE SET enabled = 1""",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Rappels de bump activés !"))
    
    @bump.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def bump_disable(self, ctx: commands.Context):
        """Désactive les rappels de bump"""
        await db.execute(
            "UPDATE bump_config SET enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Rappels de bump désactivés !"))
    
    @bump.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def bump_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon des rappels"""
        await db.execute(
            """INSERT INTO bump_config (guild_id, channel_id) 
               VALUES (?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?""",
            (ctx.guild.id, channel.id, channel.id)
        )
        await ctx.send(embed=success_embed(f"Salon de bump: {channel.mention}"))
    
    @bump.command(name="role")
    @commands.has_permissions(administrator=True)
    async def bump_role(self, ctx: commands.Context, role: discord.Role):
        """Définit le rôle à mentionner"""
        await db.execute(
            "UPDATE bump_config SET role_id = ? WHERE guild_id = ?",
            (role.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Rôle de bump: {role.mention}"))
    
    @bump.command(name="cooldown")
    @commands.has_permissions(administrator=True)
    async def bump_cooldown(self, ctx: commands.Context, duration: str):
        """Définit le temps entre les bumps (défaut: 2h pour Disboard)"""
        seconds = parse_duration(duration)
        if not seconds or seconds < 1800:  # Minimum 30 min
            return await ctx.send(embed=error_embed("Durée invalide ! (minimum 30 minutes)"))
        
        await db.execute(
            "UPDATE bump_config SET cooldown = ? WHERE guild_id = ?",
            (seconds, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Cooldown de bump: {format_duration(seconds)}"))
    
    @bump.command(name="message")
    @commands.has_permissions(administrator=True)
    async def bump_message(self, ctx: commands.Context, *, message: str):
        """Définit le message de rappel"""
        await db.execute(
            "UPDATE bump_config SET message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Message de rappel défini !\n\n**Aperçu:** {message}"))
    
    @bump.command(name="thank")
    @commands.has_permissions(administrator=True)
    async def bump_thank(self, ctx: commands.Context, *, message: str):
        """Définit le message de remerciement ({user} = mention)"""
        await db.execute(
            "UPDATE bump_config SET thank_message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        preview = message.replace("{user}", ctx.author.mention)
        await ctx.send(embed=success_embed(f"Message de remerciement défini !\n\n**Aperçu:** {preview}"))
    
    @bump.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def bump_reset(self, ctx: commands.Context):
        """Réinitialise le timer de bump"""
        await db.execute(
            "UPDATE bump_config SET last_bump = 0, last_reminder = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Timer de bump réinitialisé !"))


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMessages(bot))
