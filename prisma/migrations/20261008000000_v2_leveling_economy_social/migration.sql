-- v2: leveling, economy, social, captcha verification, temp voice.
-- Idempotent on purpose: some production databases already contain objects
-- (market_verification_sessions, several indexes) that were created with
-- `prisma db push` and never had a migration file.

ALTER TABLE "guild_configs" ADD COLUMN IF NOT EXISTS "botJoinRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
ADD COLUMN IF NOT EXISTS "crimeCooldownSeconds" INTEGER NOT NULL DEFAULT 7200,
ADD COLUMN IF NOT EXISTS "crimeMax" INTEGER NOT NULL DEFAULT 700,
ADD COLUMN IF NOT EXISTS "crimeMin" INTEGER NOT NULL DEFAULT 100,
ADD COLUMN IF NOT EXISTS "crimeSuccessRate" INTEGER NOT NULL DEFAULT 45,
ADD COLUMN IF NOT EXISTS "currencyName" TEXT NOT NULL DEFAULT 'monedas',
ADD COLUMN IF NOT EXISTS "currencySymbol" TEXT NOT NULL DEFAULT '🪙',
ADD COLUMN IF NOT EXISTS "dailyAmount" INTEGER NOT NULL DEFAULT 250,
ADD COLUMN IF NOT EXISTS "economyEnabled" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS "economyStartBalance" INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS "funEnabled" BOOLEAN NOT NULL DEFAULT true,
ADD COLUMN IF NOT EXISTS "levelRewardsStack" BOOLEAN NOT NULL DEFAULT true,
ADD COLUMN IF NOT EXISTS "levelUpChannelId" TEXT,
ADD COLUMN IF NOT EXISTS "levelUpMessage" TEXT NOT NULL DEFAULT '🎉 {user} subió a **nivel {level}**',
ADD COLUMN IF NOT EXISTS "levelingEnabled" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS "levelingIgnoredChannelIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
ADD COLUMN IF NOT EXISTS "levelingIgnoredRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
ADD COLUMN IF NOT EXISTS "robCooldownSeconds" INTEGER NOT NULL DEFAULT 14400,
ADD COLUMN IF NOT EXISTS "robEnabled" BOOLEAN NOT NULL DEFAULT true,
ADD COLUMN IF NOT EXISTS "tempVoiceCategoryId" TEXT,
ADD COLUMN IF NOT EXISTS "tempVoiceEnabled" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS "tempVoiceHubChannelId" TEXT,
ADD COLUMN IF NOT EXISTS "tempVoiceNameTemplate" TEXT NOT NULL DEFAULT '🔊 {user}',
ADD COLUMN IF NOT EXISTS "tempVoiceUserLimit" INTEGER NOT NULL DEFAULT 0,
ADD COLUMN IF NOT EXISTS "verificationChannelId" TEXT,
ADD COLUMN IF NOT EXISTS "verificationEnabled" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN IF NOT EXISTS "verificationMode" TEXT NOT NULL DEFAULT 'button',
ADD COLUMN IF NOT EXISTS "verificationPanelMessage" TEXT NOT NULL DEFAULT 'Pulsa el botón para verificarte y acceder al servidor.',
ADD COLUMN IF NOT EXISTS "verificationPanelMsgId" TEXT,
ADD COLUMN IF NOT EXISTS "verificationPanelTitle" TEXT NOT NULL DEFAULT 'Verificación',
ADD COLUMN IF NOT EXISTS "verificationRemoveRoleId" TEXT,
ADD COLUMN IF NOT EXISTS "verificationRoleId" TEXT,
ADD COLUMN IF NOT EXISTS "weeklyAmount" INTEGER NOT NULL DEFAULT 1500,
ADD COLUMN IF NOT EXISTS "workCooldownSeconds" INTEGER NOT NULL DEFAULT 3600,
ADD COLUMN IF NOT EXISTS "workMax" INTEGER NOT NULL DEFAULT 300,
ADD COLUMN IF NOT EXISTS "workMin" INTEGER NOT NULL DEFAULT 50,
ADD COLUMN IF NOT EXISTS "xpCooldownSeconds" INTEGER NOT NULL DEFAULT 60,
ADD COLUMN IF NOT EXISTS "xpPerMessageMax" INTEGER NOT NULL DEFAULT 25,
ADD COLUMN IF NOT EXISTS "xpPerMessageMin" INTEGER NOT NULL DEFAULT 15;

