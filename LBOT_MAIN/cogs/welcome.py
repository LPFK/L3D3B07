"""
Cog Welcome - messages bienvenue/aurevoir, auto-roles, DM
"""

import discord
from discord.ext import commands
from discord import app_commands
import json
from typing import Optional

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    format_message, is_admin
)


class Welcome(commands.Cog):
    """Systeme de bienvenue"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def get_config(self, guild_id: int) -> dict:
        row = await db.fetchone(
            "SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO welcome_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Handle member join"""
        if member.bot:
            return
        
        # Check if welcome is enabled
        settings = await db.fetchone(
            "SELECT welcome_enabled FROM guild_settings WHERE guild_id = ?",
            (member.guild.id,)
        )
        if not settings or not settings["welcome_enabled"]:
            return
        
        config = await self.get_config(member.guild.id)
        
        # Send welcome message
        channel_id = config.get("welcome_channel_id")
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                message = format_message(
                    config.get("welcome_message", "Bienvenue {user} sur **{server}** ! 🎉"),
                    user=member.mention,
                    server=member.guild.name,
                    guild=member.guild
                )
                
                if config.get("welcome_embed"):
                    embed = create_embed(
                        title="👋 Bienvenue !",
                        description=message,
                        color=discord.Color.green(),
                        thumbnail=member.display_avatar.url
                    )
                    embed.set_footer(text=f"Membre #{member.guild.member_count}")
                    
                    if config.get("welcome_image_url"):
                        embed.set_image(url=config["welcome_image_url"])
                    
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
                else:
                    try:
                        await channel.send(message)
                    except discord.Forbidden:
                        pass
        
        # Send DM
        if config.get("dm_enabled") and config.get("dm_message"):
            dm_message = format_message(
                config["dm_message"],
                user=member.name,
                server=member.guild.name,
                guild=member.guild
            )
            try:
                await member.send(dm_message)
            except discord.Forbidden:
                pass
        
        # Auto-roles
        auto_roles = await db.fetchall(
            "SELECT role_id FROM auto_roles WHERE guild_id = ?",
            (member.guild.id,)
        )
        
        roles_to_add = []
        for row in auto_roles:
            role = member.guild.get_role(row["role_id"])
            if role and role < member.guild.me.top_role:
                roles_to_add.append(role)
        
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Auto-role on join")
            except discord.Forbidden:
                pass
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Handle member leave"""
        if member.bot:
            return
        
        settings = await db.fetchone(
            "SELECT welcome_enabled FROM guild_settings WHERE guild_id = ?",
            (member.guild.id,)
        )
        if not settings or not settings["welcome_enabled"]:
            return
        
        config = await self.get_config(member.guild.id)
        
        channel_id = config.get("goodbye_channel_id")
        if channel_id:
            channel = member.guild.get_channel(channel_id)
            if channel:
                message = format_message(
                    config.get("goodbye_message", "Au revoir {user} ! 👋"),
                    user=member.name,
                    server=member.guild.name,
                    guild=member.guild
                )
                
                if config.get("goodbye_embed"):
                    embed = create_embed(
                        title="👋 Au revoir...",
                        description=message,
                        color=discord.Color.orange(),
                        thumbnail=member.display_avatar.url
                    )
                    
                    if config.get("goodbye_image_url"):
                        embed.set_image(url=config["goodbye_image_url"])
                    
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
                else:
                    try:
                        await channel.send(message)
                    except discord.Forbidden:
                        pass
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="welcome", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def welcome(self, ctx: commands.Context):
        """Configure le système de bienvenue"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT welcome_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        welcome_channel = ctx.guild.get_channel(config.get("welcome_channel_id"))
        goodbye_channel = ctx.guild.get_channel(config.get("goodbye_channel_id"))
        
        auto_roles = await db.fetchall(
            "SELECT role_id FROM auto_roles WHERE guild_id = ?", (ctx.guild.id,)
        )
        roles_text = ", ".join(
            ctx.guild.get_role(r["role_id"]).mention 
            for r in auto_roles 
            if ctx.guild.get_role(r["role_id"])
        ) or "Aucun"
        
        embed = create_embed(
            title="👋 Configuration de bienvenue",
            color=discord.Color.green(),
            fields=[
                ("État", "✅ Activé" if settings and settings["welcome_enabled"] else "❌ Désactivé", True),
                ("Salon bienvenue", welcome_channel.mention if welcome_channel else "Non configuré", True),
                ("Salon départ", goodbye_channel.mention if goodbye_channel else "Non configuré", True),
                ("Message bienvenue", f"```{config.get('welcome_message', 'Non défini')[:100]}```", False),
                ("Message départ", f"```{config.get('goodbye_message', 'Non défini')[:100]}```", False),
                ("Auto-rôles", roles_text, False),
                ("DM activé", "✅ Oui" if config.get("dm_enabled") else "❌ Non", True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`welcome enable/disable` - Active/désactive
`welcome channel #salon` - Salon de bienvenue
`welcome message <message>` - Message de bienvenue
`welcome goodbye channel #salon` - Salon de départ
`welcome goodbye message <message>` - Message de départ
`welcome autorole add/remove @role` - Gère les auto-rôles
`welcome dm enable/disable` - Active/désactive les DM
`welcome dm message <message>` - Message DM
`welcome test` - Teste les messages
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @welcome.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def welcome_enable(self, ctx: commands.Context):
        """Active le système de bienvenue"""
        await db.execute(
            "UPDATE guild_settings SET welcome_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système de bienvenue activé !"))
    
    @welcome.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def welcome_disable(self, ctx: commands.Context):
        """Désactive le système de bienvenue"""
        await db.execute(
            "UPDATE guild_settings SET welcome_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système de bienvenue désactivé !"))
    
    @welcome.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def welcome_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon de bienvenue"""
        await db.execute(
            "UPDATE welcome_config SET welcome_channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon de bienvenue: {channel.mention}"))
    
    @welcome.command(name="message")
    @commands.has_permissions(administrator=True)
    async def welcome_message(self, ctx: commands.Context, *, message: str):
        """Définit le message de bienvenue"""
        await db.execute(
            "UPDATE welcome_config SET welcome_message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        
        preview = format_message(message, user=ctx.author.mention, server=ctx.guild.name, guild=ctx.guild)
        await ctx.send(embed=success_embed(
            f"Message de bienvenue défini !\n\n**Aperçu:**\n{preview}"
        ))
    
    @welcome.command(name="image")
    @commands.has_permissions(administrator=True)
    async def welcome_image(self, ctx: commands.Context, url: str = None):
        """Définit l'image de bienvenue"""
        await db.execute(
            "UPDATE welcome_config SET welcome_image_url = ? WHERE guild_id = ?",
            (url, ctx.guild.id)
        )
        
        if url:
            await ctx.send(embed=success_embed("Image de bienvenue définie !"))
        else:
            await ctx.send(embed=success_embed("Image de bienvenue supprimée !"))
    
    @welcome.group(name="goodbye", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def goodbye(self, ctx: commands.Context):
        """Configure les messages de départ"""
        await ctx.send_help(ctx.command)
    
    @goodbye.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def goodbye_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon de départ"""
        await db.execute(
            "UPDATE welcome_config SET goodbye_channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon de départ: {channel.mention}"))
    
    @goodbye.command(name="message")
    @commands.has_permissions(administrator=True)
    async def goodbye_message(self, ctx: commands.Context, *, message: str):
        """Définit le message de départ"""
        await db.execute(
            "UPDATE welcome_config SET goodbye_message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        
        preview = format_message(message, user=ctx.author.name, server=ctx.guild.name, guild=ctx.guild)
        await ctx.send(embed=success_embed(
            f"Message de départ défini !\n\n**Aperçu:**\n{preview}"
        ))
    
    @welcome.group(name="autorole", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def autorole(self, ctx: commands.Context):
        """Gère les auto-rôles"""
        auto_roles = await db.fetchall(
            "SELECT role_id FROM auto_roles WHERE guild_id = ?", (ctx.guild.id,)
        )
        
        if not auto_roles:
            return await ctx.send(embed=info_embed("Aucun auto-rôle configuré !"))
        
        roles_text = "\n".join(
            f"• {ctx.guild.get_role(r['role_id']).mention}" 
            for r in auto_roles 
            if ctx.guild.get_role(r["role_id"])
        )
        
        embed = create_embed(
            title="🎭 Auto-rôles",
            description=roles_text,
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
    
    @autorole.command(name="add")
    @commands.has_permissions(administrator=True)
    async def autorole_add(self, ctx: commands.Context, role: discord.Role):
        """Ajoute un auto-rôle"""
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=error_embed("Je ne peux pas donner ce rôle !"))
        
        await db.execute(
            "INSERT OR IGNORE INTO auto_roles (guild_id, role_id) VALUES (?, ?)",
            (ctx.guild.id, role.id)
        )
        await ctx.send(embed=success_embed(f"Auto-rôle {role.mention} ajouté !"))
    
    @autorole.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def autorole_remove(self, ctx: commands.Context, role: discord.Role):
        """Supprime un auto-rôle"""
        await db.execute(
            "DELETE FROM auto_roles WHERE guild_id = ? AND role_id = ?",
            (ctx.guild.id, role.id)
        )
        await ctx.send(embed=success_embed(f"Auto-rôle {role.mention} supprimé !"))
    
    @welcome.group(name="dm", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def dm(self, ctx: commands.Context):
        """Configure les DM de bienvenue"""
        config = await self.get_config(ctx.guild.id)
        
        embed = create_embed(
            title="📬 DM de bienvenue",
            fields=[
                ("État", "✅ Activé" if config.get("dm_enabled") else "❌ Désactivé", True),
                ("Message", f"```{config.get('dm_message', 'Non défini')[:100]}```", False),
            ]
        )
        await ctx.send(embed=embed)
    
    @dm.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def dm_enable(self, ctx: commands.Context):
        """Active les DM de bienvenue"""
        await db.execute(
            "UPDATE welcome_config SET dm_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("DM de bienvenue activés !"))
    
    @dm.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def dm_disable(self, ctx: commands.Context):
        """Désactive les DM de bienvenue"""
        await db.execute(
            "UPDATE welcome_config SET dm_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("DM de bienvenue désactivés !"))
    
    @dm.command(name="message")
    @commands.has_permissions(administrator=True)
    async def dm_message_cmd(self, ctx: commands.Context, *, message: str):
        """Définit le message DM"""
        await db.execute(
            "UPDATE welcome_config SET dm_message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        await ctx.send(embed=success_embed("Message DM défini !"))
    
    @welcome.command(name="test")
    @commands.has_permissions(administrator=True)
    async def welcome_test(self, ctx: commands.Context):
        """Teste les messages de bienvenue et départ"""
        # Simulate join
        self.bot.dispatch("member_join", ctx.author)
        await ctx.send(embed=info_embed("Test de bienvenue envoyé ! Vérifie le salon configuré."))


async def setup(bot: commands.Bot):
    await bot.add_cog(Welcome(bot))
