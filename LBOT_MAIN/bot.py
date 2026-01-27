"""
DraftBot Clone - Main bot file
A feature-rich Discord bot inspired by DraftBot
"""

import discord
from discord.ext import commands
import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

from utils.database import db

# Load environment variables
load_dotenv()

# Setup logging
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
    """Main bot class"""
    
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
        self.prefix_cache: dict[int, str] = {}
    
    async def get_prefix(self, message: discord.Message) -> list[str]:
        """Get guild-specific prefix or default"""
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
        
        # Always allow mention as prefix
        return commands.when_mentioned_or(*prefixes)(self, message)
    
    async def setup_hook(self):
        """Called when bot is starting up"""
        logger.info("Initializing bot...")
        
        # Connect to database
        await db.connect()
        logger.info("Database connected")
        
        # Load all cogs
        cogs_dir = Path(__file__).parent / "cogs"
        for cog_file in cogs_dir.glob("*.py"):
            if cog_file.name.startswith("_"):
                continue
            cog_name = f"cogs.{cog_file.stem}"
            try:
                await self.load_extension(cog_name)
                logger.info(f"Loaded cog: {cog_name}")
            except Exception as e:
                logger.error(f"Failed to load {cog_name}: {e}")
        
        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} slash commands")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")
    
    async def on_ready(self):
        """Called when bot is ready"""
        import time
        self.start_time = time.time()
        
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        logger.info(f"Connected to {len(self.guilds)} guilds")
        
        # Set presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{len(self.guilds)} serveurs | !help"
        )
        await self.change_presence(activity=activity)
    
    async def on_guild_join(self, guild: discord.Guild):
        """Initialize settings when joining a new guild"""
        await db.execute(
            "INSERT OR IGNORE INTO guild_settings (guild_id) VALUES (?)",
            (guild.id,)
        )
        logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")
    
    async def on_guild_remove(self, guild: discord.Guild):
        """Clean up when leaving a guild"""
        # Optionally clean up data (uncomment if you want to delete data on leave)
        # await db.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild.id,))
        if guild.id in self.prefix_cache:
            del self.prefix_cache[guild.id]
        logger.info(f"Left guild: {guild.name} (ID: {guild.id})")
    
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        """Global error handler"""
        from utils.helpers import error_embed
        
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
        
        # Log unexpected errors
        logger.error(f"Unhandled error in {ctx.command}: {error}", exc_info=error)
        await ctx.send(embed=error_embed(
            "Une erreur inattendue s'est produite. L'équipe a été notifiée.",
            "Erreur"
        ))
    
    async def close(self):
        """Clean up when bot is shutting down"""
        await db.close()
        await super().close()


async def main():
    """Main entry point"""
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        logger.error("No DISCORD_TOKEN found in environment variables!")
        return
    
    bot = DraftBot()
    
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
