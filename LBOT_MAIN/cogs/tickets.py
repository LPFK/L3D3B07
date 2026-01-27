"""
Tickets Cog - Support ticket system with transcripts
"""

import discord
from discord.ext import commands
from discord import app_commands
import time
from io import BytesIO
from typing import Optional

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    format_message, format_datetime, ConfirmView, is_admin
)


class TicketButton(discord.ui.View):
    """Persistent ticket creation button"""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(
        label="Créer un ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket_create"
    )
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle ticket creation button"""
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.create_ticket(interaction)


class TicketControls(discord.ui.View):
    """Controls inside a ticket channel"""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(
        label="Fermer",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_close"
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Close the ticket"""
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.close_ticket_handler(interaction)
    
    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.secondary,
        emoji="🙋",
        custom_id="ticket_claim"
    )
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Claim the ticket"""
        cog = interaction.client.get_cog("Tickets")
        if cog:
            await cog.claim_ticket_handler(interaction)


class Tickets(commands.Cog):
    """Système de tickets de support"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def cog_load(self):
        """Register persistent views"""
        self.bot.add_view(TicketButton())
        self.bot.add_view(TicketControls())
    
    async def get_config(self, guild_id: int) -> dict:
        """Get ticket config"""
        row = await db.fetchone(
            "SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO ticket_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    async def create_ticket(self, interaction: discord.Interaction):
        """Create a new ticket"""
        config = await self.get_config(interaction.guild.id)
        
        # Check if user already has a ticket
        existing = await db.fetchone(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (interaction.guild.id, interaction.user.id)
        )
        
        max_tickets = config.get("max_tickets_per_user", 1)
        user_tickets = await db.fetchall(
            "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (interaction.guild.id, interaction.user.id)
        )
        
        if len(user_tickets) >= max_tickets:
            return await interaction.response.send_message(
                embed=error_embed(f"Tu as déjà {max_tickets} ticket(s) ouvert(s) !"),
                ephemeral=True
            )
        
        await interaction.response.defer(ephemeral=True)
        
        # Get or create category
        category = None
        if config.get("category_id"):
            category = interaction.guild.get_channel(config["category_id"])
        
        # Create ticket channel
        ticket_num = await db.fetchone(
            "SELECT COUNT(*) + 1 as num FROM tickets WHERE guild_id = ?",
            (interaction.guild.id,)
        )
        num = ticket_num["num"] if ticket_num else 1
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                attach_files=True,
                embed_links=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                read_messages=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True
            )
        }
        
        # Add support role
        if config.get("support_role_id"):
            support_role = interaction.guild.get_role(config["support_role_id"])
            if support_role:
                overwrites[support_role] = discord.PermissionOverwrite(
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True
                )
        
        channel = await interaction.guild.create_text_channel(
            name=f"ticket-{num:04d}",
            category=category,
            overwrites=overwrites,
            reason=f"Ticket created by {interaction.user}"
        )
        
        # Save ticket to database
        await db.execute(
            """INSERT INTO tickets (guild_id, channel_id, user_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (interaction.guild.id, channel.id, interaction.user.id, time.time())
        )
        
        # Send welcome message
        welcome_msg = format_message(
            config.get("ticket_message", "Bonjour {user} ! Un membre du staff va vous aider bientôt."),
            user=interaction.user.mention
        )
        
        embed = create_embed(
            title="🎫 Nouveau ticket",
            description=welcome_msg,
            color=discord.Color.green(),
            fields=[
                ("Créé par", interaction.user.mention, True),
                ("Ticket", f"#{num:04d}", True),
            ]
        )
        
        await channel.send(embed=embed, view=TicketControls())
        
        # Ping support role
        if config.get("support_role_id"):
            support_role = interaction.guild.get_role(config["support_role_id"])
            if support_role:
                ping_msg = await channel.send(support_role.mention)
                await ping_msg.delete()
        
        await interaction.followup.send(
            embed=success_embed(f"Ticket créé ! {channel.mention}"),
            ephemeral=True
        )
    
    async def close_ticket_handler(self, interaction: discord.Interaction):
        """Handle ticket close button"""
        ticket = await db.fetchone(
            "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'",
            (interaction.channel.id,)
        )
        
        if not ticket:
            return await interaction.response.send_message(
                embed=error_embed("Ce n'est pas un ticket !"),
                ephemeral=True
            )
        
        # Confirm close
        view = ConfirmView(interaction.user.id)
        await interaction.response.send_message(
            embed=info_embed("Es-tu sûr de vouloir fermer ce ticket ?"),
            view=view
        )
        
        await view.wait()
        
        if view.value:
            await self.close_ticket(interaction.channel, interaction.user, ticket)
        else:
            await interaction.followup.send(
                embed=info_embed("Fermeture annulée."),
                ephemeral=True
            )
    
    async def claim_ticket_handler(self, interaction: discord.Interaction):
        """Handle ticket claim button"""
        config = await self.get_config(interaction.guild.id)
        
        # Check if user is support
        if config.get("support_role_id"):
            support_role = interaction.guild.get_role(config["support_role_id"])
            if support_role and support_role not in interaction.user.roles:
                if not interaction.user.guild_permissions.administrator:
                    return await interaction.response.send_message(
                        embed=error_embed("Tu n'as pas la permission de claim ce ticket !"),
                        ephemeral=True
                    )
        
        await interaction.channel.edit(
            name=f"{interaction.channel.name}-{interaction.user.name[:10]}"
        )
        
        await interaction.response.send_message(
            embed=success_embed(f"{interaction.user.mention} a pris en charge ce ticket !")
        )
    
    async def close_ticket(
        self,
        channel: discord.TextChannel,
        closed_by: discord.Member,
        ticket: dict
    ):
        """Close a ticket and save transcript"""
        config = await self.get_config(channel.guild.id)
        
        # Update database
        await db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = ?, closed_by = ? WHERE channel_id = ?",
            (time.time(), closed_by.id, channel.id)
        )
        
        # Create transcript
        if config.get("transcript_enabled"):
            transcript = await self.create_transcript(channel)
            
            # Send to log channel
            if config.get("log_channel_id"):
                log_channel = channel.guild.get_channel(config["log_channel_id"])
                if log_channel:
                    user = channel.guild.get_member(ticket["user_id"])
                    
                    embed = create_embed(
                        title="🎫 Ticket fermé",
                        color=discord.Color.red(),
                        fields=[
                            ("Ticket", channel.name, True),
                            ("Créé par", user.mention if user else f"ID: {ticket['user_id']}", True),
                            ("Fermé par", closed_by.mention, True),
                            ("Créé le", format_datetime(ticket["created_at"]), True),
                            ("Fermé le", format_datetime(time.time()), True),
                        ]
                    )
                    
                    file = discord.File(
                        BytesIO(transcript.encode()),
                        filename=f"{channel.name}-transcript.txt"
                    )
                    
                    await log_channel.send(embed=embed, file=file)
        
        # Delete channel
        await channel.delete(reason=f"Ticket closed by {closed_by}")
    
    async def create_transcript(self, channel: discord.TextChannel) -> str:
        """Create a text transcript of the ticket"""
        messages = []
        async for message in channel.history(limit=500, oldest_first=True):
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = message.content or "[Embed/Attachment]"
            messages.append(f"[{timestamp}] {message.author}: {content}")
        
        header = f"Transcript for {channel.name}\n"
        header += f"Created: {format_datetime(time.time())}\n"
        header += "=" * 50 + "\n\n"
        
        return header + "\n".join(messages)
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="ticket", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def ticket(self, ctx: commands.Context):
        """Configure le système de tickets"""
        config = await self.get_config(ctx.guild.id)
        settings = await db.fetchone(
            "SELECT tickets_enabled FROM guild_settings WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        
        category = ctx.guild.get_channel(config.get("category_id"))
        log_channel = ctx.guild.get_channel(config.get("log_channel_id"))
        support_role = ctx.guild.get_role(config.get("support_role_id"))
        
        open_tickets = await db.fetchone(
            "SELECT COUNT(*) as count FROM tickets WHERE guild_id = ? AND status = 'open'",
            (ctx.guild.id,)
        )
        
        embed = create_embed(
            title="🎫 Configuration des tickets",
            color=discord.Color.blue(),
            fields=[
                ("État", "✅ Activé" if settings and settings["tickets_enabled"] else "❌ Désactivé", True),
                ("Tickets ouverts", str(open_tickets["count"]) if open_tickets else "0", True),
                ("Catégorie", category.name if category else "Non configurée", True),
                ("Salon de logs", log_channel.mention if log_channel else "Non configuré", True),
                ("Rôle support", support_role.mention if support_role else "Non configuré", True),
                ("Max par utilisateur", str(config.get("max_tickets_per_user", 1)), True),
            ]
        )
        
        embed.add_field(
            name="📝 Commandes",
            value="""
`ticket enable/disable` - Active/désactive
`ticket setup` - Envoie le panneau de création
`ticket category <catégorie>` - Catégorie des tickets
`ticket log #salon` - Salon des transcripts
`ticket role @role` - Rôle support
`ticket message <message>` - Message d'accueil
`ticket close` - Ferme un ticket manuellement
            """,
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @ticket.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def ticket_enable(self, ctx: commands.Context):
        """Active le système de tickets"""
        await db.execute(
            "UPDATE guild_settings SET tickets_enabled = 1 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système de tickets activé !"))
    
    @ticket.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def ticket_disable(self, ctx: commands.Context):
        """Désactive le système de tickets"""
        await db.execute(
            "UPDATE guild_settings SET tickets_enabled = 0 WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        await ctx.send(embed=success_embed("Système de tickets désactivé !"))
    
    @ticket.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def ticket_setup(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """Envoie le panneau de création de tickets"""
        channel = channel or ctx.channel
        
        embed = create_embed(
            title="🎫 Support",
            description="Clique sur le bouton ci-dessous pour ouvrir un ticket de support.\n\n"
                       "Un membre du staff te répondra dès que possible !",
            color=discord.Color.blue()
        )
        
        await channel.send(embed=embed, view=TicketButton())
        await ctx.send(embed=success_embed(f"Panneau de tickets envoyé dans {channel.mention} !"))
    
    @ticket.command(name="category")
    @commands.has_permissions(administrator=True)
    async def ticket_category(self, ctx: commands.Context, category: discord.CategoryChannel):
        """Définit la catégorie des tickets"""
        await db.execute(
            "UPDATE ticket_config SET category_id = ? WHERE guild_id = ?",
            (category.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Catégorie définie: **{category.name}**"))
    
    @ticket.command(name="log")
    @commands.has_permissions(administrator=True)
    async def ticket_log(self, ctx: commands.Context, channel: discord.TextChannel):
        """Définit le salon des transcripts"""
        await db.execute(
            "UPDATE ticket_config SET log_channel_id = ? WHERE guild_id = ?",
            (channel.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Salon de logs: {channel.mention}"))
    
    @ticket.command(name="role")
    @commands.has_permissions(administrator=True)
    async def ticket_role(self, ctx: commands.Context, role: discord.Role):
        """Définit le rôle support"""
        await db.execute(
            "UPDATE ticket_config SET support_role_id = ? WHERE guild_id = ?",
            (role.id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Rôle support: {role.mention}"))
    
    @ticket.command(name="message")
    @commands.has_permissions(administrator=True)
    async def ticket_message(self, ctx: commands.Context, *, message: str):
        """Définit le message d'accueil"""
        await db.execute(
            "UPDATE ticket_config SET ticket_message = ? WHERE guild_id = ?",
            (message, ctx.guild.id)
        )
        await ctx.send(embed=success_embed("Message d'accueil défini !"))
    
    @ticket.command(name="close")
    async def ticket_close(self, ctx: commands.Context):
        """Ferme le ticket actuel"""
        ticket = await db.fetchone(
            "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'",
            (ctx.channel.id,)
        )
        
        if not ticket:
            return await ctx.send(embed=error_embed("Ce n'est pas un ticket !"))
        
        config = await self.get_config(ctx.guild.id)
        
        # Check permission
        if ctx.author.id != ticket["user_id"]:
            if config.get("support_role_id"):
                support_role = ctx.guild.get_role(config["support_role_id"])
                if support_role and support_role not in ctx.author.roles:
                    if not ctx.author.guild_permissions.administrator:
                        return await ctx.send(embed=error_embed("Tu n'as pas la permission !"))
        
        view = ConfirmView(ctx.author.id)
        msg = await ctx.send(
            embed=info_embed("Es-tu sûr de vouloir fermer ce ticket ?"),
            view=view
        )
        
        await view.wait()
        
        if view.value:
            await self.close_ticket(ctx.channel, ctx.author, ticket)
        else:
            await msg.edit(embed=info_embed("Fermeture annulée."), view=None)
    
    @ticket.command(name="add")
    @commands.has_permissions(manage_channels=True)
    async def ticket_add(self, ctx: commands.Context, member: discord.Member):
        """Ajoute un membre au ticket"""
        ticket = await db.fetchone(
            "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'",
            (ctx.channel.id,)
        )
        
        if not ticket:
            return await ctx.send(embed=error_embed("Ce n'est pas un ticket !"))
        
        await ctx.channel.set_permissions(
            member,
            read_messages=True,
            send_messages=True,
            attach_files=True
        )
        
        await ctx.send(embed=success_embed(f"{member.mention} a été ajouté au ticket !"))
    
    @ticket.command(name="remove")
    @commands.has_permissions(manage_channels=True)
    async def ticket_remove(self, ctx: commands.Context, member: discord.Member):
        """Retire un membre du ticket"""
        ticket = await db.fetchone(
            "SELECT * FROM tickets WHERE channel_id = ? AND status = 'open'",
            (ctx.channel.id,)
        )
        
        if not ticket:
            return await ctx.send(embed=error_embed("Ce n'est pas un ticket !"))
        
        if member.id == ticket["user_id"]:
            return await ctx.send(embed=error_embed("Tu ne peux pas retirer le créateur du ticket !"))
        
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.send(embed=success_embed(f"{member.mention} a été retiré du ticket !"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Tickets(bot))