CREATE TABLE IF NOT EXISTS "market_verification_sessions" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "username" TEXT,
    "tokenHash" VARCHAR(64) NOT NULL,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "usedAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "market_verification_sessions_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "member_levels" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "xp" INTEGER NOT NULL DEFAULT 0,
    "level" INTEGER NOT NULL DEFAULT 0,
    "messages" INTEGER NOT NULL DEFAULT 0,
    "lastXpAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "member_levels_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "level_rewards" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "level" INTEGER NOT NULL,
    "roleId" TEXT NOT NULL,

    CONSTRAINT "level_rewards_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "economy_accounts" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "wallet" INTEGER NOT NULL DEFAULT 0,
    "bank" INTEGER NOT NULL DEFAULT 0,
    "dailyStreak" INTEGER NOT NULL DEFAULT 0,
    "lastDaily" TIMESTAMP(3),
    "lastWeekly" TIMESTAMP(3),
    "lastWork" TIMESTAMP(3),
    "lastCrime" TIMESTAMP(3),
    "lastRob" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "economy_accounts_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "economy_items" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "name" VARCHAR(60) NOT NULL,
    "description" TEXT NOT NULL DEFAULT '',
    "emoji" TEXT,
    "price" INTEGER NOT NULL,
    "roleId" TEXT,
    "stock" INTEGER,
    "active" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "economy_items_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "economy_inventory" (
    "id" TEXT NOT NULL,
    "accountId" TEXT NOT NULL,
    "itemId" TEXT NOT NULL,
    "quantity" INTEGER NOT NULL DEFAULT 1,

    CONSTRAINT "economy_inventory_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "marriages" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "user1Id" TEXT NOT NULL,
    "user2Id" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "marriages_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "roleplay_stats" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "action" VARCHAR(32) NOT NULL,
    "userId" TEXT NOT NULL,
    "targetId" TEXT NOT NULL,
    "count" INTEGER NOT NULL DEFAULT 0,

    CONSTRAINT "roleplay_stats_pkey" PRIMARY KEY ("id")
);

CREATE TABLE IF NOT EXISTS "temp_voice_channels" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "ownerId" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "temp_voice_channels_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX IF NOT EXISTS "market_verification_sessions_tokenHash_key" ON "market_verification_sessions"("tokenHash");

CREATE INDEX IF NOT EXISTS "market_verification_sessions_guildId_userId_idx" ON "market_verification_sessions"("guildId", "userId");

CREATE INDEX IF NOT EXISTS "market_verification_sessions_expiresAt_usedAt_idx" ON "market_verification_sessions"("expiresAt", "usedAt");

CREATE INDEX IF NOT EXISTS "member_levels_guildId_xp_idx" ON "member_levels"("guildId", "xp");

CREATE UNIQUE INDEX IF NOT EXISTS "member_levels_guildId_userId_key" ON "member_levels"("guildId", "userId");

CREATE INDEX IF NOT EXISTS "level_rewards_guildId_level_idx" ON "level_rewards"("guildId", "level");

CREATE UNIQUE INDEX IF NOT EXISTS "level_rewards_guildId_level_roleId_key" ON "level_rewards"("guildId", "level", "roleId");

CREATE INDEX IF NOT EXISTS "economy_accounts_guildId_wallet_idx" ON "economy_accounts"("guildId", "wallet");

