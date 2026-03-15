# Migrations

Systeme simple de migrations SQL.

## Comment ca marche

1. Les migrations sont des fichiers `.sql` dans `migrations/`
2. Format du nom: `001_description.sql`, `002_autre.sql`, etc.
3. Au demarrage, le bot execute les migrations pas encore appliquees
4. La table `schema_version` track les versions appliquees

## Creer une migration

```sql
-- migrations/003_add_new_feature.sql

-- toujours utiliser IF NOT EXISTS pour etre idempotent
CREATE TABLE IF NOT EXISTS ma_nouvelle_table (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    data TEXT
);

CREATE INDEX IF NOT EXISTS idx_ma_table_guild 
    ON ma_nouvelle_table(guild_id);
```

## Regles

1. **Numeros sequentiels**: 001, 002, 003...
2. **Jamais modifier une migration appliquee**: cree une nouvelle migration
3. **Idempotent**: utilise `IF NOT EXISTS`, `INSERT OR IGNORE`, etc.
4. **Petites migrations**: une feature par migration
5. **Teste avant push**: la migration doit pas casser l'existant

## Verifier le status

```python
from utils.migrations import get_migration_status

status = await get_migration_status(db.connection)
for m in status:
    print(f"{m['file']}: {'✓' if m['applied'] else '✗'}")
```

## Rollback

Y'a pas de rollback auto. Pour annuler:
1. Cree une nouvelle migration qui fait l'inverse
2. Ou restore un backup de la DB

## Exemple

```
migrations/
    001_temp_punishments.sql    # table pour mutes/bans temp
    002_mod_cases_indexes.sql   # index de perf
    003_add_user_badges.sql     # nouvelle feature badges
```
