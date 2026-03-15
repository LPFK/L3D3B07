# Repositories

Pattern Repository pour separer la logique DB des cogs.

## Structure

```
utils/repositories/
    __init__.py      # ConfigCache + BaseRepository
    levels.py        # LevelsRepository
    economy.py       # EconomyRepository
    moderation.py    # ModerationRepository
```

## Usage dans un cog

```python
from utils.repositories.levels import levels_repo, UserLevel

class Levels(commands.Cog):
    
    async def add_xp(self, member, amount):
        # avant: await db.execute("INSERT INTO user_levels...")
        # apres:
        user = await levels_repo.add_xp(member.guild.id, member.id, amount)
        return user.xp
    
    async def get_leaderboard(self, guild_id):
        return await levels_repo.get_leaderboard(guild_id, limit=10)
```

## ConfigCache

Cache les configs avec TTL pour eviter de spam la DB:

```python
# dans le repo
self.config_cache = ConfigCache("levels_config", ttl=60)
self.config_cache.set_json_fields(["ignored_channels", "booster_roles"])

# utilisation
config = await self.config_cache.get(guild_id)
# config["ignored_channels"] est deja parse en list

# apres une modif
self.config_cache.invalidate(guild_id)
```

## Avantages

1. **Testable**: on peut mocker les repos sans DB
2. **DRY**: le SQL est centralise
3. **Type hints**: dataclasses pour les retours
4. **Cache**: moins de requetes DB
5. **Maintenable**: un seul endroit a modifier si le schema change
