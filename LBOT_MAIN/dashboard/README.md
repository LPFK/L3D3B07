# 🌐 Dashboard Web — DraftBot Clone

Interface web de configuration pour le bot Discord, construite avec **Flask** et l'authentification **Discord OAuth2**. Permet aux administrateurs de serveurs de configurer tous les modules du bot via une interface graphique intuitive, sans utiliser de commandes.

---

## Fonctionnalités

- **Connexion Discord OAuth2** — Seuls les administrateurs du serveur peuvent accéder à la configuration
- **12 onglets de configuration** — Un pour chaque module du bot
- **Modifications en temps réel** — Les changements sont sauvegardés directement dans la base SQLite partagée avec le bot
- **Gestion CRUD** — Créer/supprimer des messages automatiques, récompenses de niveau, articles de boutique
- **Interface responsive** — Dark theme inspiré de Discord, fonctionne sur mobile

### Modules configurables

| Onglet | Ce qu'on peut configurer |
|--------|--------------------------|
| Vue d'ensemble | Préfixe du bot, statistiques générales |
| Modules | Activer/désactiver chaque module individuellement |
| Niveaux | XP par message, cooldown, XP vocal, récompenses de niveau |
| Économie | Monnaie, daily, work, articles de boutique |
| Modération | Salon de logs, seuil de warns, automod (anti-spam/invites/liens) |
| Bienvenue | Messages de bienvenue et de départ, salons |
| Starboard | Salon, emoji, seuil de réactions |
| Anniversaires | Salon d'annonces, rôle d'anniversaire, heure |
| Invitations | Salons join/leave, âge minimum des comptes |
| Messages auto | Créer, activer/désactiver, supprimer des messages récurrents |
| Bump | Rappels de bump : salon, rôle, cooldown, messages |
| Sorties médias | Salons et rôles pour jeux, anime, séries, films |
| Deals | Salons Epic/Steam, rôles, réduction minimum |

---

## Prérequis

- **Python 3.10+**
- Le **bot principal** doit être installé et configuré (voir le [README principal](../README.md))
- Un navigateur web

---

## 🚀 Installation

### 1. Installer les dépendances du dashboard

Depuis le dossier `dashboard/` :

```bash
cd dashboard
pip install -r requirements.txt
```

Dépendances : `flask`, `requests`, `python-dotenv`

### 2. Configurer Discord OAuth2

#### a) Obtenir le Client ID et Client Secret

1. Aller sur **https://discord.com/developers/applications**
2. Sélectionner l'application (celle du bot)
3. Dans l'onglet **OAuth2** :
   - **Client ID** → copier (visible en haut)
   - **Client Secret** → cliquer sur **Reset Secret** → copier

#### b) Ajouter le Redirect URI

Toujours dans **OAuth2** → **Redirects** :

1. Cliquer sur **Add Redirect**
2. Entrer : `http://localhost:5000/callback`
3. Cliquer sur **Save Changes**

> ⚠️ L'URL doit correspondre **exactement** à celle dans `.env`. Si tu déploies sur un serveur, utilise ton domaine (ex: `https://dashboard.monbot.fr/callback`).

#### c) Remplir le `.env`

Ouvrir le fichier `.env` **à la racine du projet** (pas dans `dashboard/`) et ajoute :

```env
# ==================== DASHBOARD ====================
DISCORD_CLIENT_ID=123456789012345678
DISCORD_CLIENT_SECRET=abcdefghijklmnop1234567890
DISCORD_REDIRECT_URI=http://localhost:5000/callback
DASHBOARD_SECRET=
```

| Variable | Description | Obligatoire |
|----------|-------------|-------------|
| `DISCORD_CLIENT_ID` | L'Application ID de ton bot | ✅ Oui |
| `DISCORD_CLIENT_SECRET` | Le secret OAuth2 | ✅ Oui |
| `DISCORD_REDIRECT_URI` | L'URL de callback (doit matcher Discord) | ✅ Oui |
| `DASHBOARD_SECRET` | Clé secrète Flask pour les sessions (auto-générée si vide) | Non |
| `DISCORD_TOKEN` | Le token du bot (déjà configuré) | ✅ Oui |

> Le dashboard a besoin du **`DISCORD_TOKEN`** du bot pour récupérer la liste des salons et rôles de chaque serveur via l'API Discord.

### 3. Lancer le dashboard

```bash
cd dashboard
python app.py
```

Tu devrais voir :

```
Dashboard starting on http://localhost:5000
Database: /path/to/data/bot.db
OAuth2 URL: https://discord.com/api/oauth2/authorize?client_id=...
```

### 4. Se connecter

1. Ouvrir **http://localhost:5000** dans ton navigateur
2. Cliquer sur **Se connecter avec Discord**
3. Autoriser l'application
4. redirection vers la liste de tes serveurs
5. Cliquer **Configurer** sur un serveur où le bot est présent

---

## Architecture

```
dashboard/
├── app.py                      # Application Flask principale
│   ├── Discord OAuth2          # Login, callback, session
│   ├── Auth decorators         # @login_required, @guild_admin_required
│   ├── Page routes             # /, /servers, /dashboard/<guild_id>
│   └── API routes              # /api/<guild_id>/settings, /config, /automessages...
│
├── templates/
│   ├── login.html              # Page de connexion
│   ├── servers.html            # Sélection du serveur
│   └── dashboard.html          # Dashboard principal (toutes les tabs)
│
├── static/
│   └── style.css               # Dark theme Discord-like
│
└── requirements.txt
```

