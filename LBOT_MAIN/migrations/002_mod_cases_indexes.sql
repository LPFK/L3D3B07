-- Migration 002: Index sur les cases de moderation
-- ameliore les perfs des recherches par user

CREATE INDEX IF NOT EXISTS idx_mod_cases_user_action 
    ON mod_cases(guild_id, user_id, action, active);

CREATE INDEX IF NOT EXISTS idx_mod_cases_created 
    ON mod_cases(guild_id, created_at DESC);
