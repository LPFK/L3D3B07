"""
Repository Economy - acces aux donnees economie

balance, bank, shop, inventaire, transactions
"""

import time
from dataclasses import dataclass
from typing import Optional

from utils.database import db
from utils.repositories import ConfigCache


@dataclass
class UserEconomy:
    """donnees eco d'un user"""
    guild_id: int
    user_id: int
    balance: int = 0
    bank: int = 0
    last_daily: float = 0
    last_work: float = 0
    total_earned: int = 0


@dataclass
class ShopItem:
    """article du shop"""
    id: int
    guild_id: int
    name: str
    description: str = ""
    price: int = 0
    role_id: Optional[int] = None
    stock: int = -1  # -1 = illimite
    required_role_id: Optional[int] = None
    created_at: float = 0


@dataclass
class InventoryItem:
    """item dans l'inventaire"""
    id: int
    guild_id: int
    user_id: int
    item_id: int
    quantity: int = 1
    purchased_at: float = 0


class EconomyRepository:
    """acces aux donnees economy"""
    
    def __init__(self):
        self.config_cache = ConfigCache("economy_config", ttl=60)
        self.config_cache.set_json_fields(["booster_roles"])
    
    # ---- CONFIG ----
    
    async def get_config(self, guild_id: int) -> dict:
        return await self.config_cache.get(guild_id)
    
    async def update_config(self, guild_id: int, **kwargs) -> None:
        if not kwargs:
            return
        
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        
        await db.execute(
            f"UPDATE economy_config SET {set_clause} WHERE guild_id = ?",
            tuple(values)
        )
        self.config_cache.invalidate(guild_id)
    
    # ---- USERS ----
    
    async def get_user(self, guild_id: int, user_id: int) -> Optional[UserEconomy]:
        row = await db.fetchone(
            "SELECT * FROM user_economy WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        if not row:
            return None
        return UserEconomy(**dict(row))
    
    async def get_or_create_user(self, guild_id: int, user_id: int) -> UserEconomy:
        user = await self.get_user(guild_id, user_id)
        if user:
            return user
        
        await db.execute(
            "INSERT OR IGNORE INTO user_economy (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id)
        )
        return UserEconomy(guild_id=guild_id, user_id=user_id)
    
    async def save_user(self, user: UserEconomy) -> None:
        await db.execute("""
            INSERT INTO user_economy (guild_id, user_id, balance, bank, last_daily, last_work, total_earned)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                balance = excluded.balance,
                bank = excluded.bank,
                last_daily = excluded.last_daily,
                last_work = excluded.last_work,
                total_earned = excluded.total_earned
        """, (user.guild_id, user.user_id, user.balance, user.bank,
              user.last_daily, user.last_work, user.total_earned))
    
    # ---- TRANSACTIONS ----
    
    async def add_balance(self, guild_id: int, user_id: int, amount: int) -> UserEconomy:
        """ajoute au solde (peut etre negatif)"""
        await self.get_or_create_user(guild_id, user_id)
        
        if amount > 0:
            await db.execute(
                "UPDATE user_economy SET balance = balance + ?, total_earned = total_earned + ? WHERE guild_id = ? AND user_id = ?",
                (amount, amount, guild_id, user_id)
            )
        else:
            await db.execute(
                "UPDATE user_economy SET balance = balance + ? WHERE guild_id = ? AND user_id = ?",
                (amount, guild_id, user_id)
            )
        
        return await self.get_user(guild_id, user_id)
    
    async def set_balance(self, guild_id: int, user_id: int, amount: int) -> None:
        await self.get_or_create_user(guild_id, user_id)
        await db.execute(
            "UPDATE user_economy SET balance = ? WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id)
        )
    
    async def transfer(self, guild_id: int, from_user: int, to_user: int, amount: int) -> bool:
        """transfert entre users, retourne False si pas assez"""
        sender = await self.get_or_create_user(guild_id, from_user)
        if sender.balance < amount:
            return False
        
        await self.add_balance(guild_id, from_user, -amount)
        await self.add_balance(guild_id, to_user, amount)
        return True
    
    async def deposit(self, guild_id: int, user_id: int, amount: int) -> bool:
        """depose en banque"""
        user = await self.get_or_create_user(guild_id, user_id)
        if user.balance < amount:
            return False
        
        await db.execute(
            "UPDATE user_economy SET balance = balance - ?, bank = bank + ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, guild_id, user_id)
        )
        return True
    
    async def withdraw(self, guild_id: int, user_id: int, amount: int) -> bool:
        """retire de la banque"""
        user = await self.get_or_create_user(guild_id, user_id)
        if user.bank < amount:
            return False
        
        await db.execute(
            "UPDATE user_economy SET balance = balance + ?, bank = bank - ? WHERE guild_id = ? AND user_id = ?",
            (amount, amount, guild_id, user_id)
        )
        return True
    
    # ---- COOLDOWNS ----
    
    async def can_daily(self, guild_id: int, user_id: int) -> tuple[bool, float]:
        """retourne (peut_daily, secondes_restantes)"""
        user = await self.get_or_create_user(guild_id, user_id)
        cooldown = 86400  # 24h
        remaining = (user.last_daily + cooldown) - time.time()
        return remaining <= 0, max(0, remaining)
    
    async def do_daily(self, guild_id: int, user_id: int, amount: int) -> UserEconomy:
        """fait le daily"""
        await self.add_balance(guild_id, user_id, amount)
        await db.execute(
            "UPDATE user_economy SET last_daily = ? WHERE guild_id = ? AND user_id = ?",
            (time.time(), guild_id, user_id)
        )
        return await self.get_user(guild_id, user_id)
    
    async def can_work(self, guild_id: int, user_id: int, cooldown: int) -> tuple[bool, float]:
        user = await self.get_or_create_user(guild_id, user_id)
        remaining = (user.last_work + cooldown) - time.time()
        return remaining <= 0, max(0, remaining)
    
    async def do_work(self, guild_id: int, user_id: int, amount: int) -> UserEconomy:
        await self.add_balance(guild_id, user_id, amount)
        await db.execute(
            "UPDATE user_economy SET last_work = ? WHERE guild_id = ? AND user_id = ?",
            (time.time(), guild_id, user_id)
        )
        return await self.get_user(guild_id, user_id)
    
    # ---- LEADERBOARD ----
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> list[UserEconomy]:
        rows = await db.fetchall(
            "SELECT * FROM user_economy WHERE guild_id = ? ORDER BY (balance + bank) DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset)
        )
        return [UserEconomy(**dict(r)) for r in rows]
    
    async def get_rank(self, guild_id: int, user_id: int) -> int:
        row = await db.fetchone("""
            SELECT COUNT(*) + 1 as rank
            FROM user_economy
            WHERE guild_id = ? AND (balance + bank) > (
                SELECT COALESCE(balance + bank, 0) FROM user_economy WHERE guild_id = ? AND user_id = ?
            )
        """, (guild_id, guild_id, user_id))
        return row["rank"] if row else 1
    
    # ---- SHOP ----
    
    async def get_shop_items(self, guild_id: int) -> list[ShopItem]:
        rows = await db.fetchall(
            "SELECT * FROM shop_items WHERE guild_id = ? ORDER BY price",
            (guild_id,)
        )
        return [ShopItem(**dict(r)) for r in rows]
    
    async def get_shop_item(self, item_id: int) -> Optional[ShopItem]:
        row = await db.fetchone(
            "SELECT * FROM shop_items WHERE id = ?",
            (item_id,)
        )
        return ShopItem(**dict(row)) if row else None
    
    async def create_shop_item(self, guild_id: int, name: str, price: int, **kwargs) -> int:
        cursor = await db.execute(
            """INSERT INTO shop_items (guild_id, name, price, description, role_id, stock, required_role_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, name, price, kwargs.get("description", ""),
             kwargs.get("role_id"), kwargs.get("stock", -1),
             kwargs.get("required_role_id"), time.time())
        )
        return cursor.lastrowid
    
    async def delete_shop_item(self, item_id: int) -> None:
        await db.execute("DELETE FROM shop_items WHERE id = ?", (item_id,))
    
    async def buy_item(self, guild_id: int, user_id: int, item_id: int) -> tuple[bool, str]:
        """
        achete un item
        retourne (success, message)
        """
        item = await self.get_shop_item(item_id)
        if not item:
            return False, "Article introuvable"
        
        if item.stock == 0:
            return False, "Stock epuise"
        
        user = await self.get_or_create_user(guild_id, user_id)
        if user.balance < item.price:
            return False, "Pas assez d'argent"
        
        # deduit le prix
        await self.add_balance(guild_id, user_id, -item.price)
        
        # reduit le stock si limite
        if item.stock > 0:
            await db.execute(
                "UPDATE shop_items SET stock = stock - 1 WHERE id = ?",
                (item_id,)
            )
        
        # ajoute a l'inventaire
        await db.execute("""
            INSERT INTO user_inventory (guild_id, user_id, item_id, quantity, purchased_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id, item_id) DO UPDATE SET quantity = quantity + 1
        """, (guild_id, user_id, item_id, time.time()))
        
        return True, f"Tu as achete **{item.name}** !"
    
    # ---- INVENTORY ----
    
    async def get_inventory(self, guild_id: int, user_id: int) -> list[dict]:
        """inventaire avec infos des items"""
        rows = await db.fetchall("""
            SELECT i.*, ui.quantity
            FROM user_inventory ui
            JOIN shop_items i ON i.id = ui.item_id
            WHERE ui.guild_id = ? AND ui.user_id = ?
            ORDER BY i.name
        """, (guild_id, user_id))
        return [dict(r) for r in rows]


# singleton
economy_repo = EconomyRepository()