### Comment ça marche

1. **Authentification** : L'utilisateur se connecte via Discord OAuth2. Le dashboard récupère son identité et la liste de ses serveurs.
2. **Filtrage** : Seuls les serveurs où l'utilisateur est **administrateur** ET où le **bot est présent** affichent le bouton "Configurer".
3. **Données** : Le dashboard lit et écrit directement dans la même base SQLite que le bot (`data/bot.db`). Les changements sont donc instantanés.
4. **API Discord** : Le dashboard utilise le token du bot pour récupérer les salons et rôles de chaque serveur (nécessaire pour les menus déroulants).

### Sécurité

- Les sessions Flask sont signées avec `DASHBOARD_SECRET`
- Chaque route API vérifie que l'utilisateur est admin du serveur cible
- Les requêtes SQL utilisent des paramètres bindés (pas d'injection SQL)
- Les colonnes modifiables sont whitelistées par table (pas d'écriture arbitraire)

---

## 🔌 Routes API

Le dashboard expose des routes API JSON utilisées par le frontend :

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/api/<guild_id>/settings` | Met à jour les settings (préfixe, toggles) |
| `POST` | `/api/<guild_id>/config/<module>` | Met à jour la config d'un module |
| `GET` | `/api/<guild_id>/automessages` | Liste les messages automatiques |
| `POST` | `/api/<guild_id>/automessages` | Crée un message automatique |
| `DELETE` | `/api/<guild_id>/automessages/<id>` | Supprime un message automatique |
| `POST` | `/api/<guild_id>/automessages/<id>/toggle` | Active/désactive un message |
| `POST` | `/api/<guild_id>/levelrewards` | Ajoute une récompense de niveau |
| `DELETE` | `/api/<guild_id>/levelrewards/<id>` | Supprime une récompense |
| `POST` | `/api/<guild_id>/shopitems` | Ajoute un article à la boutique |
| `DELETE` | `/api/<guild_id>/shopitems/<id>` | Supprime un article |

Modules disponibles pour `/config/<module>` : `levels`, `economy`, `moderation`, `welcome`, `tickets`, `starboard`, `birthdays`, `invites`, `releases`, `gamedeals`, `bump`

---

## 🌍 Déploiement en production

Pour héberger le dashboard sur un serveur (VPS, Heroku, Railway...) :

### 1. Utiliser un serveur WSGI

Flask en mode `debug=True` n'est pas adapté à la production. Utilise **Gunicorn** :

```bash
pip install gunicorn
cd dashboard
gunicorn app:app -b 0.0.0.0:5000 -w 4
```

### 2. Mettre à jour le Redirect URI

Dans le Developer Portal → OAuth2 → Redirects, ajoute ton URL de production :

```
https://dashboard.tondomaine.fr/callback
```

Et dans `.env` :

```env
DISCORD_REDIRECT_URI=https://dashboard.tondomaine.fr/callback
```

### 3. HTTPS

Discord OAuth2 **exige HTTPS** en production. Utilise un reverse proxy comme **Nginx** ou **Caddy** avec un certificat Let's Encrypt :

```nginx
server {
    listen 443 ssl;
    server_name dashboard.tondomaine.fr;

    ssl_certificate /etc/letsencrypt/live/dashboard.tondomaine.fr/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dashboard.tondomaine.fr/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### 4. Lancer en tant que service (systemd)

Crée `/etc/systemd/system/bot-dashboard.service` :

```ini
[Unit]
Description=DraftBot Dashboard
After=network.target

[Service]
User=ton_user
WorkingDirectory=/chemin/vers/draftbot-clone/dashboard
ExecStart=/usr/bin/gunicorn app:app -b 127.0.0.1:5000 -w 4
Restart=always
EnvironmentFile=/chemin/vers/draftbot-clone/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bot-dashboard
sudo systemctl start bot-dashboard
```

---

## 🛠️ Dépannage

| Problème | Solution |
|----------|----------|
| `KeyError: 'DISCORD_CLIENT_ID'` | Vérifie que `.env` contient `DISCORD_CLIENT_ID` et `DISCORD_CLIENT_SECRET` |
| Redirect URI mismatch | L'URL dans `.env` doit correspondre **exactement** à celle dans le Developer Portal |
| Aucun serveur affiché | Tu dois être **administrateur** du serveur ET le bot doit y être présent |
| Les salons/rôles ne s'affichent pas | Vérifie que `DISCORD_TOKEN` est correct dans `.env` |
| `sqlite3.OperationalError: no such table` | Lance le bot au moins une fois pour créer les tables (`python bot.py`) |
| Les changements ne sont pas pris en compte | Le bot lit la DB en temps réel, les changements sont instantanés. Vérifie le chemin `DATABASE_PATH` |
| Erreur 403 en production | Discord exige HTTPS pour OAuth2 en production |

---

## 📄 Technologies

- **[Flask](https://flask.palletsprojects.com/)** — Framework web Python
- **[Discord OAuth2](https://discord.com/developers/docs/topics/oauth2)** — Authentification
- **[SQLite](https://www.sqlite.org/)** — Base de données partagée avec le bot
- **CSS custom** — Dark theme sans framework externe
