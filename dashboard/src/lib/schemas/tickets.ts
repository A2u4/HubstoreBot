import { z } from "zod";
import { hexColor, optionalSnowflake, snowflake, snowflakes } from "./common";

const text = (max: number) => z.string().max(max).nullable().optional();
const hex = hexColor.nullable().optional();

const formQuestion = z.object({
  label: z.string().trim().min(1).max(45),
  placeholder: z.string().max(100).optional().nullable(),
  style: z.enum(["short", "paragraph"]).optional(),
  required: z.boolean().optional(),
  minLength: z.number().int().min(0).max(4000).optional().nullable(),
  maxLength: z.number().int().min(1).max(4000).optional().nullable(),
}).passthrough();

const panelFields = {
  name: z.string().trim().min(1).max(100),
  channelId: snowflake,
  title: z.string().max(256),
  description: z.string().max(4000),
  embedColor: hexColor,
  footerText: text(256),
  embedImages: z.array(z.string().url()).max(20),
  embedImageInterval: z.number().int().min(1).max(86_400),
  buttonLabel: z.string().trim().min(1).max(80),
  buttonEmoji: text(100),
  buttonColor: z.enum(["Primary", "Secondary", "Success", "Danger"]),
  style: z.string().max(50), // stored for compatibility; panels always render buttons
  categoryId: optionalSnowflake,
  closedCategoryId: optionalSnowflake,
  namingPattern: z.string().trim().min(1).max(100),
  staffRoleIds: snowflakes,
  adminRoleIds: snowflakes,
  ticketLimit: z.number().int().min(1).max(9999),
  mentionStaff: z.boolean(),
  mentionCreator: z.boolean(),
  welcomeTitle: text(256),
  welcomeMessage: text(2000),
  welcomeColor: hexColor,
  closeRequestEnabled: z.boolean(),
  closeRequestMessage: text(1000),
  claimEnabled: z.boolean(),
  claimLockOthers: z.boolean(),
  transcriptEnabled: z.boolean(),
  transcriptChannelId: optionalSnowflake,
  transcriptDMUser: z.boolean(),
  transcriptDMStaff: z.boolean(),
  logChannelId: optionalSnowflake,
  showCloseButton: z.boolean(),
  showClaimButton: z.boolean(),
  showTranscriptButton: z.boolean(),
  formEnabled: z.boolean(),
  formTitle: text(45),
  formQuestions: z.array(formQuestion).max(5).nullable(),
  escalatePanelId: z.string().uuid().nullable(),
  feedbackEnabled: z.boolean(),
  feedbackMessage: text(1000),
  autoCloseHours: z.number().int().min(0).max(720),
  panelAutoRepost: z.boolean(),
  panelAutoRepostCooldown: z.number().int().min(1).max(300),
  panelAutoRepostIgnoreBots: z.boolean(),
  groupEmbedTitle: text(256),
  groupEmbedDescription: text(4000),
  groupEmbedColor: hex,
  groupEmbedImages: z.array(z.string().url()).max(20),
};

export const ticketPanelCreate = z.object(panelFields).partial().required({ name: true, channelId: true }).strict();
export const ticketPanelUpdate = z.object(panelFields).partial().strict();

export const ticketUpdate = z.object({
  priority: z.enum(["low", "normal", "high", "urgent"]).optional(), // same values as the bot (v1 API wrongly expected "medium")
  topic: z.string().max(256).optional(),
  status: z.enum(["open", "closed"]).optional(),
}).strict();

export const panelDeploy = z.object({
  channelId: snowflake,
  panelIds: z.array(z.string().uuid()).min(1).max(5),
  embedTitle: z.string().max(256).optional(),
  embedDescription: z.string().max(4000).optional(),
  embedColor: hexColor.optional(),
  embedImages: z.array(z.string().url()).max(20).optional(),
  embedImageInterval: z.number().int().min(1).max(86_400).optional(),
});

export const panelCrossDeploy = z.object({
  sourcePanelIds: z.array(z.string().uuid()).min(1).max(5),
  targetGuildId: snowflake,
  channelId: snowflake,
  embedTitle: z.string().max(256).optional(),
  embedDescription: z.string().max(4000).optional(),
  embedColor: hexColor.optional(),
});
