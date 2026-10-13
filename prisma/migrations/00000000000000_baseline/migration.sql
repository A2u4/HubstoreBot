-- CreateTable
CREATE TABLE "guild_configs" (
    "id" TEXT NOT NULL,
    "prefix" TEXT NOT NULL DEFAULT '!',
    "language" TEXT NOT NULL DEFAULT 'en',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,
    "invitesEnabled" BOOLEAN NOT NULL DEFAULT false,
    "moderationEnabled" BOOLEAN NOT NULL DEFAULT false,
    "automodEnabled" BOOLEAN NOT NULL DEFAULT false,
    "ticketsEnabled" BOOLEAN NOT NULL DEFAULT false,
    "automationEnabled" BOOLEAN NOT NULL DEFAULT false,
    "welcomeEnabled" BOOLEAN NOT NULL DEFAULT false,
    "farewellEnabled" BOOLEAN NOT NULL DEFAULT false,
    "reputationEnabled" BOOLEAN NOT NULL DEFAULT false,
    "giveawayEnabled" BOOLEAN NOT NULL DEFAULT false,
    "rifaEnabled" BOOLEAN NOT NULL DEFAULT true,
    "rifaCategoryId" TEXT DEFAULT '1489245171953434805',
    "rifaPanelChannelId" TEXT,
    "rifaPanelMessageId" TEXT,
    "rifaLogChannelId" TEXT,
    "rifaStaffRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "suggestionsEnabled" BOOLEAN NOT NULL DEFAULT false,
    "starboardEnabled" BOOLEAN NOT NULL DEFAULT false,
    "afkEnabled" BOOLEAN NOT NULL DEFAULT true,
    "backupEnabled" BOOLEAN NOT NULL DEFAULT true,
    "stickyEnabled" BOOLEAN NOT NULL DEFAULT true,
    "loggingEnabled" BOOLEAN NOT NULL DEFAULT false,
    "moduleAllowedRoles" JSONB NOT NULL DEFAULT '{}',
    "welcomeChannelId" TEXT,
    "welcomeMessage" TEXT DEFAULT 'Bienvenido {user} !',
    "welcomeImageEnabled" BOOLEAN NOT NULL DEFAULT false,
    "welcomeEmbedTitle" TEXT DEFAULT '¡Bienvenido!',
    "welcomeEmbedColor" TEXT,
    "welcomeEmbedFooter" TEXT,
    "welcomeEmbedDescription" TEXT,
    "welcomeEmbedImage" TEXT,
    "welcomeEmbedThumbnail" TEXT,
    "welcomeImageBgColor" TEXT DEFAULT '#0d1117',
    "welcomeImageAccent1" TEXT DEFAULT '#dc3250',
    "welcomeImageAccent2" TEXT DEFAULT '#3282dc',
    "welcomeImagePillText" TEXT DEFAULT 'BIENVENID@',
    "welcomeImageBrand" TEXT DEFAULT '',
    "welcomeImageSubtitle" TEXT DEFAULT 'a {server}',
    "welcomeImageMemberLabel" TEXT DEFAULT 'Miembro #{memberCount}',
    "welcomeImageFont" TEXT DEFAULT 'Arial',
    "welcomeImageFontWeight" INTEGER DEFAULT 700,
    "welcomeCardLayout" JSONB,
    "farewellChannelId" TEXT,
    "farewellMessage" TEXT DEFAULT 'Goodbye {user}, we''ll miss you!',
    "farewellImageEnabled" BOOLEAN NOT NULL DEFAULT false,
    "farewellCardLayout" JSONB,
    "farewellEmbedTitle" TEXT DEFAULT '¡Adiós!',
    "farewellEmbedColor" TEXT,
    "farewellEmbedFooter" TEXT,
    "farewellEmbedDescription" TEXT,
    "farewellEmbedImage" TEXT,
    "farewellEmbedThumbnail" TEXT,
    "modLogChannelId" TEXT,
    "warnLogChannelId" TEXT,
    "messageLogChannelId" TEXT,
    "joinLeaveLogChannelId" TEXT,
    "auditLogChannelId" TEXT,
    "voiceLogChannelId" TEXT,
    "verificationLogChannelId" TEXT,
    "darRangoImagesChannelId" TEXT,
    "darRangoRoles" JSONB,
    "banLogChannelId" TEXT,
    "banSyncEnabled" BOOLEAN NOT NULL DEFAULT true,
    "repSyncGuildIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "statsChannels" JSONB,
    "muteRoleId" TEXT,
    "ticketCategoryId" TEXT,
    "ticketLogChannelId" TEXT,
    "ticketStaffRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "ticketCounter" INTEGER NOT NULL DEFAULT 0,
    "ticketTranscriptChannelId" TEXT,
    "ticketCloseConfirmation" BOOLEAN NOT NULL DEFAULT true,
    "ticketDMTranscript" BOOLEAN NOT NULL DEFAULT true,
    "joinRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "antiSpamEnabled" BOOLEAN NOT NULL DEFAULT false,
    "antiSpamThreshold" INTEGER NOT NULL DEFAULT 5,
    "antiSpamInterval" INTEGER NOT NULL DEFAULT 5,
    "antiFloodEnabled" BOOLEAN NOT NULL DEFAULT false,
    "antiCapsEnabled" BOOLEAN NOT NULL DEFAULT false,
    "antiCapsThreshold" INTEGER NOT NULL DEFAULT 70,
    "antiLinksEnabled" BOOLEAN NOT NULL DEFAULT false,
    "antiLinksWhitelist" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "blacklistEnabled" BOOLEAN NOT NULL DEFAULT false,
    "blacklistedWords" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "antiCapsMinLength" INTEGER NOT NULL DEFAULT 10,
    "automodExemptRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "automodExemptChannelIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "repCooldown" INTEGER NOT NULL DEFAULT 86400,
    "repChannelId" TEXT,
    "starboardChannelId" TEXT,
    "starboardEmoji" TEXT NOT NULL DEFAULT '⭐',
    "starboardThreshold" INTEGER NOT NULL DEFAULT 3,
    "suggestionsChannelId" TEXT,
    "suggestionsLogChannelId" TEXT,
    "shopChannelId" TEXT,
    "shopMessageId" TEXT,
    "shopTitle" TEXT DEFAULT '🛍️ Tienda Oficial',
    "shopDescription" TEXT DEFAULT 'Bienvenido a nuestra tienda. ¡Elige un producto y haz clic en Comprar para abrir un ticket!',
    "shopColor" TEXT DEFAULT '#5865F2',
    "shopImage" TEXT,
    "shopImages" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "shopImageInterval" INTEGER NOT NULL DEFAULT 10,
    "shopThumbnail" TEXT,
    "shopButtonStyle" TEXT DEFAULT 'multiple',
    "shopCustomButtons" JSONB NOT NULL DEFAULT '[]',
    "shopBuyButtonLabel" TEXT DEFAULT 'Comprar',
    "shopBuyButtonEmoji" TEXT DEFAULT '🛒',
    "shopBuyButtonStyle" TEXT DEFAULT 'Primary',
    "shopPanelId" TEXT,

    CONSTRAINT "guild_configs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "invites" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "inviterId" TEXT NOT NULL,
    "invitedId" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "fake" BOOLEAN NOT NULL DEFAULT false,
    "left" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "invites_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "backups" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "creatorId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "data" JSONB NOT NULL,
    "size" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "backups_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "warnings" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "moderatorId" TEXT NOT NULL,
    "reason" TEXT NOT NULL DEFAULT 'No reason provided',
    "syncedFromGuildId" TEXT,
    "syncedFromBot" TEXT,
    "syncedFromGuildName" TEXT,
    "sourceWarningId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "warnings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "mod_actions" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "moderatorId" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "reason" TEXT NOT NULL DEFAULT 'No reason provided',
    "duration" INTEGER,
    "expiresAt" TIMESTAMP(3),
    "active" BOOLEAN NOT NULL DEFAULT true,
    "syncedFromGuildId" TEXT,
    "syncedFromBot" TEXT,
    "syncedFromGuildName" TEXT,
    "sourceActionId" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "mod_actions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reaction_roles" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT NOT NULL,
    "emoji" TEXT NOT NULL,
    "roleId" TEXT NOT NULL,
    "type" TEXT NOT NULL DEFAULT 'toggle',

    CONSTRAINT "reaction_roles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "auto_responses" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "trigger" TEXT NOT NULL,
    "response" TEXT NOT NULL,
    "matchType" TEXT NOT NULL DEFAULT 'contains',
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "auto_responses_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "scheduled_messages" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "cron" TEXT NOT NULL,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "lastRun" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "scheduled_messages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "custom_text_commands" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "text" TEXT NOT NULL,
    "embedColor" TEXT NOT NULL DEFAULT '#ffffff',
    "title" TEXT,
    "thumbnailUrl" TEXT,
    "showAuthor" BOOLEAN NOT NULL DEFAULT true,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "createdById" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "custom_text_commands_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rank_money_entries" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "rankType" TEXT NOT NULL,
    "amount" INTEGER NOT NULL,
    "adrianShare" INTEGER NOT NULL,
    "kengShare" INTEGER NOT NULL,
    "buyerId" TEXT,
    "recordedById" TEXT NOT NULL,
    "note" TEXT,
    "withdrawnAt" TIMESTAMP(3),
    "withdrawnById" TEXT,
    "withdrawalNote" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rank_money_entries_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "polls" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT,
    "question" TEXT NOT NULL,
    "options" TEXT[],
    "votes" JSONB NOT NULL DEFAULT '{}',
    "creatorId" TEXT NOT NULL,
    "endsAt" TIMESTAMP(3),
    "allowedRoleIds" TEXT[],
    "ended" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "polls_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ticket_panels" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "name" TEXT NOT NULL DEFAULT 'Default',
    "channelId" TEXT NOT NULL,
    "messageId" TEXT,
    "title" TEXT NOT NULL DEFAULT 'Support Tickets',
    "description" TEXT NOT NULL DEFAULT 'Click the button below to create a ticket.',
    "embedColor" TEXT NOT NULL DEFAULT '#5865F2',
    "footerText" TEXT,
    "embedImages" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "embedImageInterval" INTEGER NOT NULL DEFAULT 10,
    "groupEmbedTitle" TEXT,
    "groupEmbedDescription" TEXT,
    "groupEmbedColor" TEXT,
    "groupEmbedImages" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "buttonLabel" TEXT NOT NULL DEFAULT 'Create Ticket',
    "buttonEmoji" TEXT DEFAULT '🎫',
    "buttonColor" TEXT NOT NULL DEFAULT 'Primary',
    "style" TEXT NOT NULL DEFAULT 'button',
    "categoryId" TEXT,
    "closedCategoryId" TEXT,
    "namingPattern" TEXT NOT NULL DEFAULT 'ticket-{number}',
    "staffRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "adminRoleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "ticketLimit" INTEGER NOT NULL DEFAULT 1,
    "mentionStaff" BOOLEAN NOT NULL DEFAULT true,
    "mentionCreator" BOOLEAN NOT NULL DEFAULT true,
    "welcomeTitle" TEXT DEFAULT 'Ticket Opened',
    "welcomeMessage" TEXT DEFAULT 'Welcome! Please describe your issue.
A staff member will assist you shortly.',
    "welcomeColor" TEXT NOT NULL DEFAULT '#5865F2',
    "closeRequestEnabled" BOOLEAN NOT NULL DEFAULT true,
    "closeRequestMessage" TEXT DEFAULT 'Are you sure you want to close this ticket?',
    "claimEnabled" BOOLEAN NOT NULL DEFAULT true,
    "claimLockOthers" BOOLEAN NOT NULL DEFAULT false,
    "transcriptEnabled" BOOLEAN NOT NULL DEFAULT true,
    "transcriptChannelId" TEXT,
    "transcriptDMUser" BOOLEAN NOT NULL DEFAULT true,
    "transcriptDMStaff" BOOLEAN NOT NULL DEFAULT false,
    "logChannelId" TEXT,
    "showCloseButton" BOOLEAN NOT NULL DEFAULT true,
    "showClaimButton" BOOLEAN NOT NULL DEFAULT true,
    "showTranscriptButton" BOOLEAN NOT NULL DEFAULT true,
    "formEnabled" BOOLEAN NOT NULL DEFAULT false,
    "formTitle" TEXT DEFAULT 'Ticket Form',
    "formQuestions" JSONB,
    "escalatePanelId" TEXT,
    "feedbackEnabled" BOOLEAN NOT NULL DEFAULT false,
    "feedbackMessage" TEXT DEFAULT 'How would you rate the support you received?',
    "panelAutoRepost" BOOLEAN NOT NULL DEFAULT false,
    "panelAutoRepostCooldown" INTEGER NOT NULL DEFAULT 5,
    "panelAutoRepostIgnoreBots" BOOLEAN NOT NULL DEFAULT true,
    "autoCloseHours" INTEGER NOT NULL DEFAULT 0,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ticket_panels_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "tickets" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "panelId" TEXT,
    "channelId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "number" INTEGER NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'open',
    "topic" TEXT,
    "claimedBy" TEXT,
    "closedBy" TEXT,
    "closeReason" TEXT,
    "priority" TEXT NOT NULL DEFAULT 'normal',
    "rating" INTEGER,
    "feedback" TEXT,
    "addedUsers" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "formAnswers" JSONB,
    "autoCloseDisabled" BOOLEAN NOT NULL DEFAULT false,
    "closedAt" TIMESTAMP(3),
    "firstResponse" TIMESTAMP(3),
    "lastActivityAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "tickets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ticket_transcripts" (
    "id" TEXT NOT NULL,
    "ticketId" TEXT NOT NULL,
    "panelId" TEXT,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "closedBy" TEXT,
    "messageCount" INTEGER NOT NULL DEFAULT 0,
    "messages" JSONB NOT NULL,
    "htmlContent" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ticket_transcripts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reputations" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "giverId" TEXT NOT NULL,
    "reason" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "reputations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "giveaways" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT,
    "hostId" TEXT NOT NULL,
    "prize" TEXT NOT NULL,
    "description" TEXT,
    "winners" INTEGER NOT NULL DEFAULT 1,
    "entries" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "winnerIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "endsAt" TIMESTAMP(3) NOT NULL,
    "ended" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "giveaways_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "suggestions" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT,
    "userId" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'pending',
    "upvotes" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "downvotes" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "staffNote" TEXT,
    "reviewedBy" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "suggestions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "starboard_entries" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "originalMsgId" TEXT NOT NULL,
    "originalChId" TEXT NOT NULL,
    "starboardMsgId" TEXT,
    "authorId" TEXT NOT NULL,
    "stars" INTEGER NOT NULL DEFAULT 0,
    "content" TEXT,
    "attachmentUrl" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "starboard_entries_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "afk_statuses" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "reason" TEXT NOT NULL DEFAULT 'AFK',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "afk_statuses_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "sticky_messages" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT,
    "title" TEXT,
    "description" TEXT NOT NULL,
    "color" TEXT NOT NULL DEFAULT '#5865F2',
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "createdBy" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "sticky_messages_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "reminders" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "remindAt" TIMESTAMP(3) NOT NULL,
    "fired" BOOLEAN NOT NULL DEFAULT false,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "reminders_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rifas" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "channelId" TEXT NOT NULL,
    "messageId" TEXT,
    "hostId" TEXT NOT NULL,
    "prize" TEXT NOT NULL,
    "description" TEXT,
    "maxSlots" INTEGER NOT NULL,
    "participants" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "winnerIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "winnersCount" INTEGER NOT NULL DEFAULT 1,
    "endsAt" TIMESTAMP(3),
    "ended" BOOLEAN NOT NULL DEFAULT false,
    "cancelled" BOOLEAN NOT NULL DEFAULT false,
    "autoDrawOnFull" BOOLEAN NOT NULL DEFAULT false,
    "allowSelfJoin" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rifas_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "command_permissions" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "command" TEXT NOT NULL,
    "roleIds" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "disabled" BOOLEAN NOT NULL DEFAULT false,
    "updatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "command_permissions_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "shop_products" (
    "id" TEXT NOT NULL,
    "guildId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "price" DOUBLE PRECISION NOT NULL,
    "stock" INTEGER NOT NULL DEFAULT 0,
    "image" TEXT,
    "images" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "active" BOOLEAN NOT NULL DEFAULT true,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "shop_products_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "invites_guildId_inviterId_idx" ON "invites"("guildId", "inviterId");

-- CreateIndex
CREATE INDEX "invites_guildId_invitedId_idx" ON "invites"("guildId", "invitedId");

-- CreateIndex
CREATE INDEX "backups_guildId_idx" ON "backups"("guildId");

-- CreateIndex
CREATE INDEX "warnings_guildId_userId_idx" ON "warnings"("guildId", "userId");

-- CreateIndex
CREATE UNIQUE INDEX "warnings_guildId_sourceWarningId_key" ON "warnings"("guildId", "sourceWarningId");

-- CreateIndex
CREATE INDEX "mod_actions_guildId_userId_idx" ON "mod_actions"("guildId", "userId");

-- CreateIndex
CREATE INDEX "mod_actions_expiresAt_idx" ON "mod_actions"("expiresAt");

-- CreateIndex
CREATE UNIQUE INDEX "mod_actions_guildId_sourceActionId_key" ON "mod_actions"("guildId", "sourceActionId");

-- CreateIndex
CREATE UNIQUE INDEX "reaction_roles_messageId_emoji_key" ON "reaction_roles"("messageId", "emoji");

-- CreateIndex
CREATE INDEX "auto_responses_guildId_idx" ON "auto_responses"("guildId");

-- CreateIndex
CREATE INDEX "scheduled_messages_guildId_idx" ON "scheduled_messages"("guildId");

-- CreateIndex
CREATE INDEX "custom_text_commands_guildId_idx" ON "custom_text_commands"("guildId");

-- CreateIndex
CREATE UNIQUE INDEX "custom_text_commands_guildId_name_key" ON "custom_text_commands"("guildId", "name");

-- CreateIndex
CREATE INDEX "rank_money_entries_guildId_withdrawnAt_idx" ON "rank_money_entries"("guildId", "withdrawnAt");

-- CreateIndex
CREATE INDEX "rank_money_entries_guildId_createdAt_idx" ON "rank_money_entries"("guildId", "createdAt");

-- CreateIndex
CREATE UNIQUE INDEX "tickets_channelId_key" ON "tickets"("channelId");

-- CreateIndex
CREATE INDEX "tickets_guildId_status_idx" ON "tickets"("guildId", "status");

-- CreateIndex
CREATE INDEX "tickets_guildId_userId_idx" ON "tickets"("guildId", "userId");

-- CreateIndex
CREATE INDEX "ticket_transcripts_guildId_idx" ON "ticket_transcripts"("guildId");

-- CreateIndex
CREATE INDEX "ticket_transcripts_ticketId_idx" ON "ticket_transcripts"("ticketId");

-- CreateIndex
CREATE INDEX "reputations_guildId_userId_idx" ON "reputations"("guildId", "userId");

-- CreateIndex
CREATE INDEX "reputations_guildId_giverId_idx" ON "reputations"("guildId", "giverId");

-- CreateIndex
CREATE INDEX "giveaways_guildId_idx" ON "giveaways"("guildId");

-- CreateIndex
CREATE INDEX "giveaways_endsAt_idx" ON "giveaways"("endsAt");

-- CreateIndex
CREATE INDEX "suggestions_guildId_idx" ON "suggestions"("guildId");

-- CreateIndex
CREATE INDEX "suggestions_guildId_status_idx" ON "suggestions"("guildId", "status");

-- CreateIndex
CREATE INDEX "starboard_entries_guildId_idx" ON "starboard_entries"("guildId");

-- CreateIndex
CREATE UNIQUE INDEX "starboard_entries_guildId_originalMsgId_key" ON "starboard_entries"("guildId", "originalMsgId");

-- CreateIndex
CREATE UNIQUE INDEX "afk_statuses_guildId_userId_key" ON "afk_statuses"("guildId", "userId");

-- CreateIndex
CREATE UNIQUE INDEX "sticky_messages_channelId_key" ON "sticky_messages"("channelId");

-- CreateIndex
CREATE INDEX "sticky_messages_guildId_idx" ON "sticky_messages"("guildId");

-- CreateIndex
CREATE INDEX "reminders_remindAt_fired_idx" ON "reminders"("remindAt", "fired");

-- CreateIndex
CREATE INDEX "reminders_userId_guildId_idx" ON "reminders"("userId", "guildId");

-- CreateIndex
CREATE INDEX "rifas_guildId_idx" ON "rifas"("guildId");

-- CreateIndex
CREATE INDEX "rifas_endsAt_idx" ON "rifas"("endsAt");

-- CreateIndex
CREATE UNIQUE INDEX "command_permissions_guildId_command_key" ON "command_permissions"("guildId", "command");

-- CreateIndex
CREATE INDEX "shop_products_guildId_active_idx" ON "shop_products"("guildId", "active");

-- AddForeignKey
ALTER TABLE "invites" ADD CONSTRAINT "invites_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "backups" ADD CONSTRAINT "backups_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "warnings" ADD CONSTRAINT "warnings_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "mod_actions" ADD CONSTRAINT "mod_actions_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reaction_roles" ADD CONSTRAINT "reaction_roles_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "auto_responses" ADD CONSTRAINT "auto_responses_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "scheduled_messages" ADD CONSTRAINT "scheduled_messages_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "custom_text_commands" ADD CONSTRAINT "custom_text_commands_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "rank_money_entries" ADD CONSTRAINT "rank_money_entries_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "polls" ADD CONSTRAINT "polls_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ticket_panels" ADD CONSTRAINT "ticket_panels_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "tickets" ADD CONSTRAINT "tickets_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "tickets" ADD CONSTRAINT "tickets_panelId_fkey" FOREIGN KEY ("panelId") REFERENCES "ticket_panels"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ticket_transcripts" ADD CONSTRAINT "ticket_transcripts_ticketId_fkey" FOREIGN KEY ("ticketId") REFERENCES "tickets"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ticket_transcripts" ADD CONSTRAINT "ticket_transcripts_panelId_fkey" FOREIGN KEY ("panelId") REFERENCES "ticket_panels"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "reputations" ADD CONSTRAINT "reputations_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "giveaways" ADD CONSTRAINT "giveaways_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "suggestions" ADD CONSTRAINT "suggestions_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "starboard_entries" ADD CONSTRAINT "starboard_entries_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "afk_statuses" ADD CONSTRAINT "afk_statuses_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "sticky_messages" ADD CONSTRAINT "sticky_messages_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "rifas" ADD CONSTRAINT "rifas_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "command_permissions" ADD CONSTRAINT "command_permissions_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "shop_products" ADD CONSTRAINT "shop_products_guildId_fkey" FOREIGN KEY ("guildId") REFERENCES "guild_configs"("id") ON DELETE CASCADE ON UPDATE CASCADE;


