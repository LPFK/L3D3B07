"""
Cog Moderation - ban, kick, mute, warn, automod

utilise moderation_repo pour config et cases
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import json
import re
from typing import Optional
from datetime import datetime, timedelta

from utils.database import db
from utils.repositories.moderation import moderation_repo
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed, warning_embed,
    parse_duration, format_duration, format_datetime, ConfirmView, is_mod
)


class Moderation(commands.Cog):
    """Commandes de moderation"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.spam_tracker: dict[tuple[int, int], list[float]] = {}
    
    async def cog_load(self):
        self.check_temp_punishments.start()
    
    async def cog_unload(self):
        self.check_temp_punishments.cancel()
    
    async def log_action(
        self,
        guild: discord.Guild,
        action: str,
        user: discord.User,
        moderator: discord.Member,
        reason: str = None,
        duration: int = None
    ):
        """log une action de moderation"""
        # cree le case via le repo
        case = await moderation_repo.create_case(
            guild_id=guild.id,
            user_id=user.id,
            moderator_id=moderator.id,
            action=action,
            reason=reason or "",
            duration=duration
        )
        
        # envoie dans le channel de log
        config = await moderation_repo.get_config(guild.id)
        log_channel_id = config.get("mod_log_channel_id")
        
        if log_channel_id:
            channel = guild.get_channel(log_channel_id)
            if channel:
                color_map = {
                    "ban": discord.Color.red(),
                    "unban": discord.Color.green(),
                    "kick": discord.Color.orange(),
                    "mute": discord.Color.dark_gray(),
                    "unmute": discord.Color.green(),
                    "warn": discord.Color.yellow(),
                }
                
                embed = create_embed(
                    title=f"📋 Case #{case.id} | {action.upper()}",
                    color=color_map.get(action, discord.Color.blurple()),
                    fields=[
                        ("Membre", f"{user} ({user.id})", True),
                        ("Modérateur", f"{moderator} ({moderator.id})", True),
                        ("Raison", reason or "Aucune raison spécifiée", False),
                    ]
                )
                
                if duration:
                    embed.add_field(name="Durée", value=format_duration(duration), inline=True)
                
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    pass
        
        return case.id
    
    async def get_or_create_mute_role(self, guild: discord.Guild) -> discord.Role:
        """recupere ou cree le role mute"""
        config = await moderation_repo.get_config(guild.id)
        
        if config.get("mute_role_id"):
            role = guild.get_role(config["mute_role_id"])
            if role:
                return role
        
        role = await guild.create_role(
            name="Muted",
            reason="Auto-created mute role",
            color=discord.Color.dark_gray()
        )
        
        for channel in guild.channels:
            try:
                await channel.set_permissions(
                    role,
                    send_messages=False,
                    add_reactions=False,
                    speak=False,
                    reason="Mute role setup"
                )
            except discord.Forbidden:
                pass
        
        await moderation_repo.update_config(guild.id, mute_role_id=role.id)
        return role
    
    @tasks.loop(minutes=1)
    async def check_temp_punishments(self):
        """verifie les punitions temporaires expirees"""
        # utilise le nouveau systeme de punitions temp
        expired = await moderation_repo.get_expired_punishments()
        
        for punishment in expired:
            guild = self.bot.get_guild(punishment.guild_id)
            if not guild:
                continue
            
            if punishment.action == "ban":
                try:
                    await guild.unban(
                        discord.Object(id=punishment.user_id),
                        reason="Temporary ban expired"
                    )
                except discord.NotFound:
                    pass
            
            elif punishment.action == "mute":
                member = guild.get_member(punishment.user_id)
                if member:
                    # timeout discord natif
                    try:
                        await member.timeout(None, reason="Mute expired")
                    except discord.Forbidden:
                        pass
            
            await moderation_repo.remove_temp_punishment(
                punishment.guild_id, punishment.user_id, punishment.action
            )
        
        # fallback: check les anciennes tables aussi (backward compat)
        await self._check_legacy_temp_punishments()
    
    async def _check_legacy_temp_punishments(self):
        """check les anciennes tables temp_bans et temp_mutes"""
        now = time.time()
        
        # temp bans
        bans = await db.fetchall(
            "SELECT * FROM temp_bans WHERE expires_at <= ?", (now,)
        )
        for ban in bans:
            guild = self.bot.get_guild(ban["guild_id"])
            if guild:
                try:
                    await guild.unban(
                        discord.Object(id=ban["user_id"]),
                        reason="Temporary ban expired"
                    )
                except discord.NotFound:
                    pass
            await db.execute(
                "DELETE FROM temp_bans WHERE guild_id = ? AND user_id = ?",
                (ban["guild_id"], ban["user_id"])
            )
        
        # temp mutes
        mutes = await db.fetchall(
            "SELECT * FROM temp_mutes WHERE expires_at <= ?", (now,)
        )
        for mute in mutes:
            guild = self.bot.get_guild(mute["guild_id"])
            if guild:
                member = guild.get_member(mute["user_id"])
                if member:
                    config = await moderation_repo.get_config(guild.id)
                    if config.get("mute_role_id"):
                        role = guild.get_role(config["mute_role_id"])
                        if role and role in member.roles:
                            try:
                                await member.remove_roles(role, reason="Mute expired")
                            except discord.Forbidden:
                                pass
            await db.execute(
                "DELETE FROM temp_mutes WHERE guild_id = ? AND user_id = ?",
                (mute["guild_id"], mute["user_id"])
            )
    
    @check_temp_punishments.before_loop
    async def before_check_punishments(self):
        await self.bot.wait_until_ready()
    
    # ==================== AUTOMOD LISTENER ====================
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """automoderation"""
        if not message.guild or message.author.bot:
            return
        
        if message.author.guild_permissions.administrator:
            return
        
        # config cached par le repo
        config = await moderation_repo.get_config(message.guild.id)
        
        if config.get("antispam_enabled"):
            await self.check_spam(message, config)
        
        if config.get("anti_invite_enabled"):
            await self.check_invites(message, config)
        
        if config.get("anti_links_enabled"):
            await self.check_links(message, config)
        
        if config.get("bad_words_enabled"):
            await self.check_bad_words(message, config)
    
    async def check_spam(self, message: discord.Message, config: dict):
        """anti-spam"""
        key = (message.guild.id, message.author.id)
        now = time.time()
        
        if key not in self.spam_tracker:
            self.spam_tracker[key] = []
        
        window = config.get("antispam_seconds", 5)
        self.spam_tracker[key] = [t for t in self.spam_tracker[key] if now - t < window]
        self.spam_tracker[key].append(now)
        
        threshold = config.get("antispam_messages", 5)
        if len(self.spam_tracker[key]) >= threshold:
            action = config.get("antispam_action", "mute")
            
            try:
                await message.delete()
            except discord.Forbidden:
                pass
            
            if action == "mute":
                role = await self.get_or_create_mute_role(message.guild)
                await message.author.add_roles(role, reason="Anti-spam")
                
                # utilise le nouveau systeme
                await moderation_repo.add_temp_punishment(
                    message.guild.id, message.author.id, "mute",
                    time.time() + 300, role.id
                )
                
                try:
                    await message.channel.send(
                        embed=warning_embed(f"{message.author.mention} a été mute pour spam (5 min)"),
                        delete_after=10
                    )
                except discord.Forbidden:
                    pass
            
            self.spam_tracker[key] = []
    
    async def check_invites(self, message: discord.Message, config: dict):
        """anti-invites discord"""
        invite_pattern = r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|li)|discordapp\.com/invite)/[a-zA-Z0-9]+"
        
        if re.search(invite_pattern, message.content):
            try:
                await message.delete()
                await message.channel.send(
                    embed=warning_embed(f"{message.author.mention}, les invitations Discord ne sont pas autorisées !"),
                    delete_after=5
                )
            except discord.Forbidden:
                pass
    
    async def check_links(self, message: discord.Message, config: dict):
        """anti-links"""
        link_pattern = r"https?://[^\s]+"
        
        if re.search(link_pattern, message.content):
            # allowed_links deja parse en list par le cache
            allowed = config.get("allowed_links", [])
            if isinstance(allowed, str):
                allowed = json.loads(allowed)
            
            for link in re.findall(link_pattern, message.content):
                if not any(allowed_domain in link for allowed_domain in allowed):
                    try:
                        await message.delete()
                        await message.channel.send(
                            embed=warning_embed(f"{message.author.mention}, les liens ne sont pas autorisés !"),
                            delete_after=5
                        )
                    except discord.Forbidden:
                        pass
                    break
    
    async def check_bad_words(self, message: discord.Message, config: dict):
        """filtre de mots"""
        # bad_words deja parse par le cache si configure
        bad_words = config.get("bad_words", [])
        if isinstance(bad_words, str):
            bad_words = json.loads(bad_words)
        
        content_lower = message.content.lower()
        
        for word in bad_words:
            if word.lower() in content_lower:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=warning_embed(f"{message.author.mention}, ce mot n'est pas autorisé !"),
                        delete_after=5
                    )
                except discord.Forbidden:
                    pass
                break
    
    # ==================== COMMANDS ====================
    
    @commands.hybrid_command(name="ban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(
        member="Le membre à bannir",
        duration="Durée du ban (ex: 1d, 12h, 30m)",
        reason="Raison du ban"
    )
    async def ban(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str = None,
        *,
        reason: str = None
    ):
        """Bannit un membre du serveur"""
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed("Tu ne peux pas bannir ce membre !"))
        
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Je ne peux pas bannir ce membre !"))
        
        duration_seconds = None
        if duration:
            td = parse_duration(duration)
            if td:
                duration_seconds = int(td.total_seconds())
        
        # DM avant ban
        try:
            dm_msg = f"Tu as été banni de **{ctx.guild.name}**"
            if reason:
                dm_msg += f"\nRaison: {reason}"
            if duration_seconds:
                dm_msg += f"\nDurée: {format_duration(duration_seconds)}"
            await member.send(embed=error_embed(dm_msg, "Bannissement"))
        except discord.Forbidden:
            pass
        
        await member.ban(reason=f"{ctx.author}: {reason or 'Pas de raison'}")
        
        if duration_seconds:
            await moderation_repo.add_temp_punishment(
                ctx.guild.id, member.id, "ban",
                time.time() + duration_seconds
            )
        
        case_num = await self.log_action(
            ctx.guild, "ban", member, ctx.author, reason, duration_seconds
        )
        
        duration_text = f" pour {format_duration(duration_seconds)}" if duration_seconds else ""
        await ctx.send(embed=success_embed(
            f"**{member}** a été banni{duration_text} ! (Case #{case_num})"
        ))
    
    @commands.hybrid_command(name="unban")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    @app_commands.describe(user_id="L'ID de l'utilisateur à débannir", reason="Raison du déban")
    async def unban(self, ctx: commands.Context, user_id: int, *, reason: str = None):
        """Débannit un utilisateur"""
        try:
            user = await self.bot.fetch_user(user_id)
            await ctx.guild.unban(user, reason=f"{ctx.author}: {reason or 'Pas de raison'}")
            
            await moderation_repo.remove_temp_punishment(ctx.guild.id, user_id, "ban")
            
            case_num = await self.log_action(ctx.guild, "unban", user, ctx.author, reason)
            await ctx.send(embed=success_embed(f"**{user}** a été débanni ! (Case #{case_num})"))
        except discord.NotFound:
            await ctx.send(embed=error_embed("Utilisateur non trouvé ou pas banni !"))
    
    @commands.hybrid_command(name="kick")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    @app_commands.describe(member="Le membre à expulser", reason="Raison de l'expulsion")
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Expulse un membre du serveur"""
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed("Tu ne peux pas expulser ce membre !"))
        
        if member.top_role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Je ne peux pas expulser ce membre !"))
        
        try:
            dm_msg = f"Tu as été expulsé de **{ctx.guild.name}**"
            if reason:
                dm_msg += f"\nRaison: {reason}"
            await member.send(embed=warning_embed(dm_msg, "Expulsion"))
        except discord.Forbidden:
            pass
        
        await member.kick(reason=f"{ctx.author}: {reason or 'Pas de raison'}")
        
        case_num = await self.log_action(ctx.guild, "kick", member, ctx.author, reason)
        await ctx.send(embed=success_embed(f"**{member}** a été expulsé ! (Case #{case_num})"))
    
    @commands.hybrid_command(name="mute", aliases=["timeout"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(
        member="Le membre à rendre muet",
        duration="Durée du mute (ex: 1d, 12h, 30m)",
        reason="Raison du mute"
    )
    async def mute(
        self,
        ctx: commands.Context,
        member: discord.Member,
        duration: str = "1h",
        *,
        reason: str = None
    ):
        """Rend un membre muet (timeout)"""
        if member.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
            return await ctx.send(embed=error_embed("Tu ne peux pas mute ce membre !"))
        
        td = parse_duration(duration)
        if not td:
            return await ctx.send(embed=error_embed("Durée invalide ! Ex: 1d, 12h, 30m"))
        
        if td > timedelta(days=28):
            return await ctx.send(embed=error_embed("La durée maximum est de 28 jours !"))
        
        duration_seconds = int(td.total_seconds())
        until = discord.utils.utcnow() + td
        
        await member.timeout(until, reason=f"{ctx.author}: {reason or 'Pas de raison'}")
        
        case_num = await self.log_action(
            ctx.guild, "mute", member, ctx.author, reason, duration_seconds
        )
        
        await ctx.send(embed=success_embed(
            f"**{member}** a été mute pour {format_duration(duration_seconds)} ! (Case #{case_num})"
        ))
    
    @commands.hybrid_command(name="unmute", aliases=["untimeout"])
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    @app_commands.describe(member="Le membre à démuter", reason="Raison du démute")
    async def unmute(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Retire le mute d'un membre"""
        await member.timeout(None, reason=f"{ctx.author}: {reason or 'Pas de raison'}")
        
        await moderation_repo.remove_temp_punishment(ctx.guild.id, member.id, "mute")
        
        case_num = await self.log_action(ctx.guild, "unmute", member, ctx.author, reason)
        await ctx.send(embed=success_embed(f"**{member}** a été démute ! (Case #{case_num})"))
    
    @commands.hybrid_command(name="warn")
    @commands.has_permissions(moderate_members=True)
    @app_commands.describe(member="Le membre à avertir", reason="Raison de l'avertissement")
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = None):
        """Donne un avertissement à un membre"""
        # cree le case de warn
        case = await moderation_repo.create_case(
            ctx.guild.id, member.id, ctx.author.id, "warn", reason or ""
        )
        
        # compte les warns
        warn_count = await moderation_repo.count_user_warns(ctx.guild.id, member.id)
        
        # log
        case_num = await self.log_action(ctx.guild, "warn", member, ctx.author, reason)
        
        # DM
        try:
            dm_msg = f"Tu as reçu un avertissement sur **{ctx.guild.name}**"
            if reason:
                dm_msg += f"\nRaison: {reason}"
            dm_msg += f"\nTu as maintenant **{warn_count}** avertissement(s)"
            await member.send(embed=warning_embed(dm_msg, "Avertissement"))
        except discord.Forbidden:
            pass
        
        await ctx.send(embed=success_embed(
            f"**{member}** a reçu un avertissement ({warn_count} total) ! (Case #{case_num})"
        ))
    
    @commands.hybrid_command(name="warnings", aliases=["warns", "infractions"])
    @app_commands.describe(member="Le membre dont tu veux voir les avertissements")
    async def warnings(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche les avertissements d'un membre"""
        member = member or ctx.author
        
        cases = await moderation_repo.get_user_cases(
            ctx.guild.id, member.id, action="warn", active_only=True
        )
        
        if not cases:
            return await ctx.send(embed=info_embed(f"{member.display_name} n'a aucun avertissement !"))
        
        description = ""
        for i, case in enumerate(cases[:10], 1):
            mod = ctx.guild.get_member(case.moderator_id)
            mod_name = mod.display_name if mod else "Modérateur inconnu"
            reason = case.reason or "Pas de raison"
            date = format_datetime(case.created_at)
            description += f"**#{i}** - Par {mod_name} ({date})\n└ {reason}\n\n"
        
        embed = create_embed(
            title=f"⚠️ Avertissements de {member.display_name}",
            description=description,
            color=discord.Color.yellow(),
            footer=f"Total: {len(cases)} avertissement(s)"
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="clearwarns", aliases=["clearwarnings"])
    @commands.has_permissions(administrator=True)
    @app_commands.describe(member="Le membre dont tu veux supprimer les avertissements")
    async def clearwarns(self, ctx: commands.Context, member: discord.Member):
        """Supprime tous les avertissements d'un membre"""
        count = await moderation_repo.clear_user_warns(ctx.guild.id, member.id)
        await ctx.send(embed=success_embed(
            f"{count} avertissement(s) de {member.mention} supprimé(s) !"
        ))
    
    @commands.hybrid_command(name="clear", aliases=["purge", "clean"])
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    @app_commands.describe(amount="Nombre de messages à supprimer (1-100)")
    async def clear(self, ctx: commands.Context, amount: int):
        """Supprime des messages"""
        if amount < 1 or amount > 100:
            return await ctx.send(embed=error_embed("Le nombre doit être entre 1 et 100 !"))
        
        try:
            await ctx.message.delete()
        except discord.NotFound:
            pass
        
        deleted = await ctx.channel.purge(limit=amount)
        
        msg = await ctx.send(embed=success_embed(f"🗑️ {len(deleted)} messages supprimés !"))
        await msg.delete(delay=3)
    
    @commands.hybrid_command(name="slowmode")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    @app_commands.describe(seconds="Délai en secondes (0 pour désactiver)")
    async def slowmode(self, ctx: commands.Context, seconds: int = 0):
        """Définit le mode lent du salon"""
        if seconds < 0 or seconds > 21600:
            return await ctx.send(embed=error_embed("Le délai doit être entre 0 et 21600 secondes !"))
        
        await ctx.channel.edit(slowmode_delay=seconds)
        
        if seconds == 0:
            await ctx.send(embed=success_embed("Mode lent désactivé !"))
        else:
            await ctx.send(embed=success_embed(f"Mode lent défini à **{seconds}** secondes !"))
    
    @commands.hybrid_command(name="lock")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context):
        """Verrouille le salon"""
        await ctx.channel.set_permissions(
            ctx.guild.default_role,
            send_messages=False,
            reason=f"Locked by {ctx.author}"
        )
        await ctx.send(embed=success_embed("🔒 Salon verrouillé !"))
    
    @commands.hybrid_command(name="unlock")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context):
        """Déverrouille le salon"""
        await ctx.channel.set_permissions(
            ctx.guild.default_role,
            send_messages=None,
            reason=f"Unlocked by {ctx.author}"
        )
        await ctx.send(embed=success_embed("🔓 Salon déverrouillé !"))
    
    # ==================== MODLOG CONFIG ====================
    
    @commands.group(name="modlog", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def modlog(self, ctx: commands.Context):
        """Configure les logs de modération"""
        config = await moderation_repo.get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(config.get("mod_log_channel_id"))
        
        embed = create_embed(
            title="📋 Configuration des logs de modération",
            description=f"**Salon actuel:** {channel.mention if channel else 'Non configuré'}",
            fields=[
                ("Définir le salon", f"`{ctx.prefix}modlog channel #salon`", False),
                ("Désactiver", f"`{ctx.prefix}modlog disable`", False),
            ]
        )
        await ctx.send(embed=embed)
    
    @modlog.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def modlog_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon des logs de modération"""
        await moderation_repo.update_config(ctx.guild.id, mod_log_channel_id=channel.id)
        await ctx.send(embed=success_embed(f"Logs de modération envoyés dans {channel.mention} !"))
    
    @modlog.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def modlog_disable(self, ctx: commands.Context):
        """Désactive les logs de modération"""
        await moderation_repo.update_config(ctx.guild.id, mod_log_channel_id=None)
        await ctx.send(embed=success_embed("Logs de modération désactivés !"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
