-- ============================================================
-- schema.sql
-- Schéma de la base de données d'un bot Discord multi-usage
-- Par Lilian Kozlowski
-- ============================================================

-- ============================================================
-- CONFIGURATION DES SERVEURS
-- Table centrale : chaque serveur Discord (guild) a une entrée
-- unique avec ses préférences et ses toggles de modules.
-- ============================================================

CREATE TABLE "guild_settings" (
    "guild_id" INTEGER PRIMARY KEY,
    "prefix" TEXT NOT NULL DEFAULT '!',
    "language" TEXT NOT NULL DEFAULT 'fr',

    -- Activation/désactivation de chaque module (0 = off, 1 = on)
    "levels_enabled" INTEGER NOT NULL DEFAULT 1,
    "economy_enabled" INTEGER NOT NULL DEFAULT 1,
    "welcome_enabled" INTEGER NOT NULL DEFAULT 0,
    "moderation_enabled" INTEGER NOT NULL DEFAULT 1,
    "tickets_enabled" INTEGER NOT NULL DEFAULT 0,
    "starboard_enabled" INTEGER NOT NULL DEFAULT 0,
    "suggestions_enabled" INTEGER NOT NULL DEFAULT 0,
    "birthdays_enabled" INTEGER NOT NULL DEFAULT 0,
    "temp_voice_enabled" INTEGER NOT NULL DEFAULT 0,
    "invites_enabled" INTEGER NOT NULL DEFAULT 0,
    "releases_enabled" INTEGER NOT NULL DEFAULT 0,
    "gamedeals_enabled" INTEGER NOT NULL DEFAULT 0,

    -- Paramètres additionnels flexibles en JSON
    "settings_json" TEXT NOT NULL DEFAULT '{}'
);

-- ============================================================
-- SYSTÈME DE NIVEAUX / XP
-- Gère l'expérience gagnée par message et en vocal, les
-- paliers de récompenses (rôles), et la configuration par serveur.
-- ============================================================

-- Configuration du système de niveaux pour chaque serveur
CREATE TABLE "levels_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "xp_per_message" INTEGER NOT NULL DEFAULT 15,
    "xp_cooldown" INTEGER NOT NULL DEFAULT 60,
    "xp_voice_per_minute" INTEGER NOT NULL DEFAULT 5,
    "level_up_channel_id" INTEGER,
    "level_up_message" TEXT NOT NULL DEFAULT 'Félicitations {user} ! Tu es passé au niveau **{level}** ! 🎉',
    "max_level" INTEGER NOT NULL DEFAULT 0,
    "color" TEXT NOT NULL DEFAULT '#5865F2',
    -- Listes JSON de salons/rôles exclus du gain d'XP
    "ignored_channels" TEXT NOT NULL DEFAULT '[]',
    "ignored_roles" TEXT NOT NULL DEFAULT '[]',
    -- Dictionnaire JSON : role_id -> multiplicateur XP
    "booster_roles" TEXT NOT NULL DEFAULT '{}'
);

-- Progression de chaque utilisateur par serveur
-- Clé composite (guild_id, user_id) : un user a des stats séparées par serveur
CREATE TABLE "user_levels" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "xp" INTEGER NOT NULL DEFAULT 0,
    "level" INTEGER NOT NULL DEFAULT 0,
    "total_messages" INTEGER NOT NULL DEFAULT 0,
    "voice_time" INTEGER NOT NULL DEFAULT 0,
    "last_message_xp" REAL NOT NULL DEFAULT 0,
    PRIMARY KEY ("guild_id", "user_id")
);

-- Récompenses attribuées en atteignant un certain niveau
CREATE TABLE "level_rewards" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "level" INTEGER NOT NULL,
    "role_id" INTEGER NOT NULL,
    -- Si activé, retire les rôles des paliers précédents
    "remove_previous" INTEGER NOT NULL DEFAULT 0,
    UNIQUE("guild_id", "level", "role_id")
);

-- ============================================================
-- SYSTÈME D'ÉCONOMIE
-- Monnaie virtuelle par serveur avec portefeuille, banque,
-- boutique d'articles, inventaire et jeux d'argent.
-- ============================================================

