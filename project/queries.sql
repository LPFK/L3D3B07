ON CONF-- ============================================================
-- queries.sql
-- Requêtes typiques exécutées sur la base de données du bot
-- Par Lilian Kozlowski
-- ============================================================


-- ============================================================
-- CONFIGURATION DES SERVEURS
-- ============================================================

-- Initialiser un nouveau serveur quand le bot le rejoint
INSERT INTO "guild_settings" ("guild_id")
VALUES (123456789012345678);

-- Récupérer le préfixe et les modules actifs d'un serveur
SELECT "prefix", "levels_enabled", "economy_enabled", "moderation_enabled"
FROM "guild_settings"
WHERE "guild_id" = 123456789012345678;

-- Changer le préfixe d'un serveur
UPDATE "guild_settings"
SET "prefix" = '?'
WHERE "guild_id" = 123456789012345678;

-- Activer le module de bienvenue pour un serveur
UPDATE "guild_settings"
SET "welcome_enabled" = 1
WHERE "guild_id" = 123456789012345678;


-- ============================================================
-- SYSTÈME DE NIVEAUX / XP
-- ============================================================

-- Ajouter de l'XP à un utilisateur après un message (upsert)
INSERT INTO "user_levels" ("guild_id", "user_id", "xp", "total_messages", "last_message_xp")
VALUES (123456789012345678, 987654321098765432, 15, 1, strftime('%s', 'now'))
ON CONFLICT ("guild_id", "user_id") DO UPDATE SET
    "xp" = "xp" + 15,
    "total_messages" = "total_messages" + 1,
    "last_message_xp" = strftime('%s', 'now');

-- Mettre à jour le niveau d'un utilisateur après un gain d'XP
UPDATE "user_levels"
SET "level" = 5
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;

-- Afficher le classement XP d'un serveur (top 10)
SELECT "user_id", "xp", "level", "total_messages", "rank"
FROM "leaderboard_xp"
WHERE "guild_id" = 123456789012345678
ORDER BY "rank" ASC
LIMIT 10;

-- Trouver le rang d'un utilisateur spécifique sur un serveur
SELECT "rank", "xp", "level"
FROM "leaderboard_xp"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;

-- Vérifier si l'utilisateur respecte le cooldown d'XP (60 secondes)
SELECT "user_id"
FROM "user_levels"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432
AND (strftime('%s', 'now') - "last_message_xp") < 60;

-- Récupérer les récompenses de niveau disponibles pour un serveur
SELECT "level", "role_id", "remove_previous"
FROM "level_rewards"
WHERE "guild_id" = 123456789012345678
ORDER BY "level" ASC;

-- Ajouter une récompense : rôle attribué au niveau 10
INSERT INTO "level_rewards" ("guild_id", "level", "role_id")
VALUES (123456789012345678, 10, 111222333444555666);

-- Réinitialiser l'XP d'un utilisateur
DELETE FROM "user_levels"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;


-- ============================================================
-- SYSTÈME D'ÉCONOMIE
-- ============================================================

-- Vérifier le solde d'un utilisateur
SELECT "wallet", "bank", ("wallet" + "bank") AS "total"
FROM "user_economy"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;

-- Réclamer la récompense quotidienne (daily)
UPDATE "user_economy"
SET "wallet" = "wallet" + 100,
    "last_daily" = strftime('%s', 'now'),
    "total_earned" = "total_earned" + 100
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;

-- Déposer de l'argent du portefeuille vers la banque
UPDATE "user_economy"
SET "wallet" = "wallet" - 500,
    "bank" = MIN("bank" + 500, "bank_max")
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432
AND "wallet" >= 500;

-- Transférer de l'argent entre deux utilisateurs
-- Étape 1 : retirer du portefeuille de l'expéditeur
UPDATE "user_economy"
SET "wallet" = "wallet" - 200
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432
AND "wallet" >= 200;

-- Étape 2 : ajouter au portefeuille du destinataire
UPDATE "user_economy"
SET "wallet" = "wallet" + 200
WHERE "guild_id" = 123456789012345678
AND "user_id" = 111111111111111111;

