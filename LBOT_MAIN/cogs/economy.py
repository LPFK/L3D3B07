"""
Economy Cog - Currency system, shop, daily rewards, work, gambling
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import json
import random
from typing import Optional

from utils.database import db
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed, warning_embed,
    format_duration, Paginator, ConfirmView, is_admin
)


class Economy(commands.Cog):
    """Système d'économie et de monnaie"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_tracking: dict[tuple[int, int], float] = {}
    
    async def cog_load(self):
        self.voice_money_task.start()
    l
    async def cog_unload(self):
        self.voice_money_task.cancel()
    
    async def get_config(self, guild_id: int) -> dict:
        """Get economy config for a guild"""
        row = await db.fetchone(
            "SELECT * FROM economy_config WHERE guild_id = ?", (guild_id,)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO economy_config (guild_id) VALUES (?)", (guild_id,)
        )
        row = await db.fetchone(
            "SELECT * FROM economy_config WHERE guild_id = ?", (guild_id,)
        )
        return dict(row)
    
    async def get_user_data(self, guild_id: int, user_id: int) -> dict:
        """Get user economy data"""
        row = await db.fetchone(
            "SELECT * FROM user_economy WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        if row:
            return dict(row)
        
        await db.execute(
            "INSERT OR IGNORE INTO user_economy (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id)
        )
        return {
            "guild_id": guild_id, "user_id": user_id,
            "balance": 0, "bank": 0, "last_daily": 0, "last_work": 0, "total_earned": 0
        }
    
    async def update_balance(self, guild_id: int, user_id: int, amount: int):
        """Update user balance"""
        await db.execute(
            """UPDATE user_economy SET balance = balance + ?, total_earned = total_earned + ?
               WHERE guild_id = ? AND user_id = ?""",
            (amount, max(0, amount), guild_id, user_id)
        )
    
    def format_currency(self, amount: int, config: dict) -> str:
        """Format currency with emoji"""
        emoji = config.get("currency_emoji", "🪙")
        name = config.get("currency_name", "coins")
        return f"{emoji} **{amount:,}** {name}"
    
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """Track voice for money"""
        if member.bot:
            return
        
        key = (member.guild.id, member.id)
        
        if before.channel is None and after.channel is not None:
            self.voice_tracking[key] = time.time()
        elif before.channel is not None and after.channel is None:
            if key in self.voice_tracking:
                del self.voice_tracking[key]
    
    @tasks.loop(minutes=1)
    async def voice_money_task(self):
        """Give money for voice time"""
        for (guild_id, user_id), join_time in list(self.voice_tracking.items()):
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue
            
            member = guild.get_member(user_id)
            if not member or not member.voice or not member.voice.channel:
                del self.voice_tracking[(guild_id, user_id)]
                continue
            
            voice_members = [m for m in member.voice.channel.members if not m.bot]
            if len(voice_members) < 2 or member.voice.self_mute or member.voice.self_deaf:
                continue
            
            config = await self.get_config(guild_id)
            money_per_min = config.get("voice_money_per_minute", 1)
            
            if money_per_min > 0:
                await self.get_user_data(guild_id, user_id)
                await self.update_balance(guild_id, user_id, money_per_min)
    
    @voice_money_task.before_loop
    async def before_voice_money(self):
        await self.bot.wait_until_ready()
    
    # ==================== COMMANDS ====================
    
    @commands.hybrid_command(name="balance", aliases=["bal", "money", "solde"])
    @app_commands.describe(member="Le membre dont tu veux voir le solde")
    async def balance(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche ton solde"""
        member = member or ctx.author
        
        if member.bot:
            return await ctx.send(embed=error_embed("Les bots n'ont pas d'argent !"))
        
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, member.id)
        
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        emoji = config.get("currency_emoji", "🪙")
        
        embed = create_embed(
            title=f"{emoji} Solde de {member.display_name}",
            color=color,
            thumbnail=member.display_avatar.url
        )
        embed.add_field(
            name="💰 Portefeuille",
            value=self.format_currency(user_data["balance"], config),
            inline=True
        )
        embed.add_field(
            name="🏦 Banque",
            value=self.format_currency(user_data["bank"], config),
            inline=True
        )
        embed.add_field(
            name="📊 Total",
            value=self.format_currency(user_data["balance"] + user_data["bank"], config),
            inline=True
        )
        embed.add_field(
            name="💵 Total gagné",
            value=self.format_currency(user_data["total_earned"], config),
            inline=True
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="daily", aliases=["quotidien"])
    async def daily(self, ctx: commands.Context):
        """Récupère ta récompense quotidienne"""
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        # Check cooldown (24 hours)
        last_daily = user_data["last_daily"]
        cooldown = 86400  # 24 hours
        
        if time.time() - last_daily < cooldown:
            remaining = int(cooldown - (time.time() - last_daily))
            return await ctx.send(embed=error_embed(
                f"Tu as déjà récupéré ta récompense quotidienne !\n"
                f"Reviens dans **{format_duration(remaining)}**"
            ))
        
        amount = config.get("daily_amount", 100)
        
        # Apply booster
        booster_roles = json.loads(config.get("booster_roles", "{}"))
        multiplier = 1.0
        for role in ctx.author.roles:
            if str(role.id) in booster_roles:
                multiplier = max(multiplier, booster_roles[str(role.id)])
        
        amount = int(amount * multiplier)
        
        await db.execute(
            "UPDATE user_economy SET balance = balance + ?, last_daily = ?, total_earned = total_earned + ? WHERE guild_id = ? AND user_id = ?",
            (amount, time.time(), amount, ctx.guild.id, ctx.author.id)
        )
        
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        embed = create_embed(
            title="🎁 Récompense quotidienne !",
            description=f"Tu as reçu {self.format_currency(amount, config)} !",
            color=color
        )
        
        if multiplier > 1:
            embed.set_footer(text=f"Bonus x{multiplier} appliqué !")
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="work", aliases=["travail", "travailler"])
    async def work(self, ctx: commands.Context):
        """Travaille pour gagner de l'argent"""
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        cooldown = config.get("work_cooldown", 3600)
        last_work = user_data["last_work"]
        
        if time.time() - last_work < cooldown:
            remaining = int(cooldown - (time.time() - last_work))
            return await ctx.send(embed=error_embed(
                f"Tu es fatigué ! Repose-toi **{format_duration(remaining)}**"
            ))
        
        work_min = config.get("work_min", 50)
        work_max = config.get("work_max", 200)
        amount = random.randint(work_min, work_max)
        
        jobs = [
            f"Tu as travaillé comme développeur et gagné",
            f"Tu as livré des pizzas et gagné",
            f"Tu as vendu des glaces et gagné",
            f"Tu as aidé ton voisin et gagné",
            f"Tu as streamé sur Twitch et gagné",
            f"Tu as fait du jardinage et gagné",
            f"Tu as réparé des ordinateurs et gagné",
            f"Tu as fait du babysitting et gagné",
        ]
        
        await db.execute(
            "UPDATE user_economy SET balance = balance + ?, last_work = ?, total_earned = total_earned + ? WHERE guild_id = ? AND user_id = ?",
            (amount, time.time(), amount, ctx.guild.id, ctx.author.id)
        )
        
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        embed = create_embed(
            title="💼 Travail",
            description=f"{random.choice(jobs)} {self.format_currency(amount, config)} !",
            color=color
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="deposit", aliases=["dep", "deposer"])
    @app_commands.describe(amount="Montant à déposer (ou 'all')")
    async def deposit(self, ctx: commands.Context, amount: str):
        """Dépose de l'argent à la banque"""
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        if amount.lower() in ["all", "tout", "max"]:
            amount = user_data["balance"]
        else:
            try:
                amount = int(amount)
            except ValueError:
                return await ctx.send(embed=error_embed("Montant invalide !"))
        
        if amount <= 0:
            return await ctx.send(embed=error_embed("Le montant doit être positif !"))
        
        if amount > user_data["balance"]:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        await db.execute(
            "UPDATE user_economy SET balance = balance - ?, bank = bank + ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, ctx.guild.id, ctx.author.id)
        )
        
        await ctx.send(embed=success_embed(
            f"Tu as déposé {self.format_currency(amount, config)} à la banque !"
        ))
    
    @commands.hybrid_command(name="withdraw", aliases=["wd", "retirer"])
    @app_commands.describe(amount="Montant à retirer (ou 'all')")
    async def withdraw(self, ctx: commands.Context, amount: str):
        """Retire de l'argent de la banque"""
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        if amount.lower() in ["all", "tout", "max"]:
            amount = user_data["bank"]
        else:
            try:
                amount = int(amount)
            except ValueError:
                return await ctx.send(embed=error_embed("Montant invalide !"))
        
        if amount <= 0:
            return await ctx.send(embed=error_embed("Le montant doit être positif !"))
        
        if amount > user_data["bank"]:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent en banque !"))
        
        await db.execute(
            "UPDATE user_economy SET balance = balance + ?, bank = bank - ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, ctx.guild.id, ctx.author.id)
        )
        
        await ctx.send(embed=success_embed(
            f"Tu as retiré {self.format_currency(amount, config)} de la banque !"
        ))
    
    @commands.hybrid_command(name="pay", aliases=["give", "donner"])
    @app_commands.describe(member="Le membre à qui donner", amount="Montant à donner")
    async def pay(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Donne de l'argent à un membre"""
        if member.bot:
            return await ctx.send(embed=error_embed("Tu ne peux pas donner aux bots !"))
        
        if member.id == ctx.author.id:
            return await ctx.send(embed=error_embed("Tu ne peux pas te donner à toi-même !"))
        
        if amount <= 0:
            return await ctx.send(embed=error_embed("Le montant doit être positif !"))
        
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        await self.get_user_data(ctx.guild.id, member.id)
        
        if amount > user_data["balance"]:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        await db.execute(
            "UPDATE user_economy SET balance = balance - ? WHERE guild_id = ? AND user_id = ?",
            (amount, ctx.guild.id, ctx.author.id)
        )
        await db.execute(
            "UPDATE user_economy SET balance = balance + ? WHERE guild_id = ? AND user_id = ?",
            (amount, ctx.guild.id, member.id)
        )
        
        await ctx.send(embed=success_embed(
            f"Tu as donné {self.format_currency(amount, config)} à {member.mention} !"
        ))
    
    @commands.hybrid_command(name="leaderboard-eco", aliases=["lb-eco", "top-eco", "richest"])
    @app_commands.describe(page="Numéro de page")
    async def leaderboard_eco(self, ctx: commands.Context, page: int = 1):
        """Affiche le classement des plus riches"""
        per_page = 10
        offset = (page - 1) * per_page
        
        rows = await db.fetchall(
            """SELECT user_id, balance, bank FROM user_economy 
               WHERE guild_id = ? ORDER BY (balance + bank) DESC LIMIT ? OFFSET ?""",
            (ctx.guild.id, per_page, offset)
        )
        
        total = await db.fetchone(
            "SELECT COUNT(*) as count FROM user_economy WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        total_pages = (total["count"] // per_page) + 1
        
        if not rows:
            return await ctx.send(embed=info_embed("Personne n'a d'argent !"))
        
        config = await self.get_config(ctx.guild.id)
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        emoji = config.get("currency_emoji", "🪙")
        
        description = ""
        for i, row in enumerate(rows, start=offset + 1):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else "Utilisateur inconnu"
            total_money = row["balance"] + row["bank"]
            
            medal = ""
            if i == 1: medal = "🥇 "
            elif i == 2: medal = "🥈 "
            elif i == 3: medal = "🥉 "
            
            description += f"{medal}**#{i}** {name}\n"
            description += f"└ {emoji} {total_money:,}\n\n"
        
        embed = create_embed(
            title=f"💰 Les plus riches de {ctx.guild.name}",
            description=description,
            color=color,
            footer=f"Page {page}/{total_pages}"
        )
        
        await ctx.send(embed=embed)
    
    # ==================== SHOP ====================
    
    @commands.hybrid_command(name="shop", aliases=["boutique", "magasin"])
    async def shop(self, ctx: commands.Context):
        """Affiche la boutique"""
        config = await self.get_config(ctx.guild.id)
        items = await db.fetchall(
            "SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price",
            (ctx.guild.id,)
        )
        
        if not items:
            return await ctx.send(embed=info_embed("La boutique est vide !"))
        
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        emoji = config.get("currency_emoji", "🪙")
        
        description = ""
        for item in items:
            stock_text = f"Stock: {item['stock']}" if item["stock"] >= 0 else "∞"
            role = ctx.guild.get_role(item["role_id"]) if item["role_id"] else None
            role_text = f" → {role.mention}" if role else ""
            
            description += f"**{item['id']}.** {item['name']}{role_text}\n"
            description += f"└ {emoji} {item['price']:,} • {stock_text}\n"
            if item["description"]:
                description += f"└ *{item['description']}*\n"
            description += "\n"
        
        embed = create_embed(
            title="🛒 Boutique",
            description=description,
            color=color,
            footer="Utilise !buy <id> pour acheter"
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="buy", aliases=["acheter"])
    @app_commands.describe(item_id="ID de l'article à acheter")
    async def buy(self, ctx: commands.Context, item_id: int):
        """Achète un article de la boutique"""
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        item = await db.fetchone(
            "SELECT * FROM shop_items WHERE id = ? AND guild_id = ?",
            (item_id, ctx.guild.id)
        )
        
        if not item:
            return await ctx.send(embed=error_embed("Article introuvable !"))
        
        if item["stock"] == 0:
            return await ctx.send(embed=error_embed("Article en rupture de stock !"))
        
        if user_data["balance"] < item["price"]:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        if item["required_role_id"]:
            required_role = ctx.guild.get_role(item["required_role_id"])
            if required_role and required_role not in ctx.author.roles:
                return await ctx.send(embed=error_embed(
                    f"Tu as besoin du rôle {required_role.mention} pour acheter cet article !"
                ))
        
        # Process purchase
        await db.execute(
            "UPDATE user_economy SET balance = balance - ? WHERE guild_id = ? AND user_id = ?",
            (item["price"], ctx.guild.id, ctx.author.id)
        )
        
        if item["stock"] > 0:
            await db.execute(
                "UPDATE shop_items SET stock = stock - 1 WHERE id = ?",
                (item_id,)
            )
        
        # Add to inventory
        await db.execute(
            """INSERT INTO user_inventory (guild_id, user_id, item_id, purchased_at)
               VALUES (?, ?, ?, ?)""",
            (ctx.guild.id, ctx.author.id, item_id, time.time())
        )
        
        # Give role if applicable
        if item["role_id"]:
            role = ctx.guild.get_role(item["role_id"])
            if role:
                try:
                    await ctx.author.add_roles(role, reason="Shop purchase")
                except discord.Forbidden:
                    pass
        
        await ctx.send(embed=success_embed(
            f"Tu as acheté **{item['name']}** pour {self.format_currency(item['price'], config)} !"
        ))
    
    @commands.hybrid_command(name="inventory", aliases=["inv", "inventaire"])
    async def inventory(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche ton inventaire"""
        member = member or ctx.author
        
        items = await db.fetchall(
            """SELECT i.name, COUNT(*) as qty FROM user_inventory ui
               JOIN shop_items i ON ui.item_id = i.id
               WHERE ui.guild_id = ? AND ui.user_id = ?
               GROUP BY i.id""",
            (ctx.guild.id, member.id)
        )
        
        if not items:
            return await ctx.send(embed=info_embed(
                f"{'Ton inventaire est vide' if member == ctx.author else f'L\\'inventaire de {member.display_name} est vide'} !"
            ))
        
        config = await self.get_config(ctx.guild.id)
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        
        description = ""
        for item in items:
            description += f"• **{item['name']}** x{item['qty']}\n"
        
        embed = create_embed(
            title=f"🎒 Inventaire de {member.display_name}",
            description=description,
            color=color
        )
        
        await ctx.send(embed=embed)
    
    # ==================== GAMBLING ====================
    
    @commands.hybrid_command(name="coinflip", aliases=["cf", "pileouface"])
    @app_commands.describe(amount="Mise", choice="Ton choix (pile/face)")
    async def coinflip(self, ctx: commands.Context, amount: int, choice: str = "pile"):
        """Joue à pile ou face"""
        if amount <= 0:
            return await ctx.send(embed=error_embed("La mise doit être positive !"))
        
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        if amount > user_data["balance"]:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        choice = choice.lower()
        if choice not in ["pile", "face", "p", "f", "heads", "tails"]:
            return await ctx.send(embed=error_embed("Choisis pile ou face !"))
        
        choice = "pile" if choice in ["pile", "p", "heads"] else "face"
        result = random.choice(["pile", "face"])
        won = choice == result
        
        if won:
            await self.update_balance(ctx.guild.id, ctx.author.id, amount)
            color = discord.Color.green()
            title = "🎉 Gagné !"
            desc = f"C'était **{result}** ! Tu gagnes {self.format_currency(amount, config)} !"
        else:
            await self.update_balance(ctx.guild.id, ctx.author.id, -amount)
            color = discord.Color.red()
            title = "😢 Perdu..."
            desc = f"C'était **{result}**... Tu perds {self.format_currency(amount, config)}"
        
        embed = create_embed(title=title, description=desc, color=color)
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="slots", aliases=["machine"])
    @app_commands.describe(amount="Mise")
    async def slots(self, ctx: commands.Context, amount: int):
        """Joue à la machine à sous"""
        if amount <= 0:
            return await ctx.send(embed=error_embed("La mise doit être positive !"))
        
        config = await self.get_config(ctx.guild.id)
        user_data = await self.get_user_data(ctx.guild.id, ctx.author.id)
        
        if amount > user_data["balance"]:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        emojis = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        weights = [30, 25, 20, 15, 7, 3]  # Weighted probabilities
        
        results = random.choices(emojis, weights=weights, k=3)
        
        # Calculate winnings
        if results[0] == results[1] == results[2]:
            if results[0] == "7️⃣":
                multiplier = 10
            elif results[0] == "💎":
                multiplier = 5
            else:
                multiplier = 3
            winnings = amount * multiplier
            title = "🎰 JACKPOT !"
            color = discord.Color.gold()
        elif results[0] == results[1] or results[1] == results[2]:
            multiplier = 1.5
            winnings = int(amount * multiplier)
            title = "🎰 Pas mal !"
            color = discord.Color.green()
        else:
            winnings = -amount
            title = "🎰 Perdu..."
            color = discord.Color.red()
        
        await self.update_balance(ctx.guild.id, ctx.author.id, winnings)
        
        slot_display = f"╔══════════╗\n║ {' '.join(results)} ║\n╚══════════╝"
        
        if winnings > 0:
            desc = f"{slot_display}\n\nTu gagnes {self.format_currency(winnings, config)} !"
        else:
            desc = f"{slot_display}\n\nTu perds {self.format_currency(abs(winnings), config)}"
        
        embed = create_embed(title=title, description=desc, color=color)
        await ctx.send(embed=embed)
    
    # ==================== ADMIN ====================
    
    @commands.group(name="ecoadmin", aliases=["ea"], invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def ecoadmin(self, ctx: commands.Context):
        """Commandes d'administration de l'économie"""
        embed = create_embed(
            title="💰 Administration de l'économie",
            description="Commandes disponibles :",
            fields=[
                ("Argent", "`ecoadmin give <@membre> <montant>`\n`ecoadmin remove <@membre> <montant>`\n`ecoadmin set <@membre> <montant>`", False),
                ("Boutique", "`ecoadmin shop add <prix> <nom>`\n`ecoadmin shop remove <id>`\n`ecoadmin shop role <id> <@role>`", False),
                ("Config", "`ecoadmin daily <montant>`\n`ecoadmin currency <nom> <emoji>`\n`ecoadmin work <min> <max>`", False),
            ]
        )
        await ctx.send(embed=embed)
    
    @ecoadmin.command(name="give")
    @commands.has_permissions(administrator=True)
    async def eco_give(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Donne de l'argent à un membre"""
        await self.get_user_data(ctx.guild.id, member.id)
        await self.update_balance(ctx.guild.id, member.id, amount)
        
        config = await self.get_config(ctx.guild.id)
        await ctx.send(embed=success_embed(
            f"Tu as donné {self.format_currency(amount, config)} à {member.mention} !"
        ))
    
    @ecoadmin.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def eco_remove(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Retire de l'argent à un membre"""
        await self.get_user_data(ctx.guild.id, member.id)
        await self.update_balance(ctx.guild.id, member.id, -amount)
        
        config = await self.get_config(ctx.guild.id)
        await ctx.send(embed=success_embed(
            f"Tu as retiré {self.format_currency(amount, config)} à {member.mention} !"
        ))
    
    @ecoadmin.command(name="set")
    @commands.has_permissions(administrator=True)
    async def eco_set(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Définit le solde d'un membre"""
        await self.get_user_data(ctx.guild.id, member.id)
        await db.execute(
            "UPDATE user_economy SET balance = ? WHERE guild_id = ? AND user_id = ?",
            (amount, ctx.guild.id, member.id)
        )
        
        config = await self.get_config(ctx.guild.id)
        await ctx.send(embed=success_embed(
            f"Solde de {member.mention} défini à {self.format_currency(amount, config)} !"
        ))
    
    @ecoadmin.group(name="shop", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def eco_shop(self, ctx: commands.Context):
        """Gère la boutique"""
        await ctx.invoke(self.shop)
    
    @eco_shop.command(name="add")
    @commands.has_permissions(administrator=True)
    async def shop_add(self, ctx: commands.Context, price: int, *, name: str):
        """Ajoute un article à la boutique"""
        await db.execute(
            "INSERT INTO shop_items (guild_id, name, price, created_at) VALUES (?, ?, ?, ?)",
            (ctx.guild.id, name, price, time.time())
        )
        await ctx.send(embed=success_embed(f"Article **{name}** ajouté pour **{price}** !"))
    
    @eco_shop.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def shop_remove(self, ctx: commands.Context, item_id: int):
        """Supprime un article de la boutique"""
        await db.execute(
            "DELETE FROM shop_items WHERE id = ? AND guild_id = ?",
            (item_id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Article #{item_id} supprimé !"))
    
    @eco_shop.command(name="role")
    @commands.has_permissions(administrator=True)
    async def shop_role(self, ctx: commands.Context, item_id: int, role: discord.Role):
        """Associe un rôle à un article"""
        await db.execute(
            "UPDATE shop_items SET role_id = ? WHERE id = ? AND guild_id = ?",
            (role.id, item_id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(
            f"L'article #{item_id} donne maintenant le rôle {role.mention} !"
        ))
    
    @eco_shop.command(name="desc")
    @commands.has_permissions(administrator=True)
    async def shop_desc(self, ctx: commands.Context, item_id: int, *, description: str):
        """Définit la description d'un article"""
        await db.execute(
            "UPDATE shop_items SET description = ? WHERE id = ? AND guild_id = ?",
            (description, item_id, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Description de l'article #{item_id} mise à jour !"))
    
    @eco_shop.command(name="stock")
    @commands.has_permissions(administrator=True)
    async def shop_stock(self, ctx: commands.Context, item_id: int, stock: int):
        """Définit le stock d'un article (-1 = illimité)"""
        await db.execute(
            "UPDATE shop_items SET stock = ? WHERE id = ? AND guild_id = ?",
            (stock, item_id, ctx.guild.id)
        )
        stock_text = "illimité" if stock < 0 else str(stock)
        await ctx.send(embed=success_embed(f"Stock de l'article #{item_id} défini à {stock_text} !"))
    
    @ecoadmin.command(name="currency")
    @commands.has_permissions(administrator=True)
    async def eco_currency(self, ctx: commands.Context, name: str, emoji: str):
        """Définit le nom et l'emoji de la monnaie"""
        await db.execute(
            "UPDATE economy_config SET currency_name = ?, currency_emoji = ? WHERE guild_id = ?",
            (name, emoji, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Monnaie définie : {emoji} {name}"))
    
    @ecoadmin.command(name="daily")
    @commands.has_permissions(administrator=True)
    async def eco_daily(self, ctx: commands.Context, amount: int):
        """Définit le montant de la récompense quotidienne"""
        await db.execute(
            "UPDATE economy_config SET daily_amount = ? WHERE guild_id = ?",
            (amount, ctx.guild.id)
        )
        await ctx.send(embed=success_embed(f"Récompense quotidienne définie à **{amount}**"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