-- Configuration de l'économie par serveur
CREATE TABLE "economy_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "currency_name" TEXT NOT NULL DEFAULT 'coins',
    "currency_emoji" TEXT NOT NULL DEFAULT '💰',
    "daily_amount" INTEGER NOT NULL DEFAULT 100,
    "work_min" INTEGER NOT NULL DEFAULT 50,
    "work_max" INTEGER NOT NULL DEFAULT 200,
    "work_cooldown" INTEGER NOT NULL DEFAULT 3600,
    "voice_money_per_min" INTEGER NOT NULL DEFAULT 2,
    "starting_balance" INTEGER NOT NULL DEFAULT 0,
    "booster_roles" TEXT NOT NULL DEFAULT '{}'
);

-- Soldes et cooldowns de chaque utilisateur
CREATE TABLE "user_economy" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "wallet" INTEGER NOT NULL DEFAULT 0,
    "bank" INTEGER NOT NULL DEFAULT 0,
    "bank_max" INTEGER NOT NULL DEFAULT 10000,
    "last_daily" REAL NOT NULL DEFAULT 0,
    "last_work" REAL NOT NULL DEFAULT 0,
    "total_earned" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY ("guild_id", "user_id")
);

-- Articles disponibles à l'achat dans la boutique du serveur
CREATE TABLE "shop_items" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "price" INTEGER NOT NULL,
    "role_id" INTEGER,
    "stock" INTEGER DEFAULT -1,
    "required_role_id" INTEGER,
    "created_at" REAL NOT NULL,
    UNIQUE("guild_id", "name")
);

-- Inventaire des articles achetés par chaque utilisateur
CREATE TABLE "user_inventory" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "item_id" INTEGER NOT NULL,
    "quantity" INTEGER NOT NULL DEFAULT 1,
    "purchased_at" REAL NOT NULL
);

-- ============================================================
-- SYSTÈME DE MODÉRATION
-- Journal d'audit des sanctions, avertissements, sanctions
-- temporaires et configuration de l'automod.
-- ============================================================

-- Configuration de la modération par serveur
CREATE TABLE "mod_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "mod_log_channel_id" INTEGER,
    "mute_role_id" INTEGER,
    -- Seuils de l'automod (0 = désactivé)
    "anti_spam" INTEGER NOT NULL DEFAULT 0,
    "anti_invite" INTEGER NOT NULL DEFAULT 0,
    "anti_links" INTEGER NOT NULL DEFAULT 0,
    "bad_words" TEXT NOT NULL DEFAULT '[]',
    "links_whitelist" TEXT NOT NULL DEFAULT '[]',
    "warn_threshold" INTEGER NOT NULL DEFAULT 3,
    "warn_action" TEXT NOT NULL DEFAULT 'mute'
);

-- Chaque sanction est un « cas » numéroté par serveur
CREATE TABLE "mod_cases" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "case_number" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "moderator_id" INTEGER NOT NULL,
    "action" TEXT NOT NULL,
    "reason" TEXT,
    "duration" INTEGER,
    "created_at" REAL NOT NULL,
    UNIQUE("guild_id", "case_number")
);

-- Compteur d'avertissements actifs par utilisateur
CREATE TABLE "warnings" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "count" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY ("guild_id", "user_id")
);

-- Bans temporaires : la tâche de fond vérifie l'expiration
CREATE TABLE "temp_bans" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "expires_at" REAL NOT NULL,
    PRIMARY KEY ("guild_id", "user_id")
);

-- Mutes temporaires : même mécanisme d'expiration
CREATE TABLE "temp_mutes" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "expires_at" REAL NOT NULL,
    PRIMARY KEY ("guild_id", "user_id")
);

-- ============================================================
-- SYSTÈME DE BIENVENUE / DÉPART
-- Messages personnalisés, images, auto-rôles et DM.
-- ============================================================

CREATE TABLE "welcome_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "welcome_channel_id" INTEGER,
    "welcome_message" TEXT NOT NULL DEFAULT 'Bienvenue {user} sur **{server}** ! 🎉',
    "welcome_embed" INTEGER NOT NULL DEFAULT 1,
    "welcome_image_url" TEXT,
    "goodbye_channel_id" INTEGER,
    "goodbye_message" TEXT NOT NULL DEFAULT 'Au revoir {user} ! 👋',
    "goodbye_embed" INTEGER NOT NULL DEFAULT 1,
    "goodbye_image_url" TEXT,
    "dm_enabled" INTEGER NOT NULL DEFAULT 0,
    "dm_message" TEXT
);