-- Acheter un article de la boutique
INSERT INTO "user_inventory" ("guild_id", "user_id", "item_id", "quantity", "purchased_at")
VALUES (123456789012345678, 987654321098765432, 1, 1, strftime('%s', 'now'));

-- Décrémenter le stock de l'article acheté
UPDATE "shop_items"
SET "stock" = "stock" - 1
WHERE "id" = 1
AND "stock" > 0;

-- Afficher le classement économique d'un serveur
SELECT "user_id", "total_balance", "rank"
FROM "leaderboard_economy"
WHERE "guild_id" = 123456789012345678
ORDER BY "rank" ASC
LIMIT 10;

-- Lister les articles de la boutique d'un serveur
SELECT "id", "name", "description", "price", "role_id", "stock"
FROM "shop_items"
WHERE "guild_id" = 123456789012345678
ORDER BY "price" ASC;


-- ============================================================
-- MODÉRATION
-- ============================================================

-- Enregistrer une nouvelle sanction (ban, kick, mute, warn)
INSERT INTO "mod_cases" ("guild_id", "case_number", "user_id", "moderator_id", "action", "reason", "duration", "created_at")
VALUES (
    123456789012345678,
    (SELECT COALESCE(MAX("case_number"), 0) + 1 FROM "mod_cases" WHERE "guild_id" = 123456789012345678),
    987654321098765432,
    555555555555555555,
    'ban',
    'Spam répété',
    86400,
    strftime('%s', 'now')
);

-- Consulter l'historique de modération d'un utilisateur
SELECT "case_number", "action", "reason", "moderator_id", "created_at"
FROM "mod_cases"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432
ORDER BY "created_at" DESC;

-- Ajouter un avertissement (incrémenter le compteur)
INSERT INTO "warnings" ("guild_id", "user_id", "count")
VALUES (123456789012345678, 987654321098765432, 1)
ON CONFLICT ("guild_id", "user_id") DO UPDATE SET
    "count" = "count" + 1;

-- Vérifier si un utilisateur a dépassé le seuil d'avertissements
SELECT w."count", mc."warn_threshold", mc."warn_action"
FROM "warnings" w
JOIN "mod_config" mc ON w."guild_id" = mc."guild_id"
WHERE w."guild_id" = 123456789012345678
AND w."user_id" = 987654321098765432
AND w."count" >= mc."warn_threshold";

-- Ajouter un ban temporaire (expire dans 24h)
INSERT INTO "temp_bans" ("guild_id", "user_id", "expires_at")
VALUES (123456789012345678, 987654321098765432, strftime('%s', 'now') + 86400);

-- Trouver les bans temporaires expirés (tâche de fond)
SELECT "guild_id", "user_id"
FROM "temp_bans"
WHERE "expires_at" <= strftime('%s', 'now');

-- Retirer un ban temporaire expiré
DELETE FROM "temp_bans"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;


-- ============================================================
-- GIVEAWAYS
-- ============================================================

-- Créer un nouveau giveaway
INSERT INTO "giveaways" ("guild_id", "channel_id", "message_id", "prize", "winner_count", "host_id", "end_time", "created_at")
VALUES (123456789012345678, 444444444444444444, 555555555555555555, 'Nitro Discord', 1, 111111111111111111, strftime('%s', 'now') + 86400, strftime('%s', 'now'));

-- Un utilisateur participe au giveaway
INSERT OR IGNORE INTO "giveaway_entries" ("giveaway_id", "user_id", "entered_at")
VALUES (1, 987654321098765432, strftime('%s', 'now'));

-- Compter les participants d'un giveaway
SELECT COUNT(*) AS "participant_count"
FROM "giveaway_entries"
WHERE "giveaway_id" = 1;

-- Trouver les giveaways qui doivent se terminer (tâche de fond)
SELECT *
FROM "active_giveaways"
WHERE "end_time" <= strftime('%s', 'now');

-- Tirer un gagnant au hasard parmi les participants
SELECT "user_id"
FROM "giveaway_entries"
WHERE "giveaway_id" = 1
ORDER BY RANDOM()
LIMIT 1;

