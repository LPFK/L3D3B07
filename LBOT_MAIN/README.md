# 🤖 DraftBot Clone

Bot Discord communautaire multi-usage inspiré de [DraftBot], développé en Python avec [discord.py](https://discordpy.readthedocs.io/). Il regroupe 12 modules couvrant la gestion complète d'un serveur Discord : niveaux, économie, modération, bienvenue, tickets, giveaways, starboard, anniversaires, invitations, sorties médias, alertes de jeux gratuits et messages automatiques.

Le bot inclut également un **dashboard web** (Flask) permettant de tout configurer via une interface graphique avec authentification Discord OAuth2.

---

## Structure du projet

```
draftbot-clone/
├── bot.py                  # Point d'entrée principal
├── requirements.txt        # Dépendances Python du bot
├── .env.example            # Template de configuration
│
├── cogs/                   # Modules du bot (12 cogs)
│   ├── levels.py           # XP, niveaux, classements, récompenses
│   ├── economy.py          # Monnaie virtuelle, boutique, jeux d'argent
│   ├── moderation.py       # Ban, kick, mute, automod, logs
│   ├── welcome.py          # Messages bienvenue/départ, auto-rôles
│   ├── tickets.py          # Tickets de support avec transcripts
│   ├── giveaways.py        # Concours avec boutons et conditions
│   ├── starboard.py        # Mise en avant des messages populaires
│   ├── birthdays.py        # Anniversaires avec annonces et rôle
│   ├── invites.py          # Tracking d'invitations avec récompenses
│   ├── releases.py         # Annonces sorties jeux/anime/séries/films
│   ├── gamedeals.py        # Jeux gratuits Epic Games / Steam
│   └── automessages.py     # Messages récurrents et rappels de bump
│
├── utils/
│   ├── database.py         # Gestion SQLite (aiosqlite)
│   └── helpers.py          # Fonctions utilitaires (embeds, parsing)
│
├── dashboard/              # Interface web de configuration
│   ├── app.py              # Serveur Flask + API
│   ├── requirements.txt    # Dépendances du dashboard
│   ├── templates/          # Pages HTML (Jinja2)
│   └── static/             # CSS
│
└── data/
    └── bot.db              # Base SQLite (créée automatiquement)
```

---

## Prérequis

- **Python 3.10+** ([télécharger](https://www.python.org/downloads/))
- **Un bot Discord** créé sur le [Developer Portal](https://discord.com/developers/applications)
- **Git** (optionnel, pour cloner le repo)

---

## Installation

### 1. Cloner ou télécharger le projet

```bash
git clone https://github.com/ton-user/draftbot-clone.git
cd draftbot-clone
```

### 2. Installer les dépendances

```bash
pip install -r requirements.txt
```

### 3. Configurer le bot Discord

#### a) Créer l'application

1. Aller sur **https://discord.com/developers/applications**
2. Cliquer sur **New Application** → donner un nom
3. Dans l'onglet **Bot** :
   - Cliquer sur **Reset Token** → copier le token
   - Activer les 3 **Privileged Gateway Intents** :
     - Presence Intent
     - Server Members Intent
     - Message Content Intent

#### b) Inviter le bot sur ton serveur

1. Aller dans **OAuth2** → **URL Generator**
2. Cocher les scopes : `bot` et `applications.commands`
3. Cocher les permissions :
   - Manage Roles, Manage Channels, View Channels
   - Kick Members, Ban Members
   - Send Messages, Manage Messages, Embed Links, Attach Files
   - Read Message History, Add Reactions, Use External Emojis
   - Connect, Speak, Move Members

   > Pour tester rapidement, cocher **Administrator** à la place.

4. Copier l'URL générée, ouvrir le liens dans un navigateur et choisis un serveur.

### 4. Configurer l'environnement

```bash
cp .env.example .env
```

Ouvrir `.env` et remplir au minimum :

```env
DISCORD_TOKEN=ton_token_ici
BOT_PREFIX=!
OWNER_ID=ton_id_discord
```

### 5. Lancer le bot

```bash
python bot.py
```

Le bot devrait se connecter et afficher :

```
INFO - Logged in as BotName#1234 (ID: 123456789)
INFO - Connected to 1 guilds
INFO - Loaded cog: cogs.levels
INFO - Loaded cog: cogs.economy
...
```

---

## Modules & Commandes

Toutes les commandes utilisent le préfixe configuré (par défaut `!`). Les commandes admin nécessitent la permission **Administrateur**.

### Niveaux (`levels.py`)

| Commande | Description |
|----------|-------------|
| `!rank [@user]` | Affiche le rang et l'XP |
| `!leaderboard` | Classement XP du serveur |
| `!levels config` | Voir la configuration |
| `!levels xp <montant>` | XP par message (admin) |
| `!levels cooldown <sec>` | Cooldown entre gains (admin) |
| `!levels channel [#salon]` | Salon d'annonce level-up (admin) |
| `!levels reward <niveau> @role` | Ajouter une récompense (admin) |
| `!levels ignore #salon` | Ignorer un salon (admin) |
| `!levels reset [@user]` | Réinitialiser l'XP (admin) |

### Économie (`economy.py`)

| Commande | Description |
|----------|-------------|
| `!balance [@user]` | Voir le solde |
| `!daily` | Récompense quotidienne |
| `!work` | Travailler pour gagner des coins |
| `!deposit <montant>` | Déposer en banque |
| `!withdraw <montant>` | Retirer de la banque |
| `!pay @user <montant>` | Transférer de l'argent |
| `!shop` | Voir la boutique |
| `!buy <article>` | Acheter un article |
| `!coinflip <montant>` | Pile ou face |
| `!slots <montant>` | Machine à sous |
| `!rob @user` | Voler quelqu'un |
| `!economy config` | Configuration (admin) |

### Modération (`moderation.py`)

| Commande | Description |
|----------|-------------|
| `!ban @user [raison]` | Bannir |
| `!tempban @user <durée> [raison]` | Ban temporaire |
| `!kick @user [raison]` | Expulser |
| `!mute @user [durée] [raison]` | Rendre muet |
| `!unmute @user` | Retirer le mute |
| `!warn @user [raison]` | Avertir |
| `!warnings @user` | Voir les avertissements |
| `!clear <nombre>` | Supprimer des messages |
| `!cases @user` | Historique de modération |
| `!mod config` | Configuration automod (admin) |

### Bienvenue (`welcome.py`)

| Commande | Description |
|----------|-------------|
| `!welcome channel #salon` | Salon de bienvenue (admin) |
| `!welcome message <texte>` | Message personnalisé (admin) |
| `!welcome goodbye #salon` | Salon de départ (admin) |
| `!welcome autorole @role` | Rôle auto aux nouveaux (admin) |
| `!welcome test` | Tester le message (admin) |

Variables : `{user}`, `{server}`, `{count}`, `{name}`

### Tickets (`tickets.py`)

| Commande | Description |
|----------|-------------|
| `!ticket` | Ouvrir un ticket |
| `!ticket close` | Fermer un ticket |
| `!ticket setup` | Configurer le système (admin) |
| `!ticket panel [#salon]` | Envoyer le panel de création (admin) |

### Giveaways (`giveaways.py`)

| Commande | Description |
|----------|-------------|
| `!gstart <durée> <nb_gagnants> <prix>` | Créer un giveaway (admin) |
| `!gend <id>` | Terminer manuellement (admin) |
| `!greroll <id>` | Relancer le tirage (admin) |
| `!gcancel <id>` | Annuler (admin) |
| `!glist` | Giveaways actifs |
| `!grequire <id> role/level <valeur>` | Ajouter une condition (admin) |

### Starboard (`starboard.py`)

| Commande | Description |
|----------|-------------|
| `!starboard enable/disable` | Activer/désactiver (admin) |
| `!starboard channel #salon` | Salon starboard (admin) |
| `!starboard threshold <n>` | Réactions minimum (admin) |
| `!starboard emoji <emoji>` | Emoji à utiliser (admin) |
| `!starboard random` | Message aléatoire du starboard |
| `!starboard stats` | Statistiques |

### Anniversaires (`birthdays.py`)

| Commande | Description |
|----------|-------------|
| `!birthday set <JJ/MM>` | Enregistrer son anniversaire |
| `!birthday remove` | Supprimer |
| `!birthday list` | Prochains anniversaires |
| `!birthday today` | Anniversaires du jour |
| `!birthday config` | Configuration (admin) |

### Invitations (`invites.py`)

| Commande | Description |
|----------|-------------|
| `!invites [@user]` | Voir ses invitations |
| `!invites leaderboard` | Classement |
| `!invites who @user` | Qui a invité ce membre |
| `!invites codes [@user]` | Codes d'invitation actifs |
| `!invites config` | Configuration (admin) |
| `!invites reward add <nb> @role` | Récompense d'invitations (admin) |

### Sorties médias (`releases.py`)

| Commande | Description |
|----------|-------------|
| `!releases enable/disable` | Activer/désactiver (admin) |
| `!releases games #salon [@role]` | Sorties jeux (admin) |
| `!releases anime #salon [@role]` | Sorties anime (admin) |
| `!releases series #salon [@role]` | Sorties séries (admin) |
| `!releases films #salon [@role]` | Sorties films (admin) |
| `!releases check` | Forcer la vérification (admin) |
| `!releases apikey tmdb/rawg <clé>` | Configurer une clé API (admin) |

### Deals & Jeux gratuits (`gamedeals.py`)

| Commande | Description |
|----------|-------------|
| `!deals enable/disable` | Activer/désactiver (admin) |
| `!deals epic #salon [@role]` | Salon Epic Games (admin) |
| `!deals steam #salon [@role]` | Salon Steam (admin) |
| `!deals steammin <pourcentage>` | Réduction minimum Steam (admin) |
| `!deals free` | Jeux gratuits actuels |
| `!deals check` | Forcer la vérification (admin) |

### Messages automatiques (`automessages.py`)

| Commande | Description |
|----------|-------------|
| `!automsg add #salon <intervalle> <message>` | Créer un message récurrent (admin) |
| `!automsg addembed #salon <intervalle> <json>` | Message avec embed (admin) |
| `!automsg remove <id>` | Supprimer (admin) |
| `!automsg enable/disable <id>` | Activer/désactiver (admin) |
| `!automsg test <id>` | Tester un message (admin) |
| `!automsg interval <id> <durée>` | Changer l'intervalle (admin) |
| `!bump enable/disable` | Rappels de bump (admin) |
| `!bump channel #salon` | Salon des rappels (admin) |
| `!bump role @role` | Rôle à mentionner (admin) |
| `!bump cooldown <durée>` | Temps entre bumps (admin) |
| `!bump message <texte>` | Message de rappel (admin) |
| `!bump thank <texte>` | Remerciement auto (admin) |

---

## Clés API optionnelles

Certains modules nécessitent des clés API externes (gratuites) :

| Module | API | Requis ? | Obtenir |
|--------|-----|----------|---------|
| Sorties jeux | RAWG | Optionnel | [rawg.io/apidocs](https://rawg.io/apidocs) |
| Sorties anime | AniList | Non (gratuit, pas de clé) | — |
| Sorties séries/films | TMDB | **Oui** | [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) |
| Jeux gratuits Epic | Epic Games | Non (gratuit, pas de clé) | — |
| Deals Steam | Steam | Non (gratuit, pas de clé) | — |

Ajouter les clés dans `.env` :

```env
TMDB_API_KEY=ta_cle_tmdb
RAWG_API_KEY=ta_cle_rawg
```

---

## Dashboard Web

Le projet inclut un dashboard web pour configurer le bot visuellement. Voir le [README du dashboard](dashboard/README.md) pour les instructions d'installation.

```bash
cd dashboard
pip install -r requirements.txt
python app.py
# → http://localhost:5000
```

---

## Base de données

Le bot utilise **SQLite** via `aiosqlite`. La base de données est créée automatiquement au premier lancement dans `data/bot.db`.

Elle contient environ 35 tables couvrant tous les modules. Toutes les données sont isolées par serveur (guild) grâce à des clés composites `(guild_id, user_id)`.

Pour inspecter la base manuellement :

```bash
sqlite3 data/bot.db
.tables
.schema user_levels
SELECT * FROM guild_settings;
```

---

## Dépannage

| Problème | Solution |
|----------|----------|
| `ModuleNotFoundError` | Lance `pip install -r requirements.txt` |
| Le bot ne répond pas aux commandes | Vérifie que **Message Content Intent** est activé sur le Developer Portal |
| `on_member_join` ne se déclenche pas | Vérifie que **Server Members Intent** est activé |
| `DISCORD_TOKEN not found` | Vérifie que le fichier `.env` existe et contient le token |
| Le bot ne voit pas les salons | Vérifie les permissions du bot sur le serveur |
| Les sorties séries/films ne marchent pas | Configure `TMDB_API_KEY` dans `.env` |
| Erreur `aiosqlite` | Vérifie que tu as Python 3.10+ |

---

## Licence

Projet personnel à but éducatif. Utilise les APIs de Discord, RAWG, AniList, TMDB, Epic Games et Steam selon leurs conditions d'utilisation respectives.