-- Rôles automatiquement attribués aux nouveaux membres
CREATE TABLE "auto_roles" (
    "guild_id" INTEGER NOT NULL,
    "role_id" INTEGER NOT NULL,
    PRIMARY KEY ("guild_id", "role_id")
);

-- ============================================================
-- SYSTÈME DE TICKETS
-- Canaux de support privés avec transcripts.
-- ============================================================

CREATE TABLE "ticket_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "category_id" INTEGER,
    "log_channel_id" INTEGER,
    "support_role_id" INTEGER,
    "max_tickets_per_user" INTEGER NOT NULL DEFAULT 1,
    "ticket_message" TEXT NOT NULL DEFAULT 'Bonjour {user} ! Un membre du staff va vous aider bientôt.',
    "transcript_enabled" INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE "tickets" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "channel_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'open',
    "created_at" REAL NOT NULL,
    "closed_at" REAL,
    "closed_by" INTEGER
);

-- ============================================================
-- SYSTÈME DE GIVEAWAYS
-- Concours avec participation par bouton, conditions et tirage.
-- ============================================================

CREATE TABLE "giveaways" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "channel_id" INTEGER NOT NULL,
    "message_id" INTEGER NOT NULL,
    "prize" TEXT NOT NULL,
    "winner_count" INTEGER NOT NULL DEFAULT 1,
    "host_id" INTEGER NOT NULL,
    "end_time" REAL NOT NULL,
    "created_at" REAL NOT NULL,
    "ended" INTEGER NOT NULL DEFAULT 0,
    -- Conditions optionnelles
    "required_role_id" INTEGER,
    "required_level" INTEGER
);

-- Participations aux giveaways
CREATE TABLE "giveaway_entries" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "giveaway_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "entered_at" REAL NOT NULL,
    "won" INTEGER DEFAULT 0,
    UNIQUE("giveaway_id", "user_id")
);

-- ============================================================
-- STARBOARD
-- Mise en avant automatique des messages populaires
-- lorsqu'ils atteignent un seuil de réactions.
-- ============================================================

CREATE TABLE "starboard_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "channel_id" INTEGER,
    "emoji" TEXT NOT NULL DEFAULT '⭐',
    "threshold" INTEGER NOT NULL DEFAULT 3,
    "self_star" INTEGER NOT NULL DEFAULT 0,
    "ignore_bots" INTEGER NOT NULL DEFAULT 1,
    "ignored_channels" TEXT
);

CREATE TABLE "starboard_messages" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "channel_id" INTEGER NOT NULL,
    "original_message_id" INTEGER NOT NULL UNIQUE,
    "starboard_message_id" INTEGER NOT NULL,
    "star_count" INTEGER NOT NULL DEFAULT 0,
    "created_at" REAL NOT NULL
);

-- ============================================================
-- ANNIVERSAIRES
-- Enregistrement et annonces automatiques des anniversaires.
-- ============================================================

CREATE TABLE "birthday_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "channel_id" INTEGER,
    "role_id" INTEGER,
    "announce_hour" INTEGER NOT NULL DEFAULT 9,
    "message" TEXT,
    "allow_changes" INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE "user_birthdays" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "day" INTEGER NOT NULL,
    "month" INTEGER NOT NULL,
    "year" INTEGER,
    "updated_at" REAL,
    PRIMARY KEY ("guild_id", "user_id")
);

-- ============================================================
-- SUIVI D'INVITATIONS
-- Tracking de qui a invité qui, avec compteurs détaillés
-- (regular, leaves, fake, bonus) et récompenses.
-- ============================================================

CREATE TABLE "invite_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "join_channel_id" INTEGER,
    "leave_channel_id" INTEGER,
    "join_message" TEXT,
    "join_message_unknown" TEXT,
    "leave_message" TEXT,
    "leave_message_unknown" TEXT,
    "min_account_age" INTEGER NOT NULL DEFAULT 7
);

-- Compteurs d'invitations agrégés par utilisateur
CREATE TABLE "user_invites" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "regular" INTEGER NOT NULL DEFAULT 0,
    "leaves" INTEGER NOT NULL DEFAULT 0,
    "fake" INTEGER NOT NULL DEFAULT 0,
    "bonus" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY ("guild_id", "user_id")
);

