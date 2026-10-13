import { z } from "zod";
import { buttonStyle, hexColor, optionalSnowflake, optionalUrl, snowflake, snowflakes } from "./common";

const text = (max: number) => z.string().max(max);
const optionalText = (max: number) => z.string().max(max).nullable().optional();
const int = (min: number, max: number) => z.number().int().min(min).max(max);

export const paymentOptionSchema = z.object({
  id: z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/),
  emoji: z.string().trim().max(20).nullable().optional(),
  country: z.string().trim().min(1).max(60),
  price: z.string().trim().min(1).max(100),
  methods: z.string().trim().max(150).nullable().optional(),
  stock: z.string().trim().max(60).nullable().optional(),
  hidden: z.boolean().optional(),
}).strict();

export const shopCategorySchema = z.object({
  id: z.string().regex(/^[a-z0-9_-]{1,40}$/),
  label: z.string().trim().min(1).max(50),
  emoji: z.string().max(100).nullable().optional(),
  style: buttonStyle.optional(),
  description: z.string().trim().max(500).nullable().optional(),
  image: optionalUrl,
  images: z.array(z.string().url()).max(20).optional(),
  effectImages: z.array(z.string().url()).max(20).optional(),
  mediaWidth: int(320, 1920).optional(),
  mediaHeight: int(180, 1080).optional(),
  mediaFit: z.enum(["contain", "cover"]).optional(),
  imageInterval: int(60, 2_592_000).optional(),
  playbackMode: z.enum(["sequence", "interval"]).optional(),
  playlistImage: optionalUrl,
  playlistDuration: int(0, 60_000).optional(),
  paymentOptions: z.array(paymentOptionSchema).max(25).optional(),
  stockAmount: int(0, 1_000_000).nullable().optional(),
  stockUnit: z.string().trim().max(80).nullable().optional(),
  availabilityText: z.string().trim().max(100).nullable().optional(),
  footerText: z.string().trim().max(1000).nullable().optional(),
  effect: z.enum(["normal", "dark", "saturated", "soft", "mono"]).optional(),
  channelId: optionalSnowflake,
  messageId: optionalSnowflake,
  standalone: z.boolean().optional(),
  announcementLastSentAt: z.string().datetime().nullable().optional(),
  actionButtons: z.array(z.object({
    id: z.string().min(1).max(80),
    label: z.string().trim().min(1).max(80),
    emoji: z.string().max(100).nullable().optional(),
    style: buttonStyle.optional(),
  }).strict()).max(5).nullable().optional(),
}).strict();

export const shopCustomButtonSchema = z.object({
  id: z.string(),
  label: z.string().max(80),
  emoji: z.string().max(100).nullable().optional(),
  style: buttonStyle,
  type: z.string().max(50).nullable().optional(),
  welcomeMessage: z.string().max(2000).nullable().optional(),
  panelId: z.string().uuid().nullable().optional(),
  categoryId: optionalSnowflake,
  staffRoleIds: snowflakes.optional(),
  namingPattern: z.string().min(1).max(100).nullable().optional(),
  stockBehavior: z.enum(["keep_enabled", "disable_when_empty", "hide_when_empty"]).optional(),
  ticketTopic: z.string().max(200).nullable().optional(),
  categoryOnly: z.boolean().optional(),
}).strict();