CREATE UNIQUE INDEX IF NOT EXISTS "economy_accounts_guildId_userId_key" ON "economy_accounts"("guildId", "userId");

CREATE UNIQUE INDEX IF NOT EXISTS "economy_items_guildId_name_key" ON "economy_items"("guildId", "name");

CREATE UNIQUE INDEX IF NOT EXISTS "economy_inventory_accountId_itemId_key" ON "economy_inventory"("accountId", "itemId");

CREATE UNIQUE INDEX IF NOT EXISTS "marriages_guildId_user1Id_key" ON "marriages"("guildId", "user1Id");

CREATE UNIQUE INDEX IF NOT EXISTS "marriages_guildId_user2Id_key" ON "marriages"("guildId", "user2Id");

CREATE UNIQUE INDEX IF NOT EXISTS "roleplay_stats_guildId_action_userId_targetId_key" ON "roleplay_stats"("guildId", "action", "userId", "targetId");

CREATE UNIQUE INDEX IF NOT EXISTS "temp_voice_channels_channelId_key" ON "temp_voice_channels"("channelId");

CREATE INDEX IF NOT EXISTS "temp_voice_channels_guildId_idx" ON "temp_voice_channels"("guildId");

CREATE INDEX IF NOT EXISTS "giveaways_guildId_ended_endsAt_idx" ON "giveaways"("guildId", "ended", "endsAt");

CREATE INDEX IF NOT EXISTS "reminders_guildId_fired_remindAt_idx" ON "reminders"("guildId", "fired", "remindAt");

CREATE INDEX IF NOT EXISTS "rifas_guildId_ended_cancelled_endsAt_idx" ON "rifas"("guildId", "ended", "cancelled", "endsAt");

CREATE INDEX IF NOT EXISTS "scheduled_messages_guildId_enabled_idx" ON "scheduled_messages"("guildId", "enabled");

CREATE INDEX IF NOT EXISTS "tickets_guildId_status_closedAt_idx" ON "tickets"("guildId", "status", "closedAt");

CREATE INDEX IF NOT EXISTS "tickets_guildId_status_autoCloseDisabled_lastActivityAt_idx" ON "tickets"("guildId", "status", "autoCloseDisabled", "lastActivityAt");

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'market_verification_sessions_guildId_fkey') THEN
    ALTER TABLE "market_verification_sessions" ADD CONSTRAINT "market_verification_sessions_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'member_levels_guildId_fkey') THEN
    ALTER TABLE "member_levels" ADD CONSTRAINT "member_levels_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'level_rewards_guildId_fkey') THEN
    ALTER TABLE "level_rewards" ADD CONSTRAINT "level_rewards_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'economy_accounts_guildId_fkey') THEN
    ALTER TABLE "economy_accounts" ADD CONSTRAINT "economy_accounts_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'economy_items_guildId_fkey') THEN
    ALTER TABLE "economy_items" ADD CONSTRAINT "economy_items_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'economy_inventory_accountId_fkey') THEN
    ALTER TABLE "economy_inventory" ADD CONSTRAINT "economy_inventory_accountId_fkey" FOREIGN KEY ("accountId") REFERENCES "economy_accounts"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'economy_inventory_itemId_fkey') THEN
    ALTER TABLE "economy_inventory" ADD CONSTRAINT "economy_inventory_itemId_fkey" FOREIGN KEY ("itemId") REFERENCES "economy_items"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'marriages_guildId_fkey') THEN
    ALTER TABLE "marriages" ADD CONSTRAINT "marriages_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'roleplay_stats_guildId_fkey') THEN
    ALTER TABLE "roleplay_stats" ADD CONSTRAINT "roleplay_stats_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'temp_voice_channels_guildId_fkey') THEN
    ALTER TABLE "temp_voice_channels" ADD CONSTRAINT "temp_voice_channels_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
  END IF;
END $$;
