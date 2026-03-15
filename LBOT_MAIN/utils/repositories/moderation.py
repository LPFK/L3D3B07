"""
Repository Moderation - acces aux donnees moderation

cases, warns, mutes, bans, automod
"""

import time
from dataclasses import dataclass
from typing import Optional, Literal

from utils.database import db
from utils.repositories import ConfigCache


@dataclass
class ModCase:
    """un cas de moderation"""
    id: int
    guild_id: int
    user_id: int
    moderator_id: int
    action: str  # warn, mute, kick, ban, unban, unmute
    reason: str = ""
    duration: Optional[int] = None  # en secondes
    expires_at: Optional[float] = None
    created_at: float = 0
    active: bool = True


@dataclass
class TempPunishment:
    """punition temporaire (mute/ban)"""
    id: int
    guild_id: int
    user_id: int
    action: str  # mute, ban
    expires_at: float
    role_id: Optional[int] = None  # pour les mutes


class ModerationRepository:
    """acces aux donnees moderation"""
    
    def __init__(self):
        self.config_cache = ConfigCache("mod_config", ttl=60)
        self.config_cache.set_json_fields([
            "automod_ignored_channels",
            "automod_ignored_roles",
            "banned_words"
        ])
    
    # ---- CONFIG ----
    
    async def get_config(self, guild_id: int) -> dict:
        return await self.config_cache.get(guild_id)
    
    async def update_config(self, guild_id: int, **kwargs) -> None:
        if not kwargs:
            return
        
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [guild_id]
        
        await db.execute(
            f"UPDATE mod_config SET {set_clause} WHERE guild_id = ?",
            tuple(values)
        )
        self.config_cache.invalidate(guild_id)
    
    # ---- CASES ----
    
    async def create_case(
        self,
        guild_id: int,
        user_id: int,
        moderator_id: int,
        action: str,
        reason: str = "",
        duration: int = None
    ) -> ModCase:
        """cree un nouveau cas"""
        now = time.time()
        expires_at = now + duration if duration else None
        
        cursor = await db.execute("""
            INSERT INTO mod_cases (guild_id, user_id, moderator_id, action, reason, duration, expires_at, created_at, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (guild_id, user_id, moderator_id, action, reason, duration, expires_at, now))
        
        case_id = cursor.lastrowid
        
        return ModCase(
            id=case_id,
            guild_id=guild_id,
            user_id=user_id,
            moderator_id=moderator_id,
            action=action,
            reason=reason,
            duration=duration,
            expires_at=expires_at,
            created_at=now,
            active=True
        )
    
    async def get_case(self, case_id: int) -> Optional[ModCase]:
        row = await db.fetchone(
            "SELECT * FROM mod_cases WHERE id = ?",
            (case_id,)
        )
        return ModCase(**dict(row)) if row else None
    
    async def get_user_cases(
        self, 
        guild_id: int, 
        user_id: int, 
        action: str = None,
        active_only: bool = False
    ) -> list[ModCase]:
        """cases d'un user"""
        query = "SELECT * FROM mod_cases WHERE guild_id = ? AND user_id = ?"
        params = [guild_id, user_id]
        
        if action:
            query += " AND action = ?"
            params.append(action)
        
        if active_only:
            query += " AND active = 1"
        
        query += " ORDER BY created_at DESC"
        
        rows = await db.fetchall(query, tuple(params))
        return [ModCase(**dict(r)) for r in rows]
    
    async def get_recent_cases(self, guild_id: int, limit: int = 20) -> list[ModCase]:
        rows = await db.fetchall(
            "SELECT * FROM mod_cases WHERE guild_id = ? ORDER BY created_at DESC LIMIT ?",
            (guild_id, limit)
        )
        return [ModCase(**dict(r)) for r in rows]
    
    async def count_user_warns(self, guild_id: int, user_id: int) -> int:
        """compte les warns actifs d'un user"""
        row = await db.fetchone(
            "SELECT COUNT(*) as count FROM mod_cases WHERE guild_id = ? AND user_id = ? AND action = 'warn' AND active = 1",
            (guild_id, user_id)
        )
        return row["count"] if row else 0
    
    async def deactivate_case(self, case_id: int) -> None:
        """desactive un cas (pardon)"""
        await db.execute(
            "UPDATE mod_cases SET active = 0 WHERE id = ?",
            (case_id,)
        )
    
    async def clear_user_warns(self, guild_id: int, user_id: int) -> int:
        """supprime tous les warns d'un user, retourne le nombre"""
        count = await self.count_user_warns(guild_id, user_id)
        await db.execute(
            "UPDATE mod_cases SET active = 0 WHERE guild_id = ? AND user_id = ? AND action = 'warn'",
            (guild_id, user_id)
        )
        return count
    
    # ---- TEMP PUNISHMENTS ----
    
    async def add_temp_punishment(
        self,
        guild_id: int,
        user_id: int,
        action: str,  # mute ou ban
        expires_at: float,
        role_id: int = None
    ) -> None:
        """ajoute une punition temporaire"""
        await db.execute("""
            INSERT INTO temp_punishments (guild_id, user_id, action, expires_at, role_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, user_id, action) DO UPDATE SET
                expires_at = excluded.expires_at,
                role_id = excluded.role_id
        """, (guild_id, user_id, action, expires_at, role_id))
    
    async def remove_temp_punishment(self, guild_id: int, user_id: int, action: str) -> None:
        """supprime une punition temporaire"""
        await db.execute(
            "DELETE FROM temp_punishments WHERE guild_id = ? AND user_id = ? AND action = ?",
            (guild_id, user_id, action)
        )
    
    async def get_expired_punishments(self) -> list[TempPunishment]:
        """recup les punitions expirees (pour la task)"""
        now = time.time()
        rows = await db.fetchall(
            "SELECT * FROM temp_punishments WHERE expires_at <= ?",
            (now,)
        )
        return [TempPunishment(**dict(r)) for r in rows]
    
    async def get_user_temp_punishment(
        self, 
        guild_id: int, 
        user_id: int, 
        action: str
    ) -> Optional[TempPunishment]:
        """recup une punition temporaire specifique"""
        row = await db.fetchone(
            "SELECT * FROM temp_punishments WHERE guild_id = ? AND user_id = ? AND action = ?",
            (guild_id, user_id, action)
        )
        return TempPunishment(**dict(row)) if row else None
    
    # ---- STATS ----
    
    async def get_mod_stats(self, guild_id: int) -> dict:
        """stats de moderation du serveur"""
        total = await db.fetchone(
            "SELECT COUNT(*) as count FROM mod_cases WHERE guild_id = ?",
            (guild_id,)
        )
        
        by_action = await db.fetchall(
            "SELECT action, COUNT(*) as count FROM mod_cases WHERE guild_id = ? GROUP BY action",
            (guild_id,)
        )
        
        return {
            "total": total["count"] if total else 0,
            "by_action": {r["action"]: r["count"] for r in by_action}
        }
    
    async def get_moderator_stats(self, guild_id: int, moderator_id: int) -> dict:
        """stats d'un moderateur"""
        row = await db.fetchone(
            "SELECT COUNT(*) as count FROM mod_cases WHERE guild_id = ? AND moderator_id = ?",
            (guild_id, moderator_id)
        )
        return {"actions": row["count"] if row else 0}


# singleton
moderation_repo = ModerationRepository()