-- Marquer le giveaway comme terminé
UPDATE "giveaways"
SET "ended" = 1
WHERE "id" = 1;


-- ============================================================
-- TICKETS
-- ============================================================

-- Ouvrir un nouveau ticket
INSERT INTO "tickets" ("guild_id", "channel_id", "user_id", "created_at")
VALUES (123456789012345678, 666666666666666666, 987654321098765432, strftime('%s', 'now'));

-- Vérifier combien de tickets ouverts a un utilisateur
SELECT COUNT(*) AS "open_count"
FROM "tickets"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432
AND "status" = 'open';

-- Fermer un ticket
UPDATE "tickets"
SET "status" = 'closed',
    "closed_at" = strftime('%s', 'now'),
    "closed_by" = 555555555555555555
WHERE "channel_id" = 666666666666666666;

-- Voir les tickets ouverts avec leur durée
SELECT "id", "user_id", "created_at", "open_duration_seconds"
FROM "open_tickets"
WHERE "guild_id" = 123456789012345678;


-- ============================================================
-- SUIVI D'INVITATIONS
-- ============================================================

-- Incrémenter les invitations régulières d'un inviteur
INSERT INTO "user_invites" ("guild_id", "user_id", "regular")
VALUES (123456789012345678, 111111111111111111, 1)
ON CONFLICT ("guild_id", "user_id") DO UPDATE SET
    "regular" = "regular" + 1;

-- Enregistrer qui a invité un nouveau membre
INSERT OR REPLACE INTO "invited_users" ("guild_id", "user_id", "inviter_id", "invite_code", "joined_at")
VALUES (123456789012345678, 987654321098765432, 111111111111111111, 'abcDEF', strftime('%s', 'now'));

-- Classement des meilleurs inviteurs
SELECT "user_id", "total_invites", "regular", "leaves", "fake", "bonus", "rank"
FROM "leaderboard_invites"
WHERE "guild_id" = 123456789012345678
ORDER BY "rank" ASC
LIMIT 10;

-- Trouver qui a invité un membre spécifique
SELECT "inviter_id", "invite_code", "joined_at"
FROM "invited_users"
WHERE "guild_id" = 123456789012345678
AND "user_id" = 987654321098765432;

-- Quand un invité quitte : incrémenter le compteur "leaves"
UPDATE "user_invites"
SET "leaves" = "leaves" + 1
WHERE "guild_id" = 123456789012345678
AND "user_id" = (
    SELECT "inviter_id"
    FROM "invited_users"
    WHERE "guild_id" = 123456789012345678
    AND "user_id" = 987654321098765432
);

-- Vérifier les récompenses débloquées par un inviteur
SELECT ir."required_invites", ir."role_id"
FROM "invite_rewards" ir
WHERE ir."guild_id" = 123456789012345678
AND ir."required_invites" <= (
    SELECT ("regular" - "leaves" - "fake" + "bonus")
    FROM "user_invites"
    WHERE "guild_id" = 123456789012345678
    AND "user_id" = 111111111111111111
)
ORDER BY ir."required_invites" DESC;


-- ============================================================
-- ANNIVERSAIRES
-- ============================================================

-- Enregistrer son anniversaire
INSERT OR REPLACE INTO "user_birthdays" ("guild_id", "user_id", "day", "month", "year", "updated_at")
VALUES (123456789012345678, 987654321098765432, 15, 6, 2002, strftime('%s', 'now'));

-- Trouver les anniversaires du jour (tâche de fond)
SELECT ub."user_id", ub."day", ub."month", ub."year", bc."channel_id", bc."role_id"
FROM "user_birthdays" ub
JOIN "birthday_config" bc ON ub."guild_id" = bc."guild_id"
JOIN "guild_settings" gs ON ub."guild_id" = gs."guild_id"
WHERE gs."birthdays_enabled" = 1
AND bc."channel_id" IS NOT NULL
AND ub."day" = CAST(strftime('%d', 'now') AS INTEGER)
AND ub."month" = CAST(strftime('%m', 'now') AS INTEGER);

