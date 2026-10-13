export type DiscordStyle = "Primary" | "Secondary" | "Success" | "Danger";
export type MediaEffect = "normal" | "dark" | "saturated" | "soft" | "mono";

export interface PaymentOption { id: string; emoji?: string | null; country: string; price: string; methods?: string | null; stock?: string | null; hidden?: boolean }
export interface CategoryAction { id: string; label: string; emoji?: string | null; style?: DiscordStyle }

export interface ShopCategory {
  id: string; label: string; emoji?: string | null; style?: DiscordStyle; description?: string | null;
  image?: string | null; images?: string[]; effectImages?: string[]; mediaWidth?: number; mediaHeight?: number; mediaFit?: "contain" | "cover";
  imageInterval?: number; playbackMode?: "sequence" | "interval"; playlistImage?: string | null; playlistDuration?: number;
  paymentOptions?: PaymentOption[]; stockAmount?: number | null; stockUnit?: string | null; availabilityText?: string | null;
  footerText?: string | null; effect?: MediaEffect; channelId?: string | null; messageId?: string | null; standalone?: boolean;
  announcementLastSentAt?: string | null; actionButtons?: CategoryAction[] | null;
}

export interface CustomButton {
  id: string; label: string; emoji?: string | null; style: DiscordStyle; type?: string | null; welcomeMessage?: string | null;
  panelId?: string | null; categoryId?: string | null; staffRoleIds?: string[]; namingPattern?: string | null;
  stockBehavior?: "keep_enabled" | "disable_when_empty" | "hide_when_empty"; ticketTopic?: string | null; categoryOnly?: boolean;
}

export interface ShopProduct {
  id: string; name: string; category: string; description: string; price: number; priceLabel: string | null; stock: number;
  stockLabel: string | null; image: string | null; images: string[]; active: boolean;
}

/** The GuildConfig fields this page edits. */
export interface ShopConfig {
  shopChannelId: string | null; shopTitle: string | null; shopDescription: string | null; shopColor: string | null;
  shopImage: string | null; shopImages: string[]; shopImageInterval: number; shopThumbnail: string | null;
  shopButtonStyle: "multiple" | "single" | null; shopCustomButtons: CustomButton[]; shopCategories: ShopCategory[];
  shopBuyButtonLabel: string | null; shopBuyButtonEmoji: string | null; shopBuyButtonStyle: DiscordStyle | null; shopPanelId: string | null;
  shopStickyEnabled: boolean; shopStickyCooldown: number; shopAnnouncementEnabled: boolean; shopAnnouncementChannelId: string | null;
  shopAnnouncementInterval: number; shopAnnouncementMessage: string | null;
}

export const SHOP_KEYS: Array<keyof ShopConfig> = [
  "shopChannelId", "shopTitle", "shopDescription", "shopColor", "shopImage", "shopImages", "shopImageInterval", "shopThumbnail",
  "shopButtonStyle", "shopCustomButtons", "shopCategories", "shopBuyButtonLabel", "shopBuyButtonEmoji", "shopBuyButtonStyle",
  "shopPanelId", "shopStickyEnabled", "shopStickyCooldown", "shopAnnouncementEnabled", "shopAnnouncementChannelId",
  "shopAnnouncementInterval", "shopAnnouncementMessage",
];

export const STYLES = [
  { value: "Primary", label: "Azul" }, { value: "Secondary", label: "Gris" }, { value: "Success", label: "Verde" }, { value: "Danger", label: "Rojo" },
];

export const DEFAULT_FOOTER = "────────────\nUsa **Comprar** para iniciar una compra o **Hacer un encargo** si buscas algo que todavía no aparece en el catálogo.";

export const MEDIA_EFFECTS: Array<{ value: MediaEffect; label: string }> = [
  { value: "normal", label: "Normal" }, { value: "dark", label: "Oscuro" }, { value: "saturated", label: "Saturado" },
  { value: "soft", label: "Suave" }, { value: "mono", label: "Monocromo" },
];

export const MEDIA_TEMPLATES = [
  { id: "discord", label: "Banner Discord (960×540)", width: 960, height: 540 },
  { id: "wide", label: "Banner ancho (960×384)", width: 960, height: 384 },
  { id: "square", label: "Cuadrado (800×800)", width: 800, height: 800 },
  { id: "portrait", label: "Vertical (720×900)", width: 720, height: 900 },
];

export function newCategory(index: number): ShopCategory {
  return {
    id: `seccion${index}`, label: `Sección ${index}`, emoji: "🛍️", style: "Primary", description: "", images: [], effectImages: [],
    mediaWidth: 960, mediaHeight: 540, mediaFit: "cover", imageInterval: 3600, playbackMode: "sequence", playlistImage: null,
    playlistDuration: 0, paymentOptions: [], stockAmount: null, stockUnit: "", availabilityText: "", footerText: DEFAULT_FOOTER, effect: "normal",
  };
}

const clean = (value: unknown, max: number) => String(value ?? "").trim().slice(0, max);

/** Shape categories exactly as the API schema expects (v1 normalised the same way before saving). */
export function normalizeCategories(categories: ShopCategory[]): ShopCategory[] {
  const seen = new Set<string>();
  return categories.slice(0, 10).flatMap((c, i) => {
    const id = clean(c.id || `seccion${i + 1}`, 40).toLowerCase().replace(/[^a-z0-9_-]/g, "");
    if (!id || !clean(c.label, 50) || seen.has(id)) return [];
    seen.add(id);
    const images = [...new Set((c.images ?? []).filter((u) => /^https?:\/\//.test(u)))].slice(0, 20);
    return [{
      ...c, id, label: clean(c.label, 50), emoji: clean(c.emoji, 100) || "🛍️", description: clean(c.description, 500),
      image: images[0] ?? null, images, effectImages: (c.effectImages ?? []).slice(0, 20),
      paymentOptions: (c.paymentOptions ?? []).filter((o) => clean(o.country, 60) && clean(o.price, 100)).slice(0, 25).map((o) => ({
        id: o.id.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80), emoji: clean(o.emoji, 20) || null, country: clean(o.country, 60),
        price: clean(o.price, 100), methods: clean(o.methods, 150) || null, stock: clean(o.stock, 60) || null, hidden: o.hidden === true,
      })),
      availabilityText: c.stockAmount != null ? `${c.stockAmount} ${c.stockUnit || "unidades disponibles"}`.slice(0, 100) : clean(c.availabilityText, 100) || null,
      stockUnit: clean(c.stockUnit, 80) || null, footerText: clean(c.footerText, 1000) || null,
      actionButtons: (c.actionButtons ?? []).filter((a) => clean(a.label, 80)).slice(0, 5),
      playlistImage: c.playlistImage || null, channelId: c.channelId || null, messageId: c.messageId || null,
    }];
  });
}
