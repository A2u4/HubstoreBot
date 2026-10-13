ALTER TABLE "guild_configs"
  ADD COLUMN "marketVpnCheckEnabled" BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN "marketVpnPolicy" TEXT NOT NULL DEFAULT 'review';

ALTER TABLE "market_network_signals"
  ADD COLUMN "vpnDetected" BOOLEAN,
  ADD COLUMN "proxyDetected" BOOLEAN,
  ADD COLUMN "torDetected" BOOLEAN,
  ADD COLUMN "relayDetected" BOOLEAN,
  ADD COLUMN "hostingDetected" BOOLEAN,
  ADD COLUMN "privacyService" VARCHAR(100),
  ADD COLUMN "privacyProvider" VARCHAR(30),
  ADD COLUMN "privacyCheckedAt" TIMESTAMP(3);
