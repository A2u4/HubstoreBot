// PM2 process file for Markets v2: three Python bots + the Next.js dashboard.
// Secrets are read from the repo-root .env by each process; nothing sensitive lives here.
// Start:   pm2 start ecosystem.config.js
// Names use a "v2-" prefix so they never clash with the v1 processes during the migration.

const BOTS = ["vapiano", "hubstore", "tradezone"];

module.exports = {
  apps: [
    ...BOTS.map((id) => ({
      name: `v2-bot-${id}`,
      cwd: `${__dirname}/bot`,
      script: ".venv/bin/python",
      args: `-m markets_bot --bot ${id}`,
      interpreter: "none",
      autorestart: true,
      restart_delay: 5000,
      max_memory_restart: "500M",
      env: { PYTHONUNBUFFERED: "1" },
    })),
    {
      name: "v2-dashboard",
      cwd: `${__dirname}/dashboard`,
      script: "node_modules/next/dist/bin/next",
      args: "start -p 3100",
      autorestart: true,
      max_memory_restart: "700M",
      env: { NODE_ENV: "production" },
    },
  ],
};
