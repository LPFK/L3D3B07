# L3D3B07

Bot Discord communautaire en Python. Clone de DraftBot avec 12 modules + dashboard web.

## Quick Start

```bash
# clone le repo
git clone https://github.com/LPFK/L3D3B07.git
cd L3D3B07/LBOT_MAIN

# setup (cree le venv et installe les deps)
./setup.sh   # linux/mac
setup.bat    # windows

# config
cp .env.exemple .env
# edite .env avec ton token discord

# lance
python bot.py
```

Le bot cree la DB automatiquement au premier lancement.

## Structure

```
LBOT_MAIN/
├── bot.py                      # point d'entree
├── cogs/                       # 12 modules
│   ├── levels.py               # xp, niveaux, rewards
│   ├── economy.py              # monnaie, shop, gambling
│   ├── moderation.py           # ban, mute, automod
│   ├── welcome.py              # bienvenue/depart
│   ├── tickets.py              # support tickets
│   ├── giveaways.py            # concours
│   ├── starboard.py            # messages populaires
│   ├── birthdays.py            # anniversaires
│   ├── invites.py              # tracking invitations
│   ├── releases.py             # sorties jeux/anime/films
│   ├── gamedeals.py            # jeux gratuits epic/steam
│   └── automessages.py         # messages recurrents
│
├── utils/
│   ├── database.py             # sqlite async + migrations
│   ├── helpers.py              # embeds, parsing, etc
│   ├── migrations.py           # systeme de migrations sql
│   └── repositories/           # pattern repository (data access)
│       ├── levels.py
│       ├── economy.py
│       └── moderation.py
│
├── migrations/                 # fichiers .sql de migration
│   ├── 001_temp_punishments.sql
│   └── 002_mod_cases_indexes.sql
│
├── dashboard/                  # interface web flask
│   ├── app.py
│   ├── templates/
│   └── static/
│
└── data/
    └── bot.db                  # sqlite (cree auto)
```

## Config (.env)

```env
# obligatoire
DISCORD_TOKEN=ton_token_discord
BOT_PREFIX=!
OWNER_ID=ton_id_discord

# optionnel - apis externes
TMDB_API_KEY=xxx              # pour sorties films/series
RAWG_API_KEY=xxx              # pour sorties jeux

# dashboard
DISCORD_CLIENT_ID=xxx
DISCORD_CLIENT_SECRET=xxx
DISCORD_REDIRECT_URI=http://localhost:5000/callback
DASHBOARD_SECRET=un_secret_random
```

## Modules

### Niveaux
XP sur les messages, vocal, leaderboard, rewards par niveau.

```
!rank [@user]     - voir son niveau
!leaderboard      - classement
!leveladmin       - config (admin)
```

### Economie
Monnaie virtuelle, daily, work, shop, coinflip, slots.

```
!balance          - voir son solde
!daily            - reward quotidienne
!work             - travailler
!shop             - boutique
!buy <id>         - acheter
!coinflip <mise>  - pile ou face
```

### Moderation
Ban, kick, mute (timeout discord), warns, automod.

```
!ban @user [duree] [raison]
!kick @user [raison]
!mute @user <duree> [raison]
!warn @user [raison]
!warnings @user
!clear <nb>
!modlog channel #salon
```

### Welcome
Messages de bienvenue/depart, auto-roles.

### Tickets
Systeme de tickets support avec boutons.

### Giveaways
Concours avec duree, nb gagnants, conditions.

### Starboard
Met en avant les messages avec X reactions.

### Birthdays
Annonces d'anniversaires automatiques.

### Invites
Tracking des invitations avec rewards.

### Releases
Annonces sorties jeux/anime/series/films (APIs externes).

### Gamedeals
Jeux gratuits Epic Games + deals Steam.

### Automessages
Messages recurrents programmables.

## Dashboard

Interface web pour configurer le bot.

```bash
cd dashboard
pip install -r requirements.txt
python app.py
# -> http://localhost:5000
```

Connecte-toi avec Discord OAuth2 pour acceder aux serveurs.

**Securite:**
- Protection CSRF sur tous les formulaires
- Rate limiting sur les APIs (10 req/min pour les writes)
- Cookies HttpOnly + SameSite

## Architecture

### Pattern Repository

Les cogs n'accedent plus directement a la DB. Ils passent par des repositories qui:
- Cachent les configs (TTL 60s)
- Pre-parsent les champs JSON
- Centralisent le SQL

```python
# avant (dans le cog)
row = await db.fetchone("SELECT * FROM levels_config WHERE guild_id = ?", (guild_id,))
ignored = json.loads(row.get("ignored_channels", "[]"))

# apres
config = await levels_repo.get_config(guild_id)
# config["ignored_channels"] est deja une list
```

### Migrations

Les evolutions de schema sont gerees par des fichiers SQL dans `migrations/`:

```
migrations/
├── 001_temp_punishments.sql
├── 002_mod_cases_indexes.sql
└── 003_ta_prochaine_migration.sql
```

Au demarrage, le bot execute automatiquement les migrations pas encore appliquees.

Pour ajouter une migration:
1. Cree `migrations/XXX_description.sql`
2. Utilise `IF NOT EXISTS` pour etre idempotent
3. Le numero doit etre sequentiel

## Setup Discord

1. Cree une app sur https://discord.com/developers/applications
2. Dans **Bot**, active les 3 intents:
   - Presence Intent
   - Server Members Intent
   - Message Content Intent
3. Dans **OAuth2 > URL Generator**:
   - Scopes: `bot` + `applications.commands`
   - Permissions: Administrator (ou les perms specifiques)
4. Copie l'URL et invite le bot

## Depannage

| Probleme | Solution |
|----------|----------|
| Le bot repond pas | Active Message Content Intent dans le dev portal |
| `on_member_join` marche pas | Active Server Members Intent |
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Dashboard OAuth loop | Verifie que REDIRECT_URI est exactement le meme partout |
| Sorties films/series vides | Configure TMDB_API_KEY |

## Stack

- Python 3.10+
- discord.py 2.x
- aiosqlite (SQLite async)
- Flask + flask-wtf + flask-limiter (dashboard)

## Licence

Projet perso/educatif. Utilise les APIs Discord, RAWG, AniList, TMDB, Epic Games, Steam.
