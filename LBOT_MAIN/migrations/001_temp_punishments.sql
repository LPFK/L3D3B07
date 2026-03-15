-- Migration 001: Table temp_punishments
-- stocke les mutes/bans temporaires pour les restaurer apres restart

CREATE TABLE IF NOT EXISTS temp_punishments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    action TEXT NOT NULL,  -- 'mute' ou 'ban'
    expires_at REAL NOT NULL,
    role_id INTEGER,  -- pour les mutes, le role mute
    created_at REAL DEFAULT (strftime('%s', 'now')),
    UNIQUE(guild_id, user_id, action)
);

CREATE INDEX IF NOT EXISTS idx_temp_punishments_expires 
    ON temp_punishments(expires_at);
