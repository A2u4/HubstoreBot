# Markets bots v2

Three Discord bots (**Vapiano**, **Hub Store**, **Trade Zone**) and their admin dashboard.

| Part | Stack | Folder |
|---|---|---|
| Bots | Python 3.12 · discord.py 2.7 · SQLAlchemy 2 (async) | `bot/` |
| Dashboard | Next.js 15 · React 19 · TypeScript · Tailwind 4 | `dashboard/` |
| Database | PostgreSQL · schema and migrations managed by Prisma | `prisma/` |

v2 reuses the **same databases, slash command names, button IDs, peer protocol and URLs** as v1, so existing
panels, tickets, shop messages and registration links keep working after the switch.

## Layout

```
bot/src/markets_bot/
  __main__.py          python -m markets_bot --bot <identity>
  bot.py               client: loads every cog, routes interactions/messages
  core/                config, db, cache, permission tree, component router,
                       message pipeline, command sync, audit, peers
  cogs/                one file per feature (27 modules)
  services/            logic shared by cogs (tickets, shop, economy, leveling, cards...)
  web/internal_server  127.0.0.1-only HTTP API used by the dashboard and peer bots
dashboard/src/
  app/                 pages (/bots/<bot>/<guild>/...) and API routes (/api/...)
  components/          monochrome UI kit + declarative config editor
  lib/server/          auth, Prisma per bot, bot API client, media processing
prisma/                schema.prisma + migrations (shared by bots and dashboard)
```

## Setup

```bash
cp .env.example .env              # fill in tokens and secrets (never commit .env)

# Bots
cd bot
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Dashboard (also installs the Prisma CLI)
cd ../dashboard
npm ci
npx prisma migrate deploy         # run once per bot database (set DATABASE_URL accordingly)
npm run build
```

Run everything with PM2:

```bash
pm2 start ecosystem.config.js
```

Or individually: `cd bot && .venv/bin/python -m markets_bot --bot vapiano` and `cd dashboard && npm run dev`.

### Database migrations

`prisma migrate deploy` applies the v1 migrations plus `20261008000000_v2_leveling_economy_social`. That
migration is idempotent (`IF NOT EXISTS`), because production also has objects created with `db push`.
It only **adds** tables and columns, so v1 keeps working against a migrated database.

### Reverse proxy

The dashboard now serves everything v1 split across several processes, including
`/bots/<bot>/auth/registro` (Market registration) and `/bots/<bot>/api/uploads/*` (shop media). Point the
whole domain at port 3100 and forward the client IP, which Market verification needs:

```nginx
location / {
    proxy_pass http://127.0.0.1:3100;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 25m;
}
```

Set `UPLOADS_DIR` to v1's `uploads/` folder so existing shop images keep resolving.

### Switching from v1

1. Back up the databases.
2. Run `prisma migrate deploy` against each database (safe while v1 is running).
3. Stop the v1 bot processes, then `pm2 start ecosystem.config.js`. The PM2 names use a `v2-` prefix, so
   they never collide with v1. Each bot redeploys its guild slash commands on startup.
4. Update nginx as shown above and add `https://<DASHBOARD_URL>/api/auth/callback` as an OAuth redirect in
   each Discord application.

## Updating the server (GitHub workflow)

The repository is private and holds only code. Secrets live in `.env` on the server, which git ignores.

```bash
# On your computer (or wherever you edit): publish changes
git add -A
git commit -m "Describe the change"
git push

# On the server: pull, install, migrate, build and restart everything
./scripts/deploy.sh
```

`deploy.sh` runs `git pull`, installs Python and Node dependencies, applies Prisma migrations to every bot
database listed in `.env`, builds the dashboard and reloads the PM2 processes. Use `./scripts/deploy.sh
--no-pull` to deploy local edits without pulling.

Setting up a fresh server: `git clone git@github.com:<you>/<repo>.git`, `cp .env.example .env`, fill it in,
then run `./scripts/deploy.sh`.

## Tests and linting

```bash
cd bot
.venv/bin/ruff check src tests
TEST_DATABASE_URL=postgresql+asyncpg://user@localhost/markets_test .venv/bin/pytest
```

The command-tree test loads every module without connecting to Discord and validates every slash command
(names, descriptions, option order, the 100-commands-per-guild limit, module tags). DB tests (economy
concurrency, leveling, schema drift) run when `TEST_DATABASE_URL` points to a migrated database.

```bash
cd dashboard
npx tsc --noEmit && npm run build
```

## Features

Everything from v1 is kept: invites, moderation (`/mod`, `/ban`, chain bans, compromised accounts), AutoMod,
logs, welcome/farewell cards, tickets (forms, claiming, transcripts, ratings, auto-close, escalation),
shop with country prices and GIF media, `/cotizacion`, reputation (cross-bot sync), giveaways, rifas,
suggestions, starboard, AFK, reminders, sticky messages, reaction roles, auto-responses, scheduled
messages, polls, backups, stats channels, `/dar-rango`, `/dinero-rangos`, Market verification and
cross-bot ban sync.

New in v2 (inspired by Nekotina, Koya and Ticket King):

- **Levels**: MEE6-style XP curve, `/nivel` rank card, `/top-niveles`, role rewards (stacking or not).
- **Economy**: wallet and bank, `/diario` with streaks, `/semanal`, `/trabajar`, `/crimen`, `/robar`,
  `/pagar`, `/apostar`, `/tragamonedas`, an item shop with role items. Every transfer locks the rows,
  so money can't be duplicated.
- **Fun**: `/accion` (hug, kiss, pat… anime GIFs with counters and a "return it" button), `/reaccion`,
  `/matrimonio`, 8ball, ship, dice, `/avatar`.
- **Verification**: a panel with a one-click button or an image captcha.
- **Temporary voice**: join a hub channel to get your own channel, managed with `/voz`.
- **Tickets**: `/ticket estadisticas` and `/ticket lista` (staff overview, first-response time).
- **Dashboard**: a black, white and grey redesign; a page for every module; live previews (embeds, and
  welcome cards rendered by the bot itself); member names in every table.

## Security

- Tokens and secrets live only in `.env` (ignored by git). Nothing secret sits in code or PM2 files.
- The bots' internal API listens on `127.0.0.1` and requires `API_SECRET`, compared in constant time.
- The dashboard session is an encrypted cookie (JWE, HttpOnly, SameSite=Lax). Every guild endpoint
  re-checks Manage Server through Discord. State-changing requests must come from the dashboard origin.
- Any channel the dashboard saves for the bot to post in must belong to that guild. v1 accepted any
  channel ID.
- Remote media downloads block private, loopback and metadata IPs, and re-check every redirect.
- v1's local "magic login" is replaced by `npm run emergency-link` (disabled unless
  `DASHBOARD_EMERGENCY_LOGIN=true`). It signs a 10-minute link, so it needs the server's secrets.
