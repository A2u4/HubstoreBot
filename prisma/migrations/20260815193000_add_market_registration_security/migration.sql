-- Market registration stores only a keyed HMAC of the network address. Raw
-- IP addresses are intentionally excluded from the schema.
ALTER TABLE "guild_configs"
  ADD COLUMN "marketVerificationEnabled" BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN "marketVerificationRoleId" TEXT,
  ADD COLUMN "marketVerificationLogChannelId" TEXT,
  ADD COLUMN "marketVerificationRetentionDays" INTEGER NOT NULL DEFAULT 90;

CREATE TABLE "market_registrations" (
  "id" TEXT NOT NULL,
  "guildId" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "username" TEXT,
  "acceptedPrivacyAt" TIMESTAMP(3) NOT NULL,
  "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "lastSeenAt" TIMESTAMP(3) NOT NULL,
  "revokedAt" TIMESTAMP(3),
  CONSTRAINT "market_registrations_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "market_network_signals" (
  "id" TEXT NOT NULL,
  "guildId" TEXT NOT NULL,
  "userId" TEXT NOT NULL,
  "registrationId" TEXT NOT NULL,
  "ipHash" VARCHAR(64) NOT NULL,
  "ipVersion" INTEGER NOT NULL,
  "firstSeenAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "lastSeenAt" TIMESTAMP(3) NOT NULL,
  "seenCount" INTEGER NOT NULL DEFAULT 1,
  CONSTRAINT "market_network_signals_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "market_network_blocks" (
  "id" TEXT NOT NULL,
  "guildId" TEXT NOT NULL,
  "ipHash" VARCHAR(64) NOT NULL,
  "sourceUserId" TEXT,
  "reason" TEXT,
  "active" BOOLEAN NOT NULL DEFAULT true,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "market_network_blocks_pkey" PRIMARY KEY ("id")
);

CREATE UNIQUE INDEX "market_registrations_guildId_userId_key"
  ON "market_registrations"("guildId", "userId");
CREATE INDEX "market_registrations_guildId_lastSeenAt_idx"
  ON "market_registrations"("guildId", "lastSeenAt");

CREATE UNIQUE INDEX "market_network_signals_guildId_userId_ipHash_key"
  ON "market_network_signals"("guildId", "userId", "ipHash");
CREATE INDEX "market_network_signals_guildId_ipHash_idx"
  ON "market_network_signals"("guildId", "ipHash");
CREATE INDEX "market_network_signals_guildId_lastSeenAt_idx"
  ON "market_network_signals"("guildId", "lastSeenAt");

CREATE UNIQUE INDEX "market_network_blocks_guildId_ipHash_key"
  ON "market_network_blocks"("guildId", "ipHash");
CREATE INDEX "market_network_blocks_guildId_sourceUserId_idx"
  ON "market_network_blocks"("guildId", "sourceUserId");
CREATE INDEX "market_network_blocks_guildId_active_idx"
  ON "market_network_blocks"("guildId", "active");

ALTER TABLE "market_registrations"
  ADD CONSTRAINT "market_registrations_guildId_fkey"
  FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "market_network_signals"
  ADD CONSTRAINT "market_network_signals_guildId_fkey"
  FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "market_network_signals"
  ADD CONSTRAINT "market_network_signals_registrationId_fkey"
  FOREIGN KEY ("registrationId") REFERENCES "market_registrations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE "market_network_blocks"
  ADD CONSTRAINT "market_network_blocks_guildId_fkey"
  FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;