-- Relation inviteur → invité : trace chaque adhésion
CREATE TABLE "invited_users" (
    "guild_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "inviter_id" INTEGER NOT NULL,
    "invite_code" TEXT,
    "joined_at" REAL,
    "is_fake" INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY ("guild_id", "user_id")
);

-- Récompenses en rôles pour les paliers d'invitations
CREATE TABLE "invite_rewards" (
    "guild_id" INTEGER NOT NULL,
    "required_invites" INTEGER NOT NULL,
    "role_id" INTEGER NOT NULL,
    PRIMARY KEY ("guild_id", "required_invites")
);

-- ============================================================
-- ANNONCES DE SORTIES MÉDIAS
-- Jeux, anime, séries et films : annonces automatiques
-- via les APIs RAWG, AniList et TMDB.
-- ============================================================

CREATE TABLE "releases_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "games_channel_id" INTEGER,
    "games_role_id" INTEGER,
    "anime_channel_id" INTEGER,
    "anime_role_id" INTEGER,
    "series_channel_id" INTEGER,
    "series_role_id" INTEGER,
    "films_channel_id" INTEGER,
    "films_role_id" INTEGER
);

-- Historique des annonces envoyées pour éviter les doublons
CREATE TABLE "announced_releases" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "category" TEXT NOT NULL,
    "item_id" TEXT NOT NULL,
    "announced_at" REAL NOT NULL,
    UNIQUE("guild_id", "category", "item_id")
);

-- ============================================================
-- ALERTES JEUX GRATUITS / PROMOTIONS
-- Surveillance automatique d'Epic Games Store et Steam.
-- ============================================================

CREATE TABLE "gamedeals_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "epic_channel_id" INTEGER,
    "epic_role_id" INTEGER,
    "steam_channel_id" INTEGER,
    "steam_role_id" INTEGER,
    "steam_min_discount" INTEGER NOT NULL DEFAULT 75
);

-- Historique des deals annoncés
CREATE TABLE "announced_deals" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "deal_id" TEXT NOT NULL,
    "platform" TEXT NOT NULL,
    "announced_at" REAL NOT NULL,
    UNIQUE("guild_id", "deal_id")
);

-- ============================================================
-- MESSAGES AUTOMATIQUES RÉCURRENTS
-- Messages planifiés à intervalles réguliers.
-- ============================================================

CREATE TABLE "auto_messages" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "channel_id" INTEGER NOT NULL,
    "content" TEXT,
    "embed_json" TEXT,
    "interval" INTEGER NOT NULL,
    "next_run" REAL NOT NULL,
    "last_run" REAL,
    "created_at" REAL NOT NULL,
    "enabled" INTEGER NOT NULL DEFAULT 1,
    "mention_role_id" INTEGER
);

-- ============================================================
-- RAPPELS DE BUMP
-- Rappels automatiques pour bumper le serveur (Disboard, etc.)
-- ============================================================

CREATE TABLE "bump_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "enabled" INTEGER NOT NULL DEFAULT 0,
    "channel_id" INTEGER,
    "role_id" INTEGER,
    "cooldown" INTEGER NOT NULL DEFAULT 7200,
    "message" TEXT,
    "thank_message" TEXT,
    "last_bump" REAL NOT NULL DEFAULT 0,
    "last_reminder" REAL NOT NULL DEFAULT 0
);

-- ============================================================
-- TABLES UTILITAIRES
-- Commandes personnalisées, reaction roles, rappels, etc.
-- ============================================================

-- Rôles attribués par réaction sur un message
CREATE TABLE "reaction_roles" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "channel_id" INTEGER NOT NULL,
    "message_id" INTEGER NOT NULL,
    "emoji" TEXT NOT NULL,
    "role_id" INTEGER NOT NULL,
    UNIQUE("message_id", "emoji")
);

-- Commandes personnalisées créées par les administrateurs
CREATE TABLE "custom_commands" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "name" TEXT NOT NULL,
    "response" TEXT NOT NULL,
    "embed" INTEGER NOT NULL DEFAULT 0,
    "created_by" INTEGER NOT NULL,
    "uses" INTEGER NOT NULL DEFAULT 0,
    UNIQUE("guild_id", "name")
);