/** Every GuildConfig field the dashboard may write. Unknown keys are rejected (strict). */
export const configUpdateSchema = z.object({
  prefix: z.string().min(1).max(5).optional(),
  language: z.enum(["en", "es", "fr", "de", "pt"]).optional(),

  // Module toggles
  invitesEnabled: z.boolean().optional(),
  moderationEnabled: z.boolean().optional(),
  automodEnabled: z.boolean().optional(),
  ticketsEnabled: z.boolean().optional(),
  automationEnabled: z.boolean().optional(),
  welcomeEnabled: z.boolean().optional(),
  farewellEnabled: z.boolean().optional(),
  reputationEnabled: z.boolean().optional(),
  giveawayEnabled: z.boolean().optional(),
  rifaEnabled: z.boolean().optional(),
  suggestionsEnabled: z.boolean().optional(),
  starboardEnabled: z.boolean().optional(),
  afkEnabled: z.boolean().optional(),
  backupEnabled: z.boolean().optional(),
  stickyEnabled: z.boolean().optional(),
  loggingEnabled: z.boolean().optional(),
  levelingEnabled: z.boolean().optional(),
  economyEnabled: z.boolean().optional(),
  funEnabled: z.boolean().optional(),
  verificationEnabled: z.boolean().optional(),
  tempVoiceEnabled: z.boolean().optional(),
  moduleAllowedRoles: z.record(z.string().max(40), snowflakes).optional(),

  // Welcome / farewell
  welcomeChannelId: optionalSnowflake,
  welcomeMessage: optionalText(2000),
  welcomeImageEnabled: z.boolean().optional(),
  welcomeEmbedTitle: optionalText(256),
  welcomeEmbedColor: hexColor.nullable().optional(),
  welcomeEmbedFooter: optionalText(2048),
  welcomeEmbedDescription: optionalText(4096),
  welcomeEmbedImage: optionalUrl,
  welcomeEmbedThumbnail: optionalUrl,
  welcomeImageBgColor: hexColor.nullable().optional(),
  welcomeImageAccent1: hexColor.nullable().optional(),
  welcomeImageAccent2: hexColor.nullable().optional(),
  welcomeImagePillText: optionalText(64),
  welcomeImageBrand: optionalText(64),
  welcomeImageSubtitle: optionalText(128),
  welcomeImageMemberLabel: optionalText(128),
  welcomeImageFont: optionalText(64),
  welcomeImageFontWeight: int(100, 900).nullable().optional(),
  welcomeCardLayout: z.any().optional(),
  farewellChannelId: optionalSnowflake,
  farewellMessage: optionalText(2000),
  farewellImageEnabled: z.boolean().optional(),
  farewellCardLayout: z.any().optional(),
  farewellEmbedTitle: optionalText(256),
  farewellEmbedColor: hexColor.nullable().optional(),
  farewellEmbedFooter: optionalText(2048),
  farewellEmbedDescription: optionalText(4096),
  farewellEmbedImage: optionalUrl,
  farewellEmbedThumbnail: optionalUrl,
  joinRoleIds: snowflakes.optional(),
  botJoinRoleIds: snowflakes.optional(),

  // Logging
  modLogChannelId: optionalSnowflake,
  warnLogChannelId: optionalSnowflake,
  messageLogChannelId: optionalSnowflake,
  joinLeaveLogChannelId: optionalSnowflake,
  auditLogChannelId: optionalSnowflake,
  voiceLogChannelId: optionalSnowflake,
  verificationLogChannelId: optionalSnowflake,
  banLogChannelId: optionalSnowflake,
  banSyncEnabled: z.boolean().optional(),
  repSyncGuildIds: snowflakes.optional(),
  muteRoleId: optionalSnowflake,

  // Dar rango / stats channels
  darRangoImagesChannelId: optionalSnowflake,
  darRangoRoles: z.array(z.object({
    id: z.string().max(64),
    pattern: z.string().max(100),
    emoji: z.string().max(32).optional(),
    message: z.string().max(1000).optional(),
  })).max(50).nullable().optional(),
  statsChannels: z.array(z.object({
    id: z.string().max(64),
    channelId: z.string().max(20),
    type: z.enum(["members", "humans", "bots", "online", "roles", "channels", "boosts"]),
    format: z.string().max(200),
  })).max(20).nullable().optional(),

  // Tickets (global)
  ticketCategoryId: optionalSnowflake,
  ticketLogChannelId: optionalSnowflake,
  ticketTranscriptChannelId: optionalSnowflake,
  ticketStaffRoleIds: snowflakes.optional(),
  ticketCloseConfirmation: z.boolean().optional(),
  ticketDMTranscript: z.boolean().optional(),

  // AutoMod
  antiSpamEnabled: z.boolean().optional(),
  antiSpamThreshold: int(1, 50).optional(),
  antiSpamInterval: int(1, 60).optional(),
  antiFloodEnabled: z.boolean().optional(),
  antiCapsEnabled: z.boolean().optional(),
  antiCapsThreshold: int(30, 100).optional(),
  antiCapsMinLength: int(5, 500).optional(),
  antiLinksEnabled: z.boolean().optional(),
  antiLinksWhitelist: z.array(z.string().max(200)).max(200).optional(),
  blacklistEnabled: z.boolean().optional(),
  blacklistedWords: z.array(z.string().max(100)).max(500).optional(),
  automodExemptRoleIds: snowflakes.optional(),
  automodExemptChannelIds: snowflakes.optional(),

  // Community
  repCooldown: int(0, 604_800).optional(),
  repChannelId: optionalSnowflake,
  starboardChannelId: optionalSnowflake,
  starboardEmoji: z.string().min(1).max(50).optional(),
  starboardThreshold: int(1, 100).optional(),
  suggestionsChannelId: optionalSnowflake,
  suggestionsLogChannelId: optionalSnowflake,

  // Rifas
  rifaCategoryId: optionalSnowflake,
  rifaPanelChannelId: optionalSnowflake,
  rifaLogChannelId: optionalSnowflake,
  rifaStaffRoleIds: snowflakes.optional(),

  // Shop
  shopChannelId: optionalSnowflake,
  shopMessageId: optionalSnowflake,
  shopTitle: optionalText(256),
  shopDescription: optionalText(4000),
  shopColor: hexColor.nullable().optional(),
  shopImage: optionalUrl,
  shopImages: z.array(z.string().url()).max(20).optional(),
  shopImageInterval: int(0, 2_592_000).optional(),
  shopThumbnail: optionalUrl,
  shopButtonStyle: z.enum(["multiple", "single"]).nullable().optional(),
  shopCustomButtons: z.array(shopCustomButtonSchema).max(20).optional(),
  shopCategories: z.array(shopCategorySchema).min(1).max(10).optional(),
  shopBuyButtonLabel: optionalText(80),
  shopBuyButtonEmoji: optionalText(100),
  shopBuyButtonStyle: buttonStyle.nullable().optional(),
  shopPanelId: z.string().uuid().nullable().optional(),
  shopStickyEnabled: z.boolean().optional(),
  shopStickyCooldown: int(5, 3600).optional(),
  shopAnnouncementEnabled: z.boolean().optional(),
  shopAnnouncementChannelId: optionalSnowflake,
  shopAnnouncementInterval: int(300, 604_800).optional(),
  shopAnnouncementMessage: optionalText(2000),

  // Market security
  marketVerificationEnabled: z.boolean().optional(),
  marketVerificationRoleId: optionalSnowflake,
  marketVerificationLogChannelId: optionalSnowflake,
  marketVerificationRetentionDays: int(1, 3650).optional(),
  marketVpnCheckEnabled: z.boolean().optional(),
  marketVpnPolicy: z.enum(["review", "block"]).optional(),
  marketBlockedNetworkAction: z.enum(["deny", "ban"]).optional(),

  // Leveling
  levelUpChannelId: z.union([snowflake, z.literal("off"), z.literal(""), z.null()]).optional()
    .transform((v) => (v === "" ? null : v)),
  levelUpMessage: text(1000).optional(),
  xpPerMessageMin: int(1, 500).optional(),
  xpPerMessageMax: int(1, 500).optional(),
  xpCooldownSeconds: int(0, 3600).optional(),
  levelingIgnoredChannelIds: snowflakes.optional(),
  levelingIgnoredRoleIds: snowflakes.optional(),
  levelRewardsStack: z.boolean().optional(),

  // Economy
  currencyName: z.string().trim().min(1).max(32).optional(),
  currencySymbol: z.string().trim().min(1).max(64).optional(),
  economyStartBalance: int(0, 1_000_000_000).optional(),
  dailyAmount: int(0, 100_000_000).optional(),
  weeklyAmount: int(0, 100_000_000).optional(),
  workMin: int(0, 100_000_000).optional(),
  workMax: int(0, 100_000_000).optional(),
  workCooldownSeconds: int(0, 604_800).optional(),
  crimeMin: int(0, 100_000_000).optional(),
  crimeMax: int(0, 100_000_000).optional(),
  crimeSuccessRate: int(0, 100).optional(),
  crimeCooldownSeconds: int(0, 604_800).optional(),
  robEnabled: z.boolean().optional(),
  robCooldownSeconds: int(0, 604_800).optional(),

  // Verification panel
  verificationMode: z.enum(["button", "captcha"]).optional(),
  verificationChannelId: optionalSnowflake,
  verificationRoleId: optionalSnowflake,
  verificationRemoveRoleId: optionalSnowflake,
  verificationPanelTitle: z.string().trim().min(1).max(256).optional(),
  verificationPanelMessage: z.string().trim().min(1).max(4000).optional(),

  // Temp voice
  tempVoiceHubChannelId: optionalSnowflake,
  tempVoiceCategoryId: optionalSnowflake,
  tempVoiceNameTemplate: z.string().trim().min(1).max(100).optional(),
  tempVoiceUserLimit: int(0, 99).optional(),
}).strict();

export type ConfigUpdate = z.infer<typeof configUpdateSchema>;

/** Fields whose change alters which slash commands the bot deploys to the guild. */
export const RESYNC_FIELDS = new Set<string>(["invitesEnabled", "marketVerificationEnabled"]);
