"""
Systeme de migrations SQL

permet de faire evoluer le schema sans casser les donnees existantes
les migrations sont dans le dossier migrations/ sous forme de fichiers .sql

usage:
    from utils.migrations import run_migrations
    await run_migrations(connection)
"""

import aiosqlite
from pathlib import Path
import logging

logger = logging.getLogger('migrations')

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


async def get_current_version(conn: aiosqlite.Connection) -> int:
    """recup la version actuelle du schema"""
    # cree la table si elle existe pas
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at REAL DEFAULT (strftime('%s', 'now'))
        )
    """)
    await conn.commit()
    
    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    return row[0] or 0


async def run_migrations(conn: aiosqlite.Connection) -> int:
    """
    execute les migrations en attente
    retourne le nombre de migrations appliquees
    """
    current = await get_current_version(conn)
    applied = 0
    
    if not MIGRATIONS_DIR.exists():
        logger.warning(f"Dossier migrations inexistant: {MIGRATIONS_DIR}")
        return 0
    
    # liste les fichiers de migration (format: 001_name.sql)
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    
    for file in migration_files:
        # extrait le numero de version du nom de fichier
        try:
            version = int(file.stem.split("_")[0])
        except (ValueError, IndexError):
            logger.warning(f"Nom de migration invalide: {file.name} (doit etre 001_name.sql)")
            continue
        
        if version > current:
            logger.info(f"Migration {file.name}...")
            
            sql = file.read_text(encoding='utf-8')
            
            try:
                # executescript pour les migrations multi-statements
                await conn.executescript(sql)
                
                # marque comme appliquee
                await conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (version,)
                )
                await conn.commit()
                
                logger.info(f"Migration {file.name} OK")
                applied += 1
                
            except Exception as e:
                logger.error(f"Migration {file.name} ERREUR: {e}")
                await conn.rollback()
                raise
    
    if applied:
        logger.info(f"{applied} migration(s) appliquee(s)")
    
    return applied


async def get_migration_status(conn: aiosqlite.Connection) -> list[dict]:
    """
    retourne le status de toutes les migrations
    pour debug/admin
    """
    current = await get_current_version(conn)
    
    # migrations appliquees
    cursor = await conn.execute(
        "SELECT version, applied_at FROM schema_version ORDER BY version"
    )
    applied = {row[0]: row[1] for row in await cursor.fetchall()}
    
    # fichiers disponibles
    status = []
    if MIGRATIONS_DIR.exists():
        for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            try:
                version = int(file.stem.split("_")[0])
                status.append({
                    "version": version,
                    "file": file.name,
                    "applied": version in applied,
                    "applied_at": applied.get(version)
                })
            except (ValueError, IndexError):
                continue
    
    return status
