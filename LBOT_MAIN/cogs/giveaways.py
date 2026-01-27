"""
Giveaways Cog - Système de giveaways avec participation par réaction
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
import asyncio
from typing import Optional, List

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed,
    parse_duration, format_duration, format_relative_time,
    is_admin
)


class GiveawayView(discord.ui.View):
    """Persistent view for giveaway participation"""
    
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(
        label="Participer",
        style=discord.ButtonStyle.primary,
        emoji="🎉",
        custom_id="giveaway_enter"
    )
    async def enter_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle giveaway entry"""
        cog = interaction.client.get_cog("Giveaways")
        if cog:
            await cog.handle_entry(interaction)


class Giveaways(commands.Cog):
    """Système de giveaways"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    async def cog_load(self):
        """Start background task and register view"""
        self.bot.add_view(GiveawayView())
        self.check_giveaways.start()
    
    async def cog_unload(self):
        """Stop background task"""
        self.check_giveaways.cancel()
    
    @tasks.loop(seconds=30)
    async def check_giveaways(self):
        """Check for ended giveaways"""
        try:
            ended = await db.fetchall(
                """SELECT * FROM giveaways 
                   WHERE ended = 0 AND end_time <= ?""",
                (time.time(),)
            )
            
            for giveaway in ended:
                await self.end_giveaway(giveaway)
        except Exception as e:
            print(f"Error checking giveaways: {e}")
    
    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()
    
    async def handle_entry(self, interaction: discord.Interaction):
        """Handle a user entering a giveaway"""
        # Get giveaway
        giveaway = await db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND ended = 0",
            (interaction.message.id,)
        )
        
        if not giveaway:
            return await interaction.response.send_message(
                embed=error_embed("Ce giveaway est terminé !"),
                ephemeral=True
            )
        
        # Check requirements
        if giveaway["required_role_id"]:
            role = interaction.guild.get_role(giveaway["required_role_id"])
            if role and role not in interaction.user.roles:
                return await interaction.response.send_message(
                    embed=error_embed(f"Tu dois avoir le rôle {role.mention} pour participer !"),
                    ephemeral=True
                )
        
        if giveaway["required_level"]:
            user_level = await db.fetchone(
                "SELECT level FROM user_levels WHERE guild_id = ? AND user_id = ?",
                (interaction.guild.id, interaction.user.id)
            )
            level = user_level["level"] if user_level else 0
            if level < giveaway["required_level"]:
                return await interaction.response.send_message(
                    embed=error_embed(f"Tu dois être niveau {giveaway['required_level']} minimum !"),
                    ephemeral=True
                )
        
        # Check if already entered
        existing = await db.fetchone(
            "SELECT * FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
            (giveaway["id"], interaction.user.id)
        )
        
        if existing:
            # Remove entry
            await db.execute(
                "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?",
                (giveaway["id"], interaction.user.id)
            )
            await interaction.response.send_message(
                embed=info_embed("Tu ne participes plus au giveaway."),
                ephemeral=True
            )
        else:
            # Add entry
            await db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id, entered_at) VALUES (?, ?, ?)",
                (giveaway["id"], interaction.user.id, time.time())
            )
            await interaction.response.send_message(
                embed=success_embed("Tu participes au giveaway ! 🎉"),
                ephemeral=True
            )
        
        # Update participant count
        await self.update_giveaway_message(giveaway)
    
    async def update_giveaway_message(self, giveaway: dict):
        """Update the giveaway embed with current participant count"""
        try:
            guild = self.bot.get_guild(giveaway["guild_id"])
            if not guild:
                return
            
            channel = guild.get_channel(giveaway["channel_id"])
            if not channel:
                return
            
            message = await channel.fetch_message(giveaway["message_id"])
            if not message:
                return
            
            # Count participants
            count = await db.fetchone(
                "SELECT COUNT(*) as count FROM giveaway_entries WHERE giveaway_id = ?",
                (giveaway["id"],)
            )
            participant_count = count["count"] if count else 0
            
            # Build embed
            embed = self.create_giveaway_embed(giveaway, participant_count)
            await message.edit(embed=embed)
        except Exception as e:
            print(f"Error updating giveaway message: {e}")
    
    def create_giveaway_embed(self, giveaway: dict, participant_count: int = 0, ended: bool = False, winners: List[discord.Member] = None):
        """Create the giveaway embed"""
        if ended:
            if winners:
                winners_text = ", ".join(w.mention for w in winners)
                description = f"**Prix:** {giveaway['prize']}\n\n🏆 **Gagnant(s):** {winners_text}"
            else:
                description = f"**Prix:** {giveaway['prize']}\n\n😢 Aucun participant valide."
            
            embed = create_embed(
                title="🎉 Giveaway terminé !",
                description=description,
                color=discord.Color.dark_grey()
            )
        else:
            time_left = giveaway["end_time"] - time.time()
            
            description = f"**Prix:** {giveaway['prize']}\n\n"
            description += f"⏰ **Fin:** {format_relative_time(giveaway['end_time'])}\n"
            description += f"👥 **Participants:** {participant_count}\n"
            description += f"🏆 **Gagnants:** {giveaway['winner_count']}"
            
            requirements = []
            if giveaway.get("required_role_id"):
                requirements.append(f"Rôle requis: <@&{giveaway['required_role_id']}>")
            if giveaway.get("required_level"):
                requirements.append(f"Niveau requis: {giveaway['required_level']}")
            
            if requirements:
                description += f"\n\n📋 **Conditions:**\n" + "\n".join(requirements)
            
            embed = create_embed(
                title="🎉 GIVEAWAY",
                description=description,
                color=discord.Color.gold()
            )
        
        embed.set_footer(text=f"Organisé par {giveaway.get('host_name', 'Inconnu')}")
        return embed
    
    async def end_giveaway(self, giveaway: dict):
        """End a giveaway and select winners"""
        try:
            guild = self.bot.get_guild(giveaway["guild_id"])
            if not guild:
                return
            
            channel = guild.get_channel(giveaway["channel_id"])
            if not channel:
                return
            
            # Get all entries
            entries = await db.fetchall(
                "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?",
                (giveaway["id"],)
            )
            
            # Filter valid participants (still in server)
            valid_users = []
            for entry in entries:
                member = guild.get_member(entry["user_id"])
                if member:
                    valid_users.append(member)
            
            # Select winners
            winner_count = min(giveaway["winner_count"], len(valid_users))
            winners = random.sample(valid_users, winner_count) if valid_users else []
            
            # Update database
            await db.execute(
                "UPDATE giveaways SET ended = 1 WHERE id = ?",
                (giveaway["id"],)
            )
            
            # Store winners
            for winner in winners:
                await db.execute(
                    """INSERT OR REPLACE INTO giveaway_entries 
                       (giveaway_id, user_id, entered_at, won)
                       VALUES (?, ?, ?, 1)""",
                    (giveaway["id"], winner.id, time.time())
                )
            
            # Update message
            try:
                message = await channel.fetch_message(giveaway["message_id"])
                embed = self.create_giveaway_embed(giveaway, len(entries), ended=True, winners=winners)
                await message.edit(embed=embed, view=None)
            except:
                pass
            
            # Announce winners
            if winners:
                winners_mention = ", ".join(w.mention for w in winners)
                await channel.send(
                    f"🎉 Félicitations {winners_mention} ! Vous avez gagné **{giveaway['prize']}** !"
                )
            else:
                await channel.send(
                    embed=info_embed(f"Le giveaway pour **{giveaway['prize']}** s'est terminé sans participant.")
                )
        except Exception as e:
            print(f"Error ending giveaway: {e}")
    
    # ==================== COMMANDS ====================
    
    @commands.group(name="giveaway", aliases=["gw"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def giveaway(self, ctx: commands.Context):
        """Gère les giveaways"""
        embed = create_embed(
            title="🎉 Giveaways",
            description="Système de giveaways avec participation par bouton.",
            color=discord.Color.gold(),
            fields=[
                ("Créer un giveaway", "`giveaway start <durée> <gagnants> <prix>`\nEx: `giveaway start 1d 1 Nitro`", False),
                ("Terminer maintenant", "`giveaway end <message_id>`", False),
                ("Relancer", "`giveaway reroll <message_id>`", False),
                ("Annuler", "`giveaway cancel <message_id>`", False),
                ("Liste", "`giveaway list`", False),
            ]
        )
        await ctx.send(embed=embed)
    
    @giveaway.command(name="start", aliases=["create"])
    @commands.has_permissions(manage_guild=True)
    async def giveaway_start(
        self, 
        ctx: commands.Context, 
        duration: str,
        winners: int,
        *, 
        prize: str
    ):
        """Démarre un giveaway
        
        Exemples:
        - !giveaway start 1d 1 Nitro Classic
        - !giveaway start 12h 3 100€ de games
        """
        # Parse duration
        seconds = parse_duration(duration)
        if not seconds or seconds < 60:
            return await ctx.send(embed=error_embed("Durée invalide ! (minimum 1 minute)"))
        
        if winners < 1 or winners > 20:
            return await ctx.send(embed=error_embed("Le nombre de gagnants doit être entre 1 et 20 !"))
        
        end_time = time.time() + seconds
        
        # Create giveaway data
        giveaway_data = {
            "guild_id": ctx.guild.id,
            "channel_id": ctx.channel.id,
            "prize": prize,
            "winner_count": winners,
            "end_time": end_time,
            "host_name": str(ctx.author),
            "host_id": ctx.author.id
        }
        
        # Create embed
        embed = self.create_giveaway_embed(giveaway_data, 0)
        
        # Send message
        msg = await ctx.send(embed=embed, view=GiveawayView())
        
        # Save to database
        await db.execute(
            """INSERT INTO giveaways 
               (guild_id, channel_id, message_id, prize, winner_count, 
                host_id, end_time, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (ctx.guild.id, ctx.channel.id, msg.id, prize, winners,
             ctx.author.id, end_time, time.time())
        )
        
        # Store host name for display
        giveaway = await db.fetchone(
            "SELECT id FROM giveaways WHERE message_id = ?", (msg.id,)
        )
        
        # Delete command message
        try:
            await ctx.message.delete()
        except:
            pass
    
    @giveaway.command(name="end")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx: commands.Context, message_id: int):
        """Termine un giveaway immédiatement"""
        giveaway = await db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ? AND ended = 0",
            (message_id, ctx.guild.id)
        )
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Giveaway non trouvé ou déjà terminé !"))
        
        await self.end_giveaway(giveaway)
        await ctx.send(embed=success_embed("Giveaway terminé !"))
    
    @giveaway.command(name="reroll")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, ctx: commands.Context, message_id: int, count: int = 1):
        """Relance le tirage pour un giveaway terminé"""
        giveaway = await db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ? AND ended = 1",
            (message_id, ctx.guild.id)
        )
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Giveaway non trouvé ou pas encore terminé !"))
        
        # Get entries (excluding previous winners)
        entries = await db.fetchall(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ? AND (won IS NULL OR won = 0)",
            (giveaway["id"],)
        )
        
        # Filter valid participants
        valid_users = []
        for entry in entries:
            member = ctx.guild.get_member(entry["user_id"])
            if member:
                valid_users.append(member)
        
        if not valid_users:
            return await ctx.send(embed=error_embed("Aucun participant éligible pour le reroll !"))
        
        # Select new winners
        winner_count = min(count, len(valid_users))
        winners = random.sample(valid_users, winner_count)
        
        winners_mention = ", ".join(w.mention for w in winners)
        await ctx.send(
            f"🎉 Nouveau(x) gagnant(s) : {winners_mention} pour **{giveaway['prize']}** !"
        )
    
    @giveaway.command(name="cancel")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_cancel(self, ctx: commands.Context, message_id: int):
        """Annule un giveaway"""
        giveaway = await db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ? AND ended = 0",
            (message_id, ctx.guild.id)
        )
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Giveaway non trouvé ou déjà terminé !"))
        
        # Delete from database
        await db.execute("DELETE FROM giveaway_entries WHERE giveaway_id = ?", (giveaway["id"],))
        await db.execute("DELETE FROM giveaways WHERE id = ?", (giveaway["id"],))
        
        # Try to delete/edit message
        try:
            channel = ctx.guild.get_channel(giveaway["channel_id"])
            if channel:
                message = await channel.fetch_message(giveaway["message_id"])
                embed = create_embed(
                    title="🎉 Giveaway annulé",
                    description=f"~~{giveaway['prize']}~~\n\nCe giveaway a été annulé.",
                    color=discord.Color.red()
                )
                await message.edit(embed=embed, view=None)
        except:
            pass
        
        await ctx.send(embed=success_embed("Giveaway annulé !"))
    
    @giveaway.command(name="list")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_list(self, ctx: commands.Context):
        """Liste les giveaways actifs"""
        giveaways = await db.fetchall(
            "SELECT * FROM giveaways WHERE guild_id = ? AND ended = 0 ORDER BY end_time ASC",
            (ctx.guild.id,)
        )
        
        if not giveaways:
            return await ctx.send(embed=info_embed("Aucun giveaway actif !"))
        
        description = ""
        for gw in giveaways[:10]:
            channel = ctx.guild.get_channel(gw["channel_id"])
            channel_mention = channel.mention if channel else "Inconnu"
            description += f"**{gw['prize']}**\n"
            description += f"├ Salon: {channel_mention}\n"
            description += f"├ Fin: {format_relative_time(gw['end_time'])}\n"
            description += f"└ ID: `{gw['message_id']}`\n\n"
        
        embed = create_embed(
            title="🎉 Giveaways actifs",
            description=description,
            color=discord.Color.gold()
        )
        await ctx.send(embed=embed)
    
    @giveaway.command(name="require")
    @commands.has_permissions(manage_guild=True)
    async def giveaway_require(
        self, 
        ctx: commands.Context, 
        message_id: int,
        requirement_type: str,
        value: str
    ):
        """Ajoute une condition à un giveaway
        
        Types: role, level
        Ex: !giveaway require 123456 role @VIP
        Ex: !giveaway require 123456 level 10
        """
        giveaway = await db.fetchone(
            "SELECT * FROM giveaways WHERE message_id = ? AND guild_id = ? AND ended = 0",
            (message_id, ctx.guild.id)
        )
        
        if not giveaway:
            return await ctx.send(embed=error_embed("Giveaway non trouvé !"))
        
        if requirement_type.lower() == "role":
            # Parse role
            try:
                role = await commands.RoleConverter().convert(ctx, value)
                await db.execute(
                    "UPDATE giveaways SET required_role_id = ? WHERE id = ?",
                    (role.id, giveaway["id"])
                )
                await ctx.send(embed=success_embed(f"Rôle requis: {role.mention}"))
            except:
                return await ctx.send(embed=error_embed("Rôle invalide !"))
        
        elif requirement_type.lower() == "level":
            try:
                level = int(value)
                await db.execute(
                    "UPDATE giveaways SET required_level = ? WHERE id = ?",
                    (level, giveaway["id"])
                )
                await ctx.send(embed=success_embed(f"Niveau requis: {level}"))
            except:
                return await ctx.send(embed=error_embed("Niveau invalide !"))
        else:
            await ctx.send(embed=error_embed("Type invalide ! Utilise `role` ou `level`."))
        
        # Update message
        giveaway = await db.fetchone("SELECT * FROM giveaways WHERE id = ?", (giveaway["id"],))
        await self.update_giveaway_message(giveaway)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