-- Rappels personnels planifiés par les utilisateurs
CREATE TABLE "reminders" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "guild_id" INTEGER NOT NULL,
    "channel_id" INTEGER NOT NULL,
    "user_id" INTEGER NOT NULL,
    "message" TEXT NOT NULL,
    "remind_at" REAL NOT NULL,
    "created_at" REAL NOT NULL,
    "sent" INTEGER NOT NULL DEFAULT 0
);

-- Configuration des logs par serveur
CREATE TABLE "log_config" (
    "guild_id" INTEGER PRIMARY KEY,
    "message_log_channel" INTEGER,
    "member_log_channel" INTEGER,
    "mod_log_channel" INTEGER,
    "voice_log_channel" INTEGER,
    "server_log_channel" INTEGER
);

-- ============================================================
-- VUES
-- Vues utilitaires pour simplifier les requêtes courantes.
-- ============================================================

-- Vue : classement des utilisateurs par XP (top 100 par serveur)
CREATE VIEW "leaderboard_xp" AS
SELECT
    "guild_id",
    "user_id",
    "xp",
    "level",
    "total_messages",
    "voice_time",
    RANK() OVER (PARTITION BY "guild_id" ORDER BY "xp" DESC) AS "rank"
FROM "user_levels";

-- Vue : classement économique (fortune totale = wallet + bank)
CREATE VIEW "leaderboard_economy" AS
SELECT
    "guild_id",
    "user_id",
    "wallet",
    "bank",
    ("wallet" + "bank") AS "total_balance",
    RANK() OVER (PARTITION BY "guild_id" ORDER BY ("wallet" + "bank") DESC) AS "rank"
FROM "user_economy";

-- Vue : classement des inviteurs (invitations effectives)
CREATE VIEW "leaderboard_invites" AS
SELECT
    "guild_id",
    "user_id",
    "regular",
    "leaves",
    "fake",
    "bonus",
    ("regular" - "leaves" - "fake" + "bonus") AS "total_invites",
    RANK() OVER (PARTITION BY "guild_id" ORDER BY ("regular" - "leaves" - "fake" + "bonus") DESC) AS "rank"
FROM "user_invites";

-- Vue : giveaways actifs (non terminés)
CREATE VIEW "active_giveaways" AS
SELECT
    "id",
    "guild_id",
    "channel_id",
    "message_id",
    "prize",
    "winner_count",
    "host_id",
    "end_time",
    (SELECT COUNT(*) FROM "giveaway_entries" WHERE "giveaway_id" = "giveaways"."id") AS "participant_count"
FROM "giveaways"
WHERE "ended" = 0;

-- Vue : tickets ouverts avec durée
CREATE VIEW "open_tickets" AS
SELECT
    "id",
    "guild_id",
    "channel_id",
    "user_id",
    "created_at",
    (strftime('%s', 'now') - "created_at") AS "open_duration_seconds"
FROM "tickets"
WHERE "status" = 'open';

-- ============================================================
-- INDEX
-- Optimisent les requêtes fréquentes du bot.
-- ============================================================

-- Classements de niveaux
CREATE INDEX "idx_user_levels_guild" ON "user_levels" ("guild_id");
CREATE INDEX "idx_user_levels_xp" ON "user_levels" ("guild_id", "xp" DESC);

-- Classements d'économie
CREATE INDEX "idx_user_economy_guild" ON "user_economy" ("guild_id");

-- Recherche rapide des cas de modération
CREATE INDEX "idx_mod_cases_guild" ON "mod_cases" ("guild_id");
CREATE INDEX "idx_mod_cases_user" ON "mod_cases" ("guild_id", "user_id");

-- Invitations : classement et recherche par inviteur
CREATE INDEX "idx_user_invites_guild" ON "user_invites" ("guild_id");
CREATE INDEX "idx_invited_users_inviter" ON "invited_users" ("guild_id", "inviter_id");

-- Messages automatiques : recherche par prochaine exécution
CREATE INDEX "idx_auto_messages_next" ON "auto_messages" ("next_run");

-- Annonces : vérification des doublons
CREATE INDEX "idx_announced_releases" ON "announced_releases" ("guild_id", "category");
CREATE INDEX "idx_announced_deals" ON "announced_deals" ("guild_id", "platform");

-- Rappels non encore envoyés
CREATE INDEX "idx_reminders_pending" ON "reminders" ("remind_at") WHERE "sent" = 0;

-- Giveaways non terminés
CREATE INDEX "idx_giveaways_active" ON "giveaways" ("end_time") WHERE "ended" = 0;
