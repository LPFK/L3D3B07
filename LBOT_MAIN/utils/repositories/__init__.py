"""
Base repository + cache de config

le but c'est de separer la logique DB des cogs
comme ca on peut tester les cogs sans DB et c'est plus clean
"""

import time
import json
from typing import Optional, Any, TypeVar, Generic
from dataclasses import dataclass, asdict

from utils.database import db


# ============ CONFIG CACHE ============

class ConfigCache:
    """
    cache les configs avec un TTL
    evite de faire json.loads() sur chaque message
    """
    
    def __init__(self, table: str, ttl: int = 60):
        self.table = table
        self.ttl = ttl
        self._cache: dict[int, tuple[float, dict]] = {}
        # champs json a parser automatiquement
        self._json_fields: list[str] = []
    
    def set_json_fields(self, fields: list[str]):
        """definit les champs a parser en json au chargement"""
        self._json_fields = fields
    
    async def get(self, guild_id: int) -> dict:
        """recup config du cache ou de la db"""
        now = time.time()
        
        if guild_id in self._cache:
            cached_at, config = self._cache[guild_id]
            if now - cached_at < self.ttl:
                return config
        
        config = await self._fetch(guild_id)
        self._cache[guild_id] = (now, config)
        return config
    
    async def _fetch(self, guild_id: int) -> dict:
        """charge depuis la db"""
        row = await db.fetchone(
            f"SELECT * FROM {self.table} WHERE guild_id = ?",
            (guild_id,)
        )
        
        if not row:
            # cree la config par defaut
            await db.execute(
                f"INSERT OR IGNORE INTO {self.table} (guild_id) VALUES (?)",
                (guild_id,)
            )
            row = await db.fetchone(
                f"SELECT * FROM {self.table} WHERE guild_id = ?",
                (guild_id,)
            )
        
        if not row:
            return {}
        
        config = dict(row)
        
        # parse les champs json
        for field in self._json_fields:
            if field in config and config[field]:
                try:
                    config[field] = json.loads(config[field])
                except (json.JSONDecodeError, TypeError):
                    config[field] = [] if field.endswith('s') else {}
        
        return config
    
    def invalidate(self, guild_id: int):
        """vide le cache pour un serveur (apres modif)"""
        self._cache.pop(guild_id, None)
    
    def clear(self):
        """vide tout le cache"""
        self._cache.clear()


# ============ BASE REPOSITORY ============

T = TypeVar('T')


class BaseRepository(Generic[T]):
    """
    classe de base pour les repositories
    gere les operations CRUD basiques
    """
    
    table: str = ""
    primary_keys: tuple = ("guild_id",)
    
    def _row_to_dict(self, row) -> dict:
        """convertit une row sqlite en dict"""
        if row is None:
            return None
        return dict(row)
    
    async def get_by_guild(self, guild_id: int) -> list[dict]:
        """recup toutes les rows d'un serveur"""
        rows = await db.fetchall(
            f"SELECT * FROM {self.table} WHERE guild_id = ?",
            (guild_id,)
        )
        return [self._row_to_dict(r) for r in rows]
    
    async def delete_by_guild(self, guild_id: int) -> None:
        """supprime toutes les rows d'un serveur"""
        await db.execute(
            f"DELETE FROM {self.table} WHERE guild_id = ?",
            (guild_id,)
        )
    
    async def count_by_guild(self, guild_id: int) -> int:
        """compte les rows d'un serveur"""
        row = await db.fetchone(
            f"SELECT COUNT(*) as count FROM {self.table} WHERE guild_id = ?",
            (guild_id,)
        )
        return row["count"] if row else 0
