"""
Database module - SQLite async database management
All tables for: levels, economy, moderation, welcome, tickets, giveaways, etc.
"""

import aiosqlite
import os
from pathlib import Path
from typing import Optional, Any
import json

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.db")


class Database:
    """Async SQLite database wrapper"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.connection: Optional[aiosqlite.Connection] = None
    
    async def connect(self):
        """Initialize database connection and create tables"""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.db_path)
        self.connection.row_factory = aiosqlite.Row
        await self._create_tables()
    
    async def close(self):
        """Close database connection"""
        if self.connection:
            await self.connection.close()
    
    async def execute(self, query: str, params: tuple = ()) -> aiosqlite.Cursor:
        """Execute a query"""
        cursor = await self.connection.execute(query, params)
        await self.connection.commit()
        return cursor
    
    async def fetchone(self, query: str, params: tuple = ()) -> Optional[aiosqlite.Row]:
        """Fetch one row"""
        cursor = await self.connection.execute(query, params)
        return await cursor.fetchone()
    
    async def fetchall(self, query: str, params: tuple = ()) -> list[aiosqlite.Row]:
        """Fetch all rows"""
        cursor = await self.connection.execute(query, params)
        return await cursor.fetchall()
    
    async def _create_tables(self):
        """Create all database tables"""
        
        # ==================== GUILD SETTINGS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id INTEGER PRIMARY KEY,
                prefix TEXT DEFAULT '!',
                language TEXT DEFAULT 'fr',
                
                -- Module toggles
                levels_enabled INTEGER DEFAULT 1,
                economy_enabled INTEGER DEFAULT 1,
                welcome_enabled INTEGER DEFAULT 0,
                moderation_enabled INTEGER DEFAULT 1,
                tickets_enabled INTEGER DEFAULT 0,
                starboard_enabled INTEGER DEFAULT 0,
                suggestions_enabled INTEGER DEFAULT 0,
                birthdays_enabled INTEGER DEFAULT 0,
                temp_voice_enabled INTEGER DEFAULT 0,
                invites_enabled INTEGER DEFAULT 0,
                releases_enabled INTEGER DEFAULT 0,
                gamedeals_enabled INTEGER DEFAULT 0,
                
                -- General settings stored as JSON
                settings_json TEXT DEFAULT '{}'
            )
        """)
        
        # ==================== LEVELS SYSTEM ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS levels_config (
                guild_id INTEGER PRIMARY KEY,
                xp_per_message INTEGER DEFAULT 15,
                xp_cooldown INTEGER DEFAULT 60,
                xp_voice_per_minute INTEGER DEFAULT 5,
                level_up_channel_id INTEGER,
                level_up_message TEXT DEFAULT 'Félicitations {user} ! Tu es passé au niveau **{level}** ! 🎉',
                max_level INTEGER DEFAULT 0,
                color TEXT DEFAULT '#5865F2',
                ignored_channels TEXT DEFAULT '[]',
                ignored_roles TEXT DEFAULT '[]',
                booster_roles TEXT DEFAULT '{}'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS user_levels (
                guild_id INTEGER,
                user_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                total_messages INTEGER DEFAULT 0,
                voice_time INTEGER DEFAULT 0,
                last_xp_time REAL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS level_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                level INTEGER,
                role_id INTEGER,
                remove_previous INTEGER DEFAULT 0,
                UNIQUE(guild_id, level, role_id)
            )
        """)
        
        # ==================== ECONOMY SYSTEM ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS economy_config (
                guild_id INTEGER PRIMARY KEY,
                currency_name TEXT DEFAULT 'coins',
                currency_emoji TEXT DEFAULT '🪙',
                daily_amount INTEGER DEFAULT 100,
                work_min INTEGER DEFAULT 50,
                work_max INTEGER DEFAULT 200,
                work_cooldown INTEGER DEFAULT 3600,
                voice_money_per_minute INTEGER DEFAULT 1,
                color TEXT DEFAULT '#F1C40F',
                booster_roles TEXT DEFAULT '{}'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS user_economy (
                guild_id INTEGER,
                user_id INTEGER,
                balance INTEGER DEFAULT 0,
                bank INTEGER DEFAULT 0,
                last_daily REAL DEFAULT 0,
                last_work REAL DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                name TEXT,
                description TEXT,
                price INTEGER,
                role_id INTEGER,
                stock INTEGER DEFAULT -1,
                required_role_id INTEGER,
                created_at REAL
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS user_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                item_id INTEGER,
                quantity INTEGER DEFAULT 1,
                purchased_at REAL,
                FOREIGN KEY (item_id) REFERENCES shop_items(id)
            )
        """)
        
        # ==================== WELCOME/GOODBYE ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS welcome_config (
                guild_id INTEGER PRIMARY KEY,
                welcome_channel_id INTEGER,
                welcome_message TEXT DEFAULT 'Bienvenue {user} sur **{server}** ! 🎉',
                welcome_embed INTEGER DEFAULT 1,
                welcome_image_url TEXT,
                goodbye_channel_id INTEGER,
                goodbye_message TEXT DEFAULT 'Au revoir {user} ! 👋',
                goodbye_embed INTEGER DEFAULT 1,
                goodbye_image_url TEXT,
                dm_message TEXT,
                dm_enabled INTEGER DEFAULT 0
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS auto_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                role_id INTEGER,
                UNIQUE(guild_id, role_id)
            )
        """)
        
        # ==================== MODERATION ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS mod_config (
                guild_id INTEGER PRIMARY KEY,
                mod_log_channel_id INTEGER,
                mute_role_id INTEGER,
                
                -- Anti-spam settings
                antispam_enabled INTEGER DEFAULT 0,
                antispam_messages INTEGER DEFAULT 5,
                antispam_seconds INTEGER DEFAULT 5,
                antispam_action TEXT DEFAULT 'mute',
                
                -- Anti-invite
                anti_invite_enabled INTEGER DEFAULT 0,
                anti_invite_action TEXT DEFAULT 'delete',
                
                -- Anti-links
                anti_links_enabled INTEGER DEFAULT 0,
                allowed_links TEXT DEFAULT '[]',
                
                -- Bad words
                bad_words_enabled INTEGER DEFAULT 0,
                bad_words TEXT DEFAULT '[]',
                bad_words_action TEXT DEFAULT 'delete'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS mod_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                moderator_id INTEGER,
                action TEXT,
                reason TEXT,
                duration INTEGER,
                created_at REAL,
                expires_at REAL
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                user_id INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                created_at REAL
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS temp_bans (
                guild_id INTEGER,
                user_id INTEGER,
                expires_at REAL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS temp_mutes (
                guild_id INTEGER,
                user_id INTEGER,
                expires_at REAL,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        # ==================== TICKETS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS ticket_config (
                guild_id INTEGER PRIMARY KEY,
                category_id INTEGER,
                log_channel_id INTEGER,
                support_role_id INTEGER,
                ticket_message TEXT DEFAULT 'Bonjour {user} ! Un membre du staff va vous aider bientôt.',
                max_tickets_per_user INTEGER DEFAULT 1,
                auto_close_hours INTEGER DEFAULT 0,
                transcript_enabled INTEGER DEFAULT 1
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER UNIQUE,
                user_id INTEGER,
                status TEXT DEFAULT 'open',
                subject TEXT,
                created_at REAL,
                closed_at REAL,
                closed_by INTEGER
            )
        """)
        
        # ==================== GIVEAWAYS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                message_id INTEGER UNIQUE,
                host_id INTEGER,
                prize TEXT,
                winners_count INTEGER DEFAULT 1,
                required_role_id INTEGER,
                ends_at REAL,
                ended INTEGER DEFAULT 0,
                winner_ids TEXT DEFAULT '[]'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_entries (
                giveaway_id INTEGER,
                user_id INTEGER,
                entries INTEGER DEFAULT 1,
                PRIMARY KEY (giveaway_id, user_id),
                FOREIGN KEY (giveaway_id) REFERENCES giveaways(id)
            )
        """)
        
        # ==================== SUGGESTIONS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS suggestions_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                review_channel_id INTEGER,
                approved_channel_id INTEGER,
                denied_channel_id INTEGER,
                auto_thread INTEGER DEFAULT 0,
                anonymous INTEGER DEFAULT 0,
                upvote_emoji TEXT DEFAULT '👍',
                downvote_emoji TEXT DEFAULT '👎'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                message_id INTEGER UNIQUE,
                user_id INTEGER,
                content TEXT,
                status TEXT DEFAULT 'pending',
                upvotes INTEGER DEFAULT 0,
                downvotes INTEGER DEFAULT 0,
                review_note TEXT,
                reviewed_by INTEGER,
                created_at REAL
            )
        """)
        
        # ==================== STARBOARD ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS starboard_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                threshold INTEGER DEFAULT 3,
                emoji TEXT DEFAULT '⭐',
                self_star INTEGER DEFAULT 0,
                ignore_channels TEXT DEFAULT '[]'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS starboard_messages (
                original_message_id INTEGER PRIMARY KEY,
                guild_id INTEGER,
                starboard_message_id INTEGER,
                channel_id INTEGER,
                author_id INTEGER,
                star_count INTEGER DEFAULT 0
            )
        """)
        
        # ==================== BIRTHDAYS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS birthday_config (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                role_id INTEGER,
                message TEXT DEFAULT '🎂 Joyeux anniversaire {user} ! 🎉',
                announce_time TEXT DEFAULT '09:00'
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS user_birthdays (
                guild_id INTEGER,
                user_id INTEGER,
                day INTEGER,
                month INTEGER,
                year INTEGER,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        # ==================== TEMPORARY VOICE ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS temp_voice_config (
                guild_id INTEGER PRIMARY KEY,
                creator_channel_id INTEGER,
                category_id INTEGER,
                default_name TEXT DEFAULT '{user}''s channel',
                default_limit INTEGER DEFAULT 0
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS temp_voice_channels (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER,
                owner_id INTEGER,
                created_at REAL
            )
        """)
        
        # ==================== ROLE REACTIONS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS reaction_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                message_id INTEGER,
                emoji TEXT,
                role_id INTEGER,
                UNIQUE(message_id, emoji)
            )
        """)
        
        # ==================== CUSTOM COMMANDS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS custom_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                name TEXT,
                response TEXT,
                embed INTEGER DEFAULT 0,
                created_by INTEGER,
                uses INTEGER DEFAULT 0,
                UNIQUE(guild_id, name)
            )
        """)
        
        # ==================== REMINDERS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                user_id INTEGER,
                message TEXT,
                remind_at REAL,
                created_at REAL,
                sent INTEGER DEFAULT 0
            )
        """)
        
        # ==================== LOGS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS log_config (
                guild_id INTEGER PRIMARY KEY,
                message_log_channel INTEGER,
                member_log_channel INTEGER,
                mod_log_channel INTEGER,
                voice_log_channel INTEGER,
                server_log_channel INTEGER
            )
        """)
        
        # ==================== SOCIAL NOTIFICATIONS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS social_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                platform TEXT,
                platform_id TEXT,
                custom_message TEXT,
                last_check TEXT,
                UNIQUE(guild_id, platform, platform_id)
            )
        """)
        
        # ==================== INVITE TRACKING ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS invite_config (
                guild_id INTEGER PRIMARY KEY,
                join_channel_id INTEGER,
                leave_channel_id INTEGER,
                join_message TEXT,
                join_message_unknown TEXT,
                leave_message TEXT,
                leave_message_unknown TEXT,
                min_account_age INTEGER DEFAULT 7
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS user_invites (
                guild_id INTEGER,
                user_id INTEGER,
                regular INTEGER DEFAULT 0,
                leaves INTEGER DEFAULT 0,
                fake INTEGER DEFAULT 0,
                bonus INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS invited_users (
                guild_id INTEGER,
                user_id INTEGER,
                inviter_id INTEGER,
                invite_code TEXT,
                joined_at REAL,
                is_fake INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS invite_rewards (
                guild_id INTEGER,
                required_invites INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, required_invites)
            )
        """)
        
        # ==================== RELEASES (Games/Anime/Series/Films) ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS releases_config (
                guild_id INTEGER PRIMARY KEY,
                games_channel_id INTEGER,
                games_role_id INTEGER,
                anime_channel_id INTEGER,
                anime_role_id INTEGER,
                series_channel_id INTEGER,
                series_role_id INTEGER,
                films_channel_id INTEGER,
                films_role_id INTEGER
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS announced_releases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                category TEXT,
                item_id TEXT,
                announced_at REAL,
                UNIQUE(guild_id, category, item_id)
            )
        """)
        
        # ==================== GAME DEALS (Epic/Steam) ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS gamedeals_config (
                guild_id INTEGER PRIMARY KEY,
                epic_channel_id INTEGER,
                epic_role_id INTEGER,
                steam_channel_id INTEGER,
                steam_role_id INTEGER,
                steam_min_discount INTEGER DEFAULT 75
            )
        """)
        
        await self.execute("""
            CREATE TABLE IF NOT EXISTS announced_deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                deal_id TEXT,
                platform TEXT,
                announced_at REAL,
                UNIQUE(guild_id, deal_id)
            )
        """)
        
        # ==================== AUTO MESSAGES ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS auto_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                content TEXT,
                embed_json TEXT,
                interval INTEGER,
                next_run REAL,
                last_run REAL,
                created_at REAL,
                enabled INTEGER DEFAULT 1,
                mention_role_id INTEGER
            )
        """)
        
        # ==================== BUMP REMINDERS ====================
        await self.execute("""
            CREATE TABLE IF NOT EXISTS bump_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                channel_id INTEGER,
                role_id INTEGER,
                cooldown INTEGER DEFAULT 7200,
                message TEXT,
                thank_message TEXT,
                last_bump REAL DEFAULT 0,
                last_reminder REAL DEFAULT 0
            )
        """)
        
        # Create indexes for performance
        await self.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_guild ON user_levels(guild_id)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_user_levels_xp ON user_levels(guild_id, xp DESC)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_user_economy_guild ON user_economy(guild_id)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_mod_cases_guild ON mod_cases(guild_id)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_mod_cases_user ON mod_cases(guild_id, user_id)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_user_invites_guild ON user_invites(guild_id)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_invited_users_inviter ON invited_users(guild_id, inviter_id)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_auto_messages_next ON auto_messages(next_run)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_announced_releases ON announced_releases(guild_id, category)")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_announced_deals ON announced_deals(guild_id, platform)")


# Singleton instance
db = Database()
