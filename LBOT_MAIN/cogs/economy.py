"""
Cog Economy - monnaie, shop, daily, work, gambling

utilise economy_repo pour les acces DB (voir utils/repositories/economy.py)
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
import random
from typing import Optional

from utils.database import db
from utils.repositories.economy import economy_repo, UserEconomy
from utils.helpers import (
    create_embed, success_embed, error_embed, info_embed, warning_embed,
    format_duration, Paginator, ConfirmView, is_admin
)


class Economy(commands.Cog):
    """Systeme d'economie"""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_tracking: dict[tuple[int, int], float] = {}
    
    async def cog_load(self):
        self.voice_money_task.start()
    
    async def cog_unload(self):
        self.voice_money_task.cancel()
    
    def format_currency(self, amount: int, config: dict) -> str:
        """formate la monnaie avec emoji"""
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
        """track le vocal pour l'argent"""
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
        """donne de l'argent pour le temps vocal"""
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
            
            config = await economy_repo.get_config(guild_id)
            money_per_min = config.get("voice_money_per_minute", 1)
            
            if money_per_min > 0:
                await economy_repo.add_balance(guild_id, user_id, money_per_min)
    
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
        
        config = await economy_repo.get_config(ctx.guild.id)
        user = await economy_repo.get_or_create_user(ctx.guild.id, member.id)
        
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        emoji = config.get("currency_emoji", "🪙")
        
        embed = create_embed(
            title=f"{emoji} Solde de {member.display_name}",
            color=color,
            thumbnail=member.display_avatar.url
        )
        embed.add_field(
            name="💰 Portefeuille",
            value=self.format_currency(user.balance, config),
            inline=True
        )
        embed.add_field(
            name="🏦 Banque",
            value=self.format_currency(user.bank, config),
            inline=True
        )
        embed.add_field(
            name="📊 Total",
            value=self.format_currency(user.balance + user.bank, config),
            inline=True
        )
        embed.add_field(
            name="💵 Total gagné",
            value=self.format_currency(user.total_earned, config),
            inline=True
        )
        
        await ctx.send(embed=embed)
    
    @commands.hybrid_command(name="daily", aliases=["quotidien"])
    async def daily(self, ctx: commands.Context):
        """Récupère ta récompense quotidienne"""
        config = await economy_repo.get_config(ctx.guild.id)
        can_claim, remaining = await economy_repo.can_daily(ctx.guild.id, ctx.author.id)
        
        if not can_claim:
            return await ctx.send(embed=error_embed(
                f"Tu as déjà récupéré ta récompense quotidienne !\n"
                f"Reviens dans **{format_duration(int(remaining))}**"
            ))
        
        amount = config.get("daily_amount", 100)
        
        # boosters
        booster_roles = config.get("booster_roles", {})
        multiplier = 1.0
        for role in ctx.author.roles:
            if str(role.id) in booster_roles:
                multiplier = max(multiplier, booster_roles[str(role.id)])
        
        amount = int(amount * multiplier)
        
        await economy_repo.do_daily(ctx.guild.id, ctx.author.id, amount)
        
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
        config = await economy_repo.get_config(ctx.guild.id)
        cooldown = config.get("work_cooldown", 3600)
        
        can_work, remaining = await economy_repo.can_work(ctx.guild.id, ctx.author.id, cooldown)
        
        if not can_work:
            return await ctx.send(embed=error_embed(
                f"Tu es fatigué ! Repose-toi **{format_duration(int(remaining))}**"
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
        
        await economy_repo.do_work(ctx.guild.id, ctx.author.id, amount)
        
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
        config = await economy_repo.get_config(ctx.guild.id)
        user = await economy_repo.get_or_create_user(ctx.guild.id, ctx.author.id)
        
        if amount.lower() in ["all", "tout", "max"]:
            amount = user.balance
        else:
            try:
                amount = int(amount)
            except ValueError:
                return await ctx.send(embed=error_embed("Montant invalide !"))
        
        if amount <= 0:
            return await ctx.send(embed=error_embed("Le montant doit être positif !"))
        
        if amount > user.balance:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        success = await economy_repo.deposit(ctx.guild.id, ctx.author.id, amount)
        if success:
            await ctx.send(embed=success_embed(
                f"Tu as déposé {self.format_currency(amount, config)} à la banque !"
            ))
    
    @commands.hybrid_command(name="withdraw", aliases=["wd", "retirer"])
    @app_commands.describe(amount="Montant à retirer (ou 'all')")
    async def withdraw(self, ctx: commands.Context, amount: str):
        """Retire de l'argent de la banque"""
        config = await economy_repo.get_config(ctx.guild.id)
        user = await economy_repo.get_or_create_user(ctx.guild.id, ctx.author.id)
        
        if amount.lower() in ["all", "tout", "max"]:
            amount = user.bank
        else:
            try:
                amount = int(amount)
            except ValueError:
                return await ctx.send(embed=error_embed("Montant invalide !"))
        
        if amount <= 0:
            return await ctx.send(embed=error_embed("Le montant doit être positif !"))
        
        if amount > user.bank:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent en banque !"))
        
        success = await economy_repo.withdraw(ctx.guild.id, ctx.author.id, amount)
        if success:
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
        
        config = await economy_repo.get_config(ctx.guild.id)
        
        success = await economy_repo.transfer(ctx.guild.id, ctx.author.id, member.id, amount)
        if not success:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        await ctx.send(embed=success_embed(
            f"Tu as donné {self.format_currency(amount, config)} à {member.mention} !"
        ))
    
    @commands.hybrid_command(name="leaderboard-eco", aliases=["lb-eco", "top-eco", "richest"])
    @app_commands.describe(page="Numéro de page")
    async def leaderboard_eco(self, ctx: commands.Context, page: int = 1):
        """Affiche le classement des plus riches"""
        per_page = 10
        offset = (page - 1) * per_page
        
        users = await economy_repo.get_leaderboard(ctx.guild.id, limit=per_page, offset=offset)
        
        # compte total pour pagination
        total_row = await db.fetchone(
            "SELECT COUNT(*) as count FROM user_economy WHERE guild_id = ?",
            (ctx.guild.id,)
        )
        total_pages = (total_row["count"] // per_page) + 1
        
        if not users:
            return await ctx.send(embed=info_embed("Personne n'a d'argent !"))
        
        config = await economy_repo.get_config(ctx.guild.id)
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        emoji = config.get("currency_emoji", "🪙")
        
        description = ""
        for i, user in enumerate(users, start=offset + 1):
            member = ctx.guild.get_member(user.user_id)
            name = member.display_name if member else "Utilisateur inconnu"
            total_money = user.balance + user.bank
            
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
        config = await economy_repo.get_config(ctx.guild.id)
        items = await economy_repo.get_shop_items(ctx.guild.id)
        
        if not items:
            return await ctx.send(embed=info_embed("La boutique est vide !"))
        
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        emoji = config.get("currency_emoji", "🪙")
        
        description = ""
        for item in items:
            stock_text = f"Stock: {item.stock}" if item.stock >= 0 else "∞"
            role = ctx.guild.get_role(item.role_id) if item.role_id else None
            role_text = f" → {role.mention}" if role else ""
            
            description += f"**{item.id}.** {item.name}{role_text}\n"
            description += f"└ {emoji} {item.price:,} • {stock_text}\n"
            if item.description:
                description += f"└ *{item.description}*\n"
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
        config = await economy_repo.get_config(ctx.guild.id)
        item = await economy_repo.get_shop_item(item_id)
        
        if not item or item.guild_id != ctx.guild.id:
            return await ctx.send(embed=error_embed("Article introuvable !"))
        
        # check required role
        if item.required_role_id:
            required_role = ctx.guild.get_role(item.required_role_id)
            if required_role and required_role not in ctx.author.roles:
                return await ctx.send(embed=error_embed(
                    f"Tu as besoin du rôle {required_role.mention} pour acheter cet article !"
                ))
        
        success, message = await economy_repo.buy_item(ctx.guild.id, ctx.author.id, item_id)
        
        if not success:
            return await ctx.send(embed=error_embed(message))
        
        # donne le role si applicable
        if item.role_id:
            role = ctx.guild.get_role(item.role_id)
            if role:
                try:
                    await ctx.author.add_roles(role, reason="Shop purchase")
                except discord.Forbidden:
                    pass
        
        await ctx.send(embed=success_embed(
            f"Tu as acheté **{item.name}** pour {self.format_currency(item.price, config)} !"
        ))
    
    @commands.hybrid_command(name="inventory", aliases=["inv", "inventaire"])
    async def inventory(self, ctx: commands.Context, member: discord.Member = None):
        """Affiche ton inventaire"""
        member = member or ctx.author
        
        items = await economy_repo.get_inventory(ctx.guild.id, member.id)
        
        if not items:
            msg = "Ton inventaire est vide" if member == ctx.author else f"L'inventaire de {member.display_name} est vide"
            return await ctx.send(embed=info_embed(f"{msg} !"))
        
        config = await economy_repo.get_config(ctx.guild.id)
        color = discord.Color.from_str(config.get("color", "#F1C40F"))
        
        description = ""
        for item in items:
            description += f"• **{item['name']}** x{item['quantity']}\n"
        
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
        
        config = await economy_repo.get_config(ctx.guild.id)
        user = await economy_repo.get_or_create_user(ctx.guild.id, ctx.author.id)
        
        if amount > user.balance:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        choice = choice.lower()
        if choice not in ["pile", "face", "p", "f", "heads", "tails"]:
            return await ctx.send(embed=error_embed("Choisis pile ou face !"))
        
        choice = "pile" if choice in ["pile", "p", "heads"] else "face"
        result = random.choice(["pile", "face"])
        won = choice == result
        
        if won:
            await economy_repo.add_balance(ctx.guild.id, ctx.author.id, amount)
            color = discord.Color.green()
            title = "🎉 Gagné !"
            desc = f"C'était **{result}** ! Tu gagnes {self.format_currency(amount, config)} !"
        else:
            await economy_repo.add_balance(ctx.guild.id, ctx.author.id, -amount)
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
        
        config = await economy_repo.get_config(ctx.guild.id)
        user = await economy_repo.get_or_create_user(ctx.guild.id, ctx.author.id)
        
        if amount > user.balance:
            return await ctx.send(embed=error_embed("Tu n'as pas assez d'argent !"))
        
        emojis = ["🍒", "🍋", "🍊", "🍇", "💎", "7️⃣"]
        weights = [30, 25, 20, 15, 7, 3]
        
        results = random.choices(emojis, weights=weights, k=3)
        
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
        
        await economy_repo.add_balance(ctx.guild.id, ctx.author.id, winnings)
        
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
        await economy_repo.add_balance(ctx.guild.id, member.id, amount)
        config = await economy_repo.get_config(ctx.guild.id)
        await ctx.send(embed=success_embed(
            f"Tu as donné {self.format_currency(amount, config)} à {member.mention} !"
        ))
    
    @ecoadmin.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def eco_remove(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Retire de l'argent à un membre"""
        await economy_repo.add_balance(ctx.guild.id, member.id, -amount)
        config = await economy_repo.get_config(ctx.guild.id)
        await ctx.send(embed=success_embed(
            f"Tu as retiré {self.format_currency(amount, config)} à {member.mention} !"
        ))
    
    @ecoadmin.command(name="set")
    @commands.has_permissions(administrator=True)
    async def eco_set(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Définit le solde d'un membre"""
        await economy_repo.set_balance(ctx.guild.id, member.id, amount)
        config = await economy_repo.get_config(ctx.guild.id)
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
        await economy_repo.create_shop_item(ctx.guild.id, name, price)
        await ctx.send(embed=success_embed(f"Article **{name}** ajouté pour **{price}** !"))
    
    @eco_shop.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def shop_remove(self, ctx: commands.Context, item_id: int):
        """Supprime un article de la boutique"""
        await economy_repo.delete_shop_item(item_id)
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
        await economy_repo.update_config(ctx.guild.id, currency_name=name, currency_emoji=emoji)
        await ctx.send(embed=success_embed(f"Monnaie définie : {emoji} {name}"))
    
    @ecoadmin.command(name="daily")
    @commands.has_permissions(administrator=True)
    async def eco_daily(self, ctx: commands.Context, amount: int):
        """Définit le montant de la récompense quotidienne"""
        await economy_repo.update_config(ctx.guild.id, daily_amount=amount)
        await ctx.send(embed=success_embed(f"Récompense quotidienne définie à **{amount}**"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
