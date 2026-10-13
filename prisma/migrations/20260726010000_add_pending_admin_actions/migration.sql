CREATE TABLE "pending_admin_actions" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "moderatorId" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "payload" JSONB NOT NULL,
    "result" JSONB,
    "progress" INTEGER NOT NULL DEFAULT 0,
    "total" INTEGER NOT NULL DEFAULT 0,
    "error" TEXT,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "consumedAt" TIMESTAMP(3),

    CONSTRAINT "pending_admin_actions_pkey" PRIMARY KEY ("id")
);

CREATE INDEX "pending_admin_actions_guildId_type_status_idx"
    ON "pending_admin_actions"("guildId", "type", "status");

CREATE INDEX "pending_admin_actions_moderatorId_type_status_idx"
    ON "pending_admin_actions"("moderatorId", "type", "status");

CREATE INDEX "pending_admin_actions_expiresAt_idx"
    ON "pending_admin_actions"("expiresAt");
