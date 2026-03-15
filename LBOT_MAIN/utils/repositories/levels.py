"""
Repository Levels - acces aux donnees XP/niveaux

separe la logique SQL du cog pour:
- tester plus facilement
- pas dupliquer le SQL partout
- centraliser les modifs de schema
"""

import time
from dataclasses import dataclass
from typing import Optional

from utils.database import db
from utils.repositories import ConfigCache


@dataclass
class UserLevel:
    """un user avec son xp/level"""
    guild_id: int
    user_id: int
    xp: int = 0
    level: int = 0
    total_messages: int = 0
    voice_time: int = 0
    last_xp_time: float = 0


@dataclass
class LevelReward:
    """recompense de niveau"""
    id: int
    guild_id: int
    level: int
    role_id: int
    remove_previous: bool = False


class LevelsRepository:
    """acces aux donnees levels"""
    
    def __init__(self):
        # cache config avec parsing json auto
        self.config_cache = ConfigCache("levels_config", ttl=60)
        self.config_cache.set_json_fields([
            "ignored_channels",
            "ignored_roles", 
            "booster_roles"
        ])
    
    # ---- CONFIG ----
    
    async def get_config(self, guild_id: int) -> dict:
        """config levels du serveur (avec cache)"""
        return await self.config_cache.get(guild_id)
    
    async def update_config(self, guild_id: int, **kwargs) -> None:
        """met a jour la config"""
        if not kwargs:
            return
        
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        
        await db.execute(
            f"UPDATE levels_config SET {set_clause} WHERE guild_id = ?",
            tuple(values)
        )
        self.config_cache.invalidate(guild_id)
    
    # ---- USERS ----
    
    async def get_user(self, guild_id: int, user_id: int) -> Optional[UserLevel]:
        """recup un user"""
        row = await db.fetchone(
            "SELECT * FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        if not row:
            return None
        return UserLevel(**dict(row))
    
    async def get_or_create_user(self, guild_id: int, user_id: int) -> UserLevel:
        """recup ou cree un user"""
        user = await self.get_user(guild_id, user_id)
        if user:
            return user
        
        await db.execute(
            "INSERT OR IGNORE INTO user_levels (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id)
        )
        return UserLevel(guild_id=guild_id, user_id=user_id)
    
    async def save_user(self, user: UserLevel) -> None:
        """sauvegarde un user"""
        await db.execute("""
            INSERT INTO user_levels (guild_id, user_id, xp, level, total_messages, voice_time, last_xp_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                xp = excluded.xp,
                level = excluded.level,
                total_messages = excluded.total_messages,
                voice_time = excluded.voice_time,
                last_xp_time = excluded.last_xp_time
        """, (user.guild_id, user.user_id, user.xp, user.level,
              user.total_messages, user.voice_time, user.last_xp_time))
    
    async def add_xp(self, guild_id: int, user_id: int, amount: int) -> UserLevel:
        """ajoute de l'xp et retourne le user mis a jour"""
        now = time.time()
        
        await db.execute("""
            INSERT INTO user_levels (guild_id, user_id, xp, total_messages, last_xp_time)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                xp = xp + ?,
                total_messages = total_messages + 1,
                last_xp_time = ?
        """, (guild_id, user_id, amount, now, amount, now))
        
        return await self.get_user(guild_id, user_id)
    
    async def set_xp(self, guild_id: int, user_id: int, xp: int, level: int) -> None:
        """definit l'xp d'un user"""
        await db.execute("""
            INSERT INTO user_levels (guild_id, user_id, xp, level)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?
        """, (guild_id, user_id, xp, level, xp, level))
    
    async def reset_user(self, guild_id: int, user_id: int) -> None:
        """reset un user"""
        await db.execute(
            "DELETE FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
    
    async def check_cooldown(self, guild_id: int, user_id: int, cooldown: int) -> bool:
        """
        verifie si l'user peut gagner de l'xp
        retourne True si ok, False si en cooldown
        """
        row = await db.fetchone(
            "SELECT last_xp_time FROM user_levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        )
        if not row:
            return True
        return time.time() - row["last_xp_time"] >= cooldown
    
    # ---- LEADERBOARD ----
    
    async def get_leaderboard(self, guild_id: int, limit: int = 10, offset: int = 0) -> list[UserLevel]:
        """classement xp"""
        rows = await db.fetchall(
            "SELECT * FROM user_levels WHERE guild_id = ? ORDER BY xp DESC LIMIT ? OFFSET ?",
            (guild_id, limit, offset)
        )
        return [UserLevel(**dict(r)) for r in rows]
    
    async def get_rank(self, guild_id: int, user_id: int) -> int:
        """rang d'un user (1-indexed)"""
        row = await db.fetchone("""
            SELECT COUNT(*) + 1 as rank
            FROM user_levels
            WHERE guild_id = ? AND xp > (
                SELECT COALESCE(xp, 0) FROM user_levels WHERE guild_id = ? AND user_id = ?
            )
        """, (guild_id, guild_id, user_id))
        return row["rank"] if row else 1
    
    async def get_total_users(self, guild_id: int) -> int:
        """nombre total d'users avec xp"""
        row = await db.fetchone(
            "SELECT COUNT(*) as count FROM user_levels WHERE guild_id = ?",
            (guild_id,)
        )
        return row["count"] if row else 0
    
    # ---- REWARDS ----
    
    async def get_rewards(self, guild_id: int) -> list[LevelReward]:
        """liste des rewards"""
        rows = await db.fetchall(
            "SELECT * FROM level_rewards WHERE guild_id = ? ORDER BY level",
            (guild_id,)
        )
        return [LevelReward(**dict(r)) for r in rows]
    
    async def get_rewards_for_level(self, guild_id: int, level: int) -> list[LevelReward]:
        """rewards jusqu'au niveau donne"""
        rows = await db.fetchall(
            "SELECT * FROM level_rewards WHERE guild_id = ? AND level <= ? ORDER BY level",
            (guild_id, level)
        )
        return [LevelReward(**dict(r)) for r in rows]
    
    async def add_reward(self, guild_id: int, level: int, role_id: int, remove_previous: bool = False) -> None:
        """ajoute une reward"""
        await db.execute(
            "INSERT OR REPLACE INTO level_rewards (guild_id, level, role_id, remove_previous) VALUES (?, ?, ?, ?)",
            (guild_id, level, role_id, int(remove_previous))
        )
    
    async def remove_reward(self, guild_id: int, level: int) -> None:
        """supprime une reward"""
        await db.execute(
            "DELETE FROM level_rewards WHERE guild_id = ? AND level = ?",
            (guild_id, level)
        )


# singleton
levels_repo = LevelsRepository()
