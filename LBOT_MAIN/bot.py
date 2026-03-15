"""
Bot Discord communautaire
clone de DraftBot avec levels, economy, moderation, etc.
"""

import discord
from discord.ext import commands
import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from utils.database import db

load_dotenv()

# logs en fichier + console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('draftbot')


class DraftBot(commands.Bot):
    """le bot principal"""
    
    def __init__(self):
        intents = discord.Intents.all()
        
        super().__init__(
            command_prefix=self.get_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
            owner_id=int(os.getenv("OWNER_ID", 0)) or None
        )
        
        self.default_prefix = os.getenv("BOT_PREFIX", "!")
        self.start_time = None
        self.prefix_cache: dict[int, str] = {}  # cache des prefix par serveur
    
    async def get_prefix(self, message: discord.Message) -> list[str]:
        """recup le prefix du serveur ou le default"""
        prefixes = [self.default_prefix]
        
        if message.guild:
            guild_id = message.guild.id
            if guild_id in self.prefix_cache:
                prefixes = [self.prefix_cache[guild_id]]
            else:
                row = await db.fetchone(
                    "SELECT prefix FROM guild_settings WHERE guild_id = ?",
                    (guild_id,)
                )
                if row:
                    self.prefix_cache[guild_id] = row["prefix"]
                    prefixes = [row["prefix"]]
        
        # on peut toujours mentionner le bot comme prefix
        return commands.when_mentioned_or(*prefixes)(self, message)
    
    async def setup_hook(self):
        """au demarrage du bot"""
        logger.info("Init...")
        
        await db.connect()
        logger.info("DB ok")
        
        # charge tous les cogs du dossier cogs/
        cogs_dir = Path(__file__).parent / "cogs"
        for cog_file in cogs_dir.glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
            cog_name = f"cogs.{cog_file.stem}"
            try:
                await self.load_extension(cog_name)
                logger.info(f"Cog charge: {cog_name}")
            except Exception as e:
                logger.error(f"Erreur chargement {cog_name}: {e}")
        
        # sync les slash commands
        try:
            synced = await self.tree.sync()
            logger.info(f"{len(synced)} slash commands sync")
        except Exception as e:
            logger.error(f"Sync fail: {e}")
    
    async def on_ready(self):
        """quand le bot est pret"""
        import time
        self.start_time = time.time()
        
        logger.info(f"Connecte: {self.user} (ID: {self.user.id})")
        logger.info(f"{len(self.guilds)} serveurs")
        
        # status du bot
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(self.guilds)} serveurs | !help"
        )
        await self.change_presence(activity=activity)
    
    async def on_guild_join(self, guild: discord.Guild):
        """quand le bot rejoint un serveur"""
        await db.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)",
            (guild.id,)
        )
        logger.info(f"Rejoint: {guild.name} ({guild.id})")
    
    async def on_guild_remove(self, guild: discord.Guild):
        """quand le bot quitte un serveur"""
        # on garde les donnees au cas ou (decommenter pour supprimer)
        # await db.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild.id,))
        if guild.id in self.prefix_cache:
            del self.prefix_cache[guild.id]
        logger.info(f"Quitte: {guild.name} ({guild.id})")
    
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """gestion globale des erreurs"""
        from utils.helpers import error_embed
        
        # commande inconnue = on ignore
        if isinstance(error, commands.CommandNotFound):
            return
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=error_embed(
                "Tu n'as pas la permission d'utiliser cette commande.",
                "Permission refusée"
            ))
            return
        
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=error_embed(
                f"Argument manquant: `{error.param.name}`\n"
                f"Utilise `{ctx.prefix}help {ctx.command}` pour plus d'infos.",
                "Argument manquant"
            ))
            return
        
        if isinstance(error, commands.BadArgument):
            await ctx.send(embed=error_embed(
                str(error),
                "Argument invalide"
            ))
            return
        
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=error_embed(
                f"Commande en cooldown. Réessaie dans **{error.retry_after:.1f}s**.",
                "Cooldown"
            ))
            return
        
        if isinstance(error, commands.CheckFailure):
            await ctx.send(embed=error_embed(
                "Tu ne peux pas utiliser cette commande ici.",
                "Accès refusé"
            ))
            return
        
        # erreur inattendue = on log
        logger.error(f"Erreur dans {ctx.command}: {error}", exc_info=error)
        await ctx.send(embed=error_embed(
            "Une erreur inattendue s'est produite. L'équipe a été notifiée.",
            "Erreur"
        ))
    
    async def close(self):
        """fermeture propre"""
        await db.close()
        await super().close()


async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("DISCORD_TOKEN manquant dans le .env !")
        return
    
    bot = DraftBot()
    
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
