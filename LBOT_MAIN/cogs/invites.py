"""
Cog Invites - tracking d'invitations style InviteTracker

- qui a invite qui
- compteur invits (regular, leaves, fake, bonus)
- leaderboard inviteurs
- messages join/leave avec info inviteur
- rewards d'invitations
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
from typing import Optional, Dict, List
from collections import defaultdict

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    format_message, Paginator, is_admin
)


class Invites(commands.Cog):
    """Système de tracking d'invitations"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Cache des invites par guild: {guild_id: {invite_code: uses}}
        self.invite_cache: Dict[int, Dict[str, int]] = {}
    
    async def cog_load(self):
        """Initialize invite cache"""
        self.bot.loop.create_task(self.init_invite_cache())
        self.sync_invites.start()
    
    async def cog_unload(self):
        self.sync_invites.cancel()
    
    async def init_invite_cache(self):
        """Initialize the invite cache for all guilds"""
        await self.bot.wait_until_ready()
        
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)
    
    async def cache_guild_invites(self, guild: discord.Guild):
        """Cache invites for a guild"""
        try:
            invites = await guild.invites()
            self.invite_cache[guild.id] = {
                invite.code: invite.uses for invite in invites
            }
        except discord.Forbidden:
            self.invite_cache[guild.id] = {}
        except Exception as e:
            print(f"Error caching invites for {guild.name}: {e}")
            self.invite_cache[guild.id] = {}
    
    @tasks.loop(minutes=10)
    async def sync_invites(self):
        """Periodically sync invite cache"""
        for guild in self.bot.guilds:
            await self.cache_guild_invites(guild)
    
    @sync_invites.before_loop
    async def before_sync_invites(self):
        await self.bot.wait_until_ready()
    
    async def get_config(self, guild_id: int) -> dict:
        """Get invite config"""
        row = await db.fetchone(
            "SELECT * FROM invite_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO invite_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM invite_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    async def get_user_invites(self, guild_id: int, user_id: int) -> dict:
        """Get invite stats for a user"""
        row = await db.fetchone(
            "SELECT * FROM user_invites WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        if row:
            return dict(row)
        
        return {
            "regular": 0,
            "leaves": 0,
            "fake": 0,
            "bonus": 0
        }
    
    def calculate_total_invites(self, stats: dict) -> int:
        """Calculate total effective invites"""
        return stats.get("regular", 0) - stats.get("leaves", 0) - stats.get("fake", 0) + stats.get("bonus", 0)
    
    async def find_used_invite(self, guild: discord.Guild) -> Optional[discord.Invite]:
        """Find which invite was used for a new member"""
        try:
            new_invites = await guild.invites()
            new_invite_dict = {invite.code: invite for invite in new_invites}
            
            old_cache = self.invite_cache.get(guild.id, {})
            
            for code, invite in new_invite_dict.items():
                old_uses = old_cache.get(code, 0)
                if invite.uses > old_uses:
                    # Update cache
                    self.invite_cache[guild.id] = {
                        inv.code: inv.uses for inv in new_invites
                    }
                    return invite
            
            # Update cache even if no invite found
            self.invite_cache[guild.id] = {
                inv.code: inv.uses for inv in new_invites
            }
            return None
        except:
            return None
    
    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Cache invites when joining a guild"""
        await self.cache_guild_invites(guild)
    
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        """Track new invite creation"""
        if invite.guild.id not in self.invite_cache:
            self.invite_cache[invite.guild.id] = {}
        self.invite_cache[invite.guild.id][invite.code] = invite.uses
    
    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        """Track invite deletion"""
        if invite.guild.id in self.invite_cache:
            self.invite_cache[invite.guild.id].pop(invite.code, None)
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Track who invited a new member"""
        if member.bot:
            return
        
        # Check if invites tracking is enabled
        settings = await db.fetchone(
            "SELECT invites_enabled FROM guild_settings WHERE guild_id = ?",
            (member.guild.id,)
        )
        if not settings or not settings["invites_enabled"]:
            return
        
        config = await self.get_config(member.guild.id)
        
        # Find which invite was used
        used_invite = await self.find_used_invite(member.guild)
        
        inviter = None
        invite_code = None
        
        if used_invite and used_invite.inviter:
            inviter = used_invite.inviter
            invite_code = used_invite.code
            
            # Check for fake invite (account too young)
            is_fake = False
            account_age = (discord.utils.utcnow() - member.created_at).days
            min_age = config.get("min_account_age") or 7
            
            if account_age < min_age:
                is_fake = True
            
            # Update inviter stats
            if is_fake:
                await db.execute(
                    """INSERT INTO user_invites (guild_id, user_id, fake)
                       VALUES (?, ?, 1)
                       ON CONFLICT(guild_id, user_id) DO UPDATE SET fake = fake + 1""",
                    (member.guild.id, inviter.id)
                )
            else:
                await db.execute(
                    """INSERT INTO user_invites (guild_id, user_id, regular)
                       VALUES (?, ?, 1)
                       ON CONFLICT(guild_id, user_id) DO UPDATE SET regular = regular + 1""",
                    (member.guild.id, inviter.id)
                )
            
            # Store who invited this member
            await db.execute(
                """INSERT OR REPLACE INTO invited_users 
                   (guild_id, user_id, inviter_id, invite_code, joined_at, is_fake)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (member.guild.id, member.id, inviter.id, invite_code, time.time(), is_fake)
            )
            
            # Check for invite rewards
            await self.check_invite_rewards(member.guild, inviter)
        
        # Send join message
        if config.get("join_channel_id"):
            channel = member.guild.get_channel(config["join_channel_id"])
            if channel:
                await self.send_join_message(member, inviter, invite_code, config, channel)
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Track when an invited member leaves"""
        if member.bot:
            return
        
        settings = await db.fetchone(
            "SELECT invites_enabled FROM guild_settings WHERE guild_id = ?",
            (member.guild.id,)
        )
        if not settings or not settings["invites_enabled"]:
            return
        
        config = await self.get_config(member.guild.id)
        
        # Find who invited this member
        invited = await db.fetchone(
            "SELECT * FROM invited_users WHERE guild_id = ? AND user_id = ?",
            (member.guild.id, member.id)
        )
        
        inviter = None
        if invited:
            inviter = member.guild.get_member(invited["inviter_id"])
            
            # Update leaves count (only if wasn't fake)
            if not invited.get("is_fake"):
                await db.execute(
                    """UPDATE user_invites SET leaves = leaves + 1 
                       WHERE guild_id = ? AND user_id = ?""",
                    (member.guild.id, invited["inviter_id"])
                )
        
        # Send leave message
        if config.get("leave_channel_id"):
            channel = member.guild.get_channel(config["leave_channel_id"])
            if channel:
                await self.send_leave_message(member, inviter, config, channel)
    
    async def send_join_message(
        self, 
        member: discord.Member, 
        inviter: Optional[discord.Member],
        invite_code: Optional[str],
        config: dict,
        channel: discord.TextChannel
    ):
        """Send join message with invite info"""
        if inviter:
            stats = await self.get_user_invites(member.guild.id, inviter.id)
            total = self.calculate_total_invites(stats)
            
            message = config.get("join_message") or (
                "👋 {user} a rejoint le serveur !\n"
                "Invité par {inviter} ({invites} invitations)"
            )
            
            formatted = format_message(
                message,
                user=member.mention,
                inviter=inviter.mention,
                invites=str(total),
                code=invite_code or "inconnu",
                server=member.guild.name
            )
        else:
            message = config.get("join_message_unknown") or (
                "👋 {user} a rejoint le serveur !\n"
                "Impossible de déterminer l'inviteur."
            )
            
            formatted = format_message(
                message,
                user=member.mention,
                server=member.guild.name
            )
        
        embed = create_embed(
            title="👋 Nouveau membre",
            description=formatted,
            color=discord.Color.green(),
            thumbnail=member.display_avatar.url
        )
        embed.set_footer(text=f"Membre #{member.guild.member_count}")
        
        try:
            await channel.send(embed=embed)
        except:
            pass
    
    async def send_leave_message(
        self,
        member: discord.Member,
        inviter: Optional[discord.Member],
        config: dict,
        channel: discord.TextChannel
    ):
        """Send leave message"""
        if inviter:
            stats = await self.get_user_invites(member.guild.id, inviter.id)
            total = self.calculate_total_invites(stats)
            
            message = config.get("leave_message") or (
                "👋 {user} a quitté le serveur.\n"
                "Il avait été invité par {inviter} ({invites} invitations)"
            )
            
            formatted = format_message(
                message,
                user=member.name,
                inviter=inviter.mention,
                invites=str(total),
                server=member.guild.name
            )
        else:
            message = config.get("leave_message_unknown") or (
                "👋 {user} a quitté le serveur."
            )
            
            formatted = format_message(
                message,
                user=member.name,
                server=member.guild.name
            )
        
        embed = create_embed(
            title="👋 Départ",
            description=formatted,
            color=discord.Color.orange(),
            thumbnail=member.display_avatar.url
        )
        
        try:
            await channel.send(embed=embed)
        except:
            pass
    
    async def check_invite_rewards(self, guild: discord.Guild, inviter: discord.Member):
        """Check and give invite rewards"""
        stats = await self.get_user_invites(guild.id, inviter.id)
        total = self.calculate_total_invites(stats)
        
        # Get rewards
        rewards = await db.fetchall(
            """SELECT * FROM invite_rewards 
               WHERE guild_id = ? AND required_invites <= ?
               ORDER BY required_invites DESC""",
            (guild.id, total)
        )
        
        for reward in rewards:
            role = guild.get_role(reward["role_id"])
            if role and role not in inviter.roles and role < guild.me.top_role:
                try:
                    await inviter.add_roles(role, reason=f"Invite reward: {total} invites")
                except:
                    pass
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="invites", aliases=["inv"], invoke_without_command=True)
    async def invites(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche les invitations d'un membre"""
        member = member or ctx.author
        
        stats = await self.get_user_invites(ctx.guild.id, member.id)
        total = self.calculate_total_invites(stats)
        
        embed = create_embed(
            title=f"📨 Invitations de {member.display_name}",
            color=discord.Color.blue(),
            thumbnail=member.display_avatar.url
        )
        
        embed.add_field(
            name="📊 Total",
            value=f"**{total}** invitations",
            inline=False
        )
        
        embed.add_field(
            name="✅ Régulières",
            value=str(stats.get("regular", 0)),
            inline=True
        )
        embed.add_field(
            name="❌ Partis",
            value=str(stats.get("leaves", 0)),
            inline=True
        )
        embed.add_field(
            name="🚫 Fake",
            value=str(stats.get("fake", 0)),
            inline=True
        )
        embed.add_field(
            name="🎁 Bonus",
            value=str(stats.get("bonus", 0)),
            inline=True
        )
        
        await ctx.send(embed=embed)
    
    @invites.command(name="leaderboard", aliases=["lb", "top"])
    async def invites_leaderboard(self, ctx: commands.Context):
        """Affiche le classement des inviteurs"""
        top_inviters = await db.fetchall(
            """SELECT user_id, regular, leaves, fake, bonus,
                      (regular - leaves - fake + bonus) as total
               FROM user_invites 
               WHERE guild_id = ?
               ORDER BY total DESC
               LIMIT 20""",
            (ctx.guild.id,)
        )
        
        if not top_inviters:
            return await ctx.send(embed=info_embed("Aucune invitation enregistrée !"))
        
        description = ""
        for i, row in enumerate(top_inviters, 1):
            member = ctx.guild.get_member(row["user_id"])
            if not member:
                continue
            
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**{i}.**"
            description += f"{medal} {member.mention} - **{row['total']}** invites\n"
        
        embed = create_embed(
            title="🏆 Top Inviteurs",
            description=description or "Aucun inviteur.",
            color=discord.Color.gold()
        )
        
        await ctx.send(embed=embed)
    
    @invites.command(name="who", aliases=["inviter"])
    async def invites_who(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche qui a invité un membre"""
        member = member or ctx.author
        
        invited = await db.fetchone(
            "SELECT * FROM invited_users WHERE guild_id = ? AND user_id = ?",
            (ctx.guild.id, member.id)
        )
        
        if not invited:
            return await ctx.send(embed=info_embed(
                f"Impossible de savoir qui a invité {member.display_name}."
            ))
        
        inviter = ctx.guild.get_member(invited["inviter_id"])
        
        embed = create_embed(
            title=f"📨 Qui a invité {member.display_name} ?",
            color=discord.Color.blue(),
            thumbnail=member.display_avatar.url
        )
        
        if inviter:
            embed.description = f"Invité par {inviter.mention}"
            if invited.get("invite_code"):
                embed.add_field(name="Code", value=f"`{invited['invite_code']}`", inline=True)
        else:
            embed.description = f"Invité par un utilisateur qui a quitté (ID: {invited['inviter_id']})"
        
        await ctx.send(embed=embed)
    
    @invites.command(name="invited", aliases=["list"])
    async def invites_invited(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche les membres invités par quelqu'un"""
        member = member or ctx.author
        
        invited = await db.fetchall(
            """SELECT user_id, joined_at, is_fake FROM invited_users 
               WHERE guild_id = ? AND inviter_id = ?
               ORDER BY joined_at DESC
               LIMIT 20""",
            (ctx.guild.id, member.id)
        )
        
        if not invited:
            return await ctx.send(embed=info_embed(
                f"{member.display_name} n'a invité personne."
            ))
        
        description = ""
        for row in invited:
            user = ctx.guild.get_member(row["user_id"])
            if user:
                status = "🚫" if row.get("is_fake") else "✅"
                description += f"{status} {user.mention}\n"
        
        embed = create_embed(
            title=f"📨 Membres invités par {member.display_name}",
            description=description or "Aucun membre trouvé.",
            color=discord.Color.blue()
        )
        
        await ctx.send(embed=embed)
    
    @invites.command(name="codes")
    async def invites_codes(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche les codes d'invitation d'un membre"""
        member = member or ctx.author
        
        try:
            invites = await ctx.guild.invites()
            user_invites = [inv for inv in invites if inv.inviter and inv.inviter.id == member.id]
            
            if not user_invites:
                return await ctx.send(embed=info_embed(
                    f"{member.display_name} n'a pas de code d'invitation actif."
                ))
            
            description = ""
            for inv in user_invites[:10]:
                description += f"`{inv.code}` - **{inv.uses}** utilisations"
                if inv.max_uses:
                    description += f" / {inv.max_uses}"
                description += "\n"
            
            embed = create_embed(
                title=f"🔗 Codes de {member.display_name}",
                description=description,
                color=discord.Color.blue()
            )
            
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=error_embed("Je n'ai pas la permission de voir les invitations !"))
    
    # ==================== ADMIN COMMANDS ====================
    
    @invites.command(name="add", aliases=["bonus"])
    @commands.has_permissions(administrator=True)
    async def invites_add(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Ajoute des invitations bonus"""
        await db.execute(
            """INSERT INTO user_invites (guild_id, user_id, bonus)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET bonus = bonus + ?""",
            (ctx.guild.id, member.id, amount, amount)
        )
        
        stats = await self.get_user_invites(ctx.guild.id, member.id)
        total = self.calculate_total_invites(stats)
        
        await ctx.send(embed=success_embed(
            f"+{amount} invitations bonus pour {member.mention}\n"
            f"Total: **{total}** invitations"
        ))
        
        # Check rewards
        await self.check_invite_rewards(ctx.guild, member)
    
    @invites.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def invites_remove(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Retire des invitations bonus"""
        await db.execute(
            """UPDATE user_invites SET bonus = bonus - ? 
               WHERE guild_id = ? AND user_id = ?""",
            (amount, ctx.guild.id, member.id)
        )
        
        stats = await self.get_user_invites(ctx.guild.id, member.id)
        total = self.calculate_total_invites(stats)
        
        await ctx.send(embed=success_embed(
            f"-{amount} invitations pour {member.mention}\n"
            f"Total: **{total}** invitations"
        ))
    
    @invites.command(name="reset")
    @commands.has_permissions(administrator=True)
    async def invites_reset(self, ctx: commands.Context, member: discord.Member = None):
        """Reset les invitations d'un membre ou du serveur"""
        if member:
            await db.execute(
                "DELETE FROM user_invites WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, member.id)
            )
            await db.execute(
                "DELETE FROM invited_users WHERE guild_id = ? AND inviter_id = ?",
                (ctx.guild.id, member.id)
            )
            await ctx.send(embed=success_embed(f"Invitations de {member.mention} réinitialisées !"))
        else:
            await db.execute("DELETE FROM user_invites WHERE guild_id = ?", (ctx.guild.id,))
            await db.execute("DELETE FROM invited_users WHERE guild_id = ?", (ctx.guild.id,))
            await ctx.send(embed=success_embed("Toutes les invitations ont été réinitialisées !"))
    
    @invites.group(name="config", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def invites_config(self, ctx: commands.Context):
        """Configure le système d'invitations"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT invites_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        join_channel = ctx.guild.get_channel(config.get("join_channel_id"))
        leave_channel = ctx.guild.get_channel(config.get("leave_channel_id"))
        
        embed = create_embed(
            title="📨 Configuration des invitations",
            color=discord.Color.blue(),
            fields=[
                ("État", "✅ Activé" if settings and settings["invites_enabled"] else "❌ Désactivé", True),
                ("Salon arrivées", join_channel.mention if join_channel else "Non configuré", True),
                ("Salon départs", leave_channel.mention if leave_channel else "Non configuré", True),
                ("Âge minimum compte", f"{config.get('min_account_age') or 7} jours", True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`invites config enable/disable` - Active/désactive
`invites config join #salon` - Salon des arrivées
`invites config leave #salon` - Salon des départs
`invites config age <jours>` - Âge min. du compte (fake)
`invites reward add <invites> @role` - Ajoute une récompense
`invites reward remove <invites>` - Supprime une récompense
`invites reward list` - Liste des récompenses
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @invites_config.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def invites_enable(self, ctx: commands.Context):
        """Active le système d'invitations"""
        await db.execute(
            "UPDATE guild_settings SET invites_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système d'invitations activé !"))
    
    @invites_config.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def invites_disable(self, ctx: commands.Context):
        """Désactive le système d'invitations"""
        await db.execute(
            "UPDATE guild_settings SET invites_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système d'invitations désactivé !"))
    
    @invites_config.command(name="join")
    @commands.has_permissions(administrator=True)
    async def invites_join_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon des arrivées"""
        await self.get_config(ctx.guild.id)
        await db.execute(
            "UPDATE invite_config SET join_channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon des arrivées: {channel.mention}"))
    
    @invites_config.command(name="leave")
    @commands.has_permissions(administrator=True)
    async def invites_leave_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon des départs"""
        await db.execute(
            "UPDATE invite_config SET leave_channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon des départs: {channel.mention}"))
    
    @invites_config.command(name="age")
    @commands.has_permissions(administrator=True)
    async def invites_age(self, ctx: commands.Context, days: int):
        """Définit l'âge minimum du compte (sinon = fake)"""
        if days < 0 or days > 365:
            return await ctx.send(embed=error_embed("L'âge doit être entre 0 et 365 jours !"))
        
        await db.execute(
            "UPDATE invite_config SET min_account_age = ? WHERE guild_id = ?",
            (days, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Âge minimum du compte: {days} jours"))
    
    @invites.group(name="reward", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def invites_reward(self, ctx: commands.Context):
        """Gère les récompenses d'invitations"""
        await self.invites_reward_list(ctx)
    
    @invites_reward.command(name="add")
    @commands.has_permissions(administrator=True)
    async def invites_reward_add(self, ctx: commands.Context, required_invites: int, role: discord.Role):
        """Ajoute une récompense d'invitations"""
        if required_invites < 1:
            return await ctx.send(embed=error_embed("Le nombre d'invitations doit être positif !"))
        
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Je ne peux pas donner ce rôle !"))
        
        await db.execute(
            """INSERT OR REPLACE INTO invite_rewards (guild_id, required_invites, role_id)
               VALUES (?, ?, ?)""",
            (ctx.guild.id, required_invites, role.id)
        )
        
        await ctx.send(embed=success_embed(
            f"Récompense ajoutée: {role.mention} à **{required_invites}** invitations"
        ))
    
    @invites_reward.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def invites_reward_remove(self, ctx: commands.Context, required_invites: int):
        """Supprime une récompense"""
        await db.execute(
            "DELETE FROM invite_rewards WHERE guild_id = ? AND required_invites = ?",
            (ctx.guild.id, required_invites)
        )
        await ctx.send(embed=success_embed(f"Récompense à {required_invites} invitations supprimée !"))
    
    @invites_reward.command(name="list")
    @commands.has_permissions(administrator=True)
    async def invites_reward_list(self, ctx: commands.Context):
        """Liste les récompenses d'invitations"""
        rewards = await db.fetchall(
            "SELECT * FROM invite_rewards WHERE guild_id = ? ORDER BY required_invites ASC",
            (ctx.guild.id,)
        )
        
        if not rewards:
            return await ctx.send(embed=info_embed("Aucune récompense configurée !"))
        
        description = ""
        for reward in rewards:
            role = ctx.guild.get_role(reward["role_id"])
            if role:
                description += f"**{reward['required_invites']}** invites → {role.mention}\n"
        
        embed = create_embed(
            title="🎁 Récompenses d'invitations",
            description=description or "Aucune récompense.",
            color=discord.Color.gold()
        )
        
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Invites(bot))