-- Prochains anniversaires d'un serveur (triés par proximité)
SELECT "user_id", "day", "month",
    CASE
        WHEN ("month" * 100 + "day") >= (CAST(strftime('%m', 'now') AS INTEGER) * 100 + CAST(strftime('%d', 'now') AS INTEGER))
        THEN ("month" * 100 + "day") - (CAST(strftime('%m', 'now') AS INTEGER) * 100 + CAST(strftime('%d', 'now') AS INTEGER))
        ELSE (1200 + "month" * 100 + "day") - (CAST(strftime('%m', 'now') AS INTEGER) * 100 + CAST(strftime('%d', 'now') AS INTEGER))
    END AS "days_approx"
FROM "user_birthdays"
WHERE "guild_id" = 123456789012345678
ORDER BY "days_approx" ASC
LIMIT 10;


-- ============================================================
-- STARBOARD
-- ============================================================

-- Ajouter un message au starboard
INSERT INTO "starboard_messages" ("guild_id", "channel_id", "original_message_id", "starboard_message_id", "star_count", "created_at")
VALUES (123456789012345678, 444444444444444444, 777777777777777777, 888888888888888888, 3, strftime('%s', 'now'));

-- Mettre à jour le nombre d'étoiles
UPDATE "starboard_messages"
SET "star_count" = 5
WHERE "original_message_id" = 777777777777777777;

-- Retirer du starboard si en dessous du seuil
DELETE FROM "starboard_messages"
WHERE "original_message_id" = 777777777777777777;

-- Afficher un message aléatoire du starboard
SELECT *
FROM "starboard_messages"
WHERE "guild_id" = 123456789012345678
ORDER BY RANDOM()
LIMIT 1;


-- ============================================================
-- MESSAGES AUTOMATIQUES ET BUMP
-- ============================================================

-- Créer un message automatique récurrent (toutes les 2 heures)
INSERT INTO "auto_messages" ("guild_id", "channel_id", "content", "interval", "next_run", "created_at")
VALUES (123456789012345678, 444444444444444444, 'N''oubliez pas de bump le serveur ! /bump', 7200, strftime('%s', 'now') + 7200, strftime('%s', 'now'));

-- Trouver les messages automatiques à envoyer maintenant (tâche de fond)
SELECT *
FROM "auto_messages"
WHERE "enabled" = 1
AND "next_run" <= strftime('%s', 'now');

-- Après envoi : planifier la prochaine exécution
UPDATE "auto_messages"
SET "next_run" = strftime('%s', 'now') + "interval",
    "last_run" = strftime('%s', 'now')
WHERE "id" = 1;

-- Enregistrer un bump réussi
UPDATE "bump_config"
SET "last_bump" = strftime('%s', 'now')
WHERE "guild_id" = 123456789012345678;

-- Vérifier si le rappel de bump doit être envoyé
SELECT *
FROM "bump_config"
WHERE "enabled" = 1
AND "channel_id" IS NOT NULL
AND (strftime('%s', 'now') - "last_bump") >= "cooldown"
AND (strftime('%s', 'now') - "last_reminder") >= 300;


-- ============================================================
-- ANNONCES ET DEALS
-- ============================================================

-- Vérifier si un jeu/anime/film a déjà été annoncé (éviter doublons)
SELECT COUNT(*) AS "already_announced"
FROM "announced_releases"
WHERE "guild_id" = 123456789012345678
AND "category" = 'game'
AND "item_id" = '12345';

-- Marquer une sortie comme annoncée
INSERT INTO "announced_releases" ("guild_id", "category", "item_id", "announced_at")
VALUES (123456789012345678, 'anime', 'one_piece_ep1100', strftime('%s', 'now'));

-- Vérifier si un deal a déjà été annoncé
SELECT COUNT(*) AS "already_announced"
FROM "announced_deals"
WHERE "guild_id" = 123456789012345678
AND "deal_id" = 'epic_fortnite_free';

-- Nettoyer les annonces de plus de 30 jours (maintenance)
DELETE FROM "announced_releases"
WHERE "announced_at" < strftime('%s', 'now') - 2592000;

DELETE FROM "announced_deals"
WHERE "announced_at" < strftime('%s', 'now') - 2592000;
