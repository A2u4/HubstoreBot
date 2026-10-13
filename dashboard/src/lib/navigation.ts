import {
  ArrowLeftRight, BarChart2, Bot, Coins, Database, Gift, Hand, LayoutDashboard, Lightbulb, Medal, Mic, Network,
  PartyPopper, ScrollText, Send, Settings, Shield, ShieldAlert, ShieldCheck, ShoppingCart, Sparkles, Star, StickyNote,
  Tags, Terminal, Ticket, TrendingUp, UserPlus, type LucideIcon,
} from "lucide-react";

export interface NavItem {
  group: string;
  path: string;
  icon: LucideIcon;
  label: string;
  description: string;
  /** GuildConfig toggle that enables this module (shown as on/off in the sidebar). */
  toggle?: string;
  isNew?: boolean;
}

export const NAV: NavItem[] = [
  { group: "Inicio", path: "", icon: LayoutDashboard, label: "Resumen", description: "Estado general y accesos rápidos" },
  { group: "Inicio", path: "/config", icon: Settings, label: "Configuración", description: "Módulos, roles por módulo y clonado" },
  { group: "Inicio", path: "/commands", icon: Terminal, label: "Comandos", description: "Permisos por comando y comandos de texto" },

  { group: "Comunidad", path: "/welcome", icon: Hand, label: "Bienvenida", description: "Entradas, salidas y roles iniciales", toggle: "welcomeEnabled" },
  { group: "Comunidad", path: "/leveling", icon: TrendingUp, label: "Niveles", description: "XP por mensajes, ranking y recompensas", toggle: "levelingEnabled", isNew: true },
  { group: "Comunidad", path: "/economy", icon: Coins, label: "Economía", description: "Moneda, trabajos, tienda de artículos", toggle: "economyEnabled", isNew: true },
  { group: "Comunidad", path: "/fun", icon: PartyPopper, label: "Diversión", description: "Roleplay, matrimonios y minijuegos", toggle: "funEnabled", isNew: true },
  { group: "Comunidad", path: "/invites", icon: UserPlus, label: "Invitaciones", description: "Invitadores y cuentas sospechosas", toggle: "invitesEnabled" },
  { group: "Comunidad", path: "/reputation", icon: Star, label: "Reputación", description: "Puntos, ranking y migración", toggle: "reputationEnabled" },
  { group: "Comunidad", path: "/reactionroles", icon: Tags, label: "Roles por reacción", description: "Paneles de roles interactivos" },
  { group: "Comunidad", path: "/suggestions", icon: Lightbulb, label: "Sugerencias", description: "Propuestas y votaciones", toggle: "suggestionsEnabled" },
  { group: "Comunidad", path: "/starboard", icon: Sparkles, label: "Destacados", description: "Mensajes destacados", toggle: "starboardEnabled" },
  { group: "Comunidad", path: "/giveaways", icon: Gift, label: "Sorteos", description: "Sorteos automáticos", toggle: "giveawayEnabled" },
  { group: "Comunidad", path: "/rifas", icon: Gift, label: "Rifas", description: "Rifas por puestos", toggle: "rifaEnabled" },
  { group: "Comunidad", path: "/temp-voice", icon: Mic, label: "Voz temporal", description: "Canales de voz que se crean al entrar", toggle: "tempVoiceEnabled", isNew: true },

  { group: "Seguridad", path: "/moderation", icon: Shield, label: "Moderación", description: "Sanciones y advertencias", toggle: "moderationEnabled" },
  { group: "Seguridad", path: "/automod", icon: ShieldAlert, label: "AutoMod", description: "Protección automática", toggle: "automodEnabled" },
  { group: "Seguridad", path: "/verification", icon: ShieldCheck, label: "Verificación", description: "Panel con botón o captcha y Market", toggle: "verificationEnabled", isNew: true },

  { group: "Atención y ventas", path: "/tickets", icon: Ticket, label: "Tickets", description: "Paneles, tickets y transcripciones", toggle: "ticketsEnabled" },
  { group: "Atención y ventas", path: "/shop", icon: ShoppingCart, label: "Tienda", description: "Catálogo, stock, GIF y publicación" },
  { group: "Atención y ventas", path: "/dar-rango", icon: Medal, label: "Dar rango", description: "Mensajes por rango y archivo de imágenes" },

  { group: "Contenido", path: "/automation", icon: Bot, label: "Automatización", description: "Respuestas, mensajes programados y encuestas", toggle: "automationEnabled" },
  { group: "Contenido", path: "/sticky", icon: StickyNote, label: "Mensajes fijos", description: "Mensajes que permanecen al final", toggle: "stickyEnabled" },
  { group: "Contenido", path: "/messages", icon: Send, label: "Enviar mensaje", description: "Publicar mensajes y embeds" },

  { group: "Administración", path: "/logging", icon: ScrollText, label: "Registros", description: "Canales de auditoría", toggle: "loggingEnabled" },
  { group: "Administración", path: "/server-stats", icon: BarChart2, label: "Estadísticas", description: "Contadores en canales de voz" },
  { group: "Administración", path: "/backups", icon: Database, label: "Respaldos", description: "Copias de seguridad", toggle: "backupEnabled" },
  { group: "Administración", path: "/migration", icon: ArrowLeftRight, label: "Migración", description: "Clonar configuración y paneles" },
  { group: "Administración", path: "/cross-bot", icon: Network, label: "Sincronizar bots", description: "Bans y reputación compartidos" },
];

export function navHref(bot: string, guildId: string, item: Pick<NavItem, "path">): string {
  return `/bots/${bot}/${guildId}${item.path}`;
}
