/** Approximate Discord rendering of a message + embed, for live previews. */
export interface EmbedData {
  title?: string | null;
  description?: string | null;
  color?: string | null;
  url?: string | null;
  authorName?: string | null;
  authorIconUrl?: string | null;
  footerText?: string | null;
  footerIconUrl?: string | null;
  imageUrl?: string | null;
  thumbnailUrl?: string | null;
  timestamp?: boolean;
  fields?: Array<{ name: string; value: string; inline?: boolean }>;
}

function Markdown({ text }: { text: string }) {
  // Bold, italics, inline code and line breaks: enough for a preview without an HTML injection surface.
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={i}>{part.slice(2, -2)}</strong>;
        if (/^`[^`]+`$/.test(part)) return <code key={i} className="rounded bg-black/40 px-1 text-[0.85em]">{part.slice(1, -1)}</code>;
        if (/^\*[^*]+\*$/.test(part)) return <em key={i}>{part.slice(1, -1)}</em>;
        return <span key={i}>{part}</span>;
      })}
    </>
  );
}

export function EmbedPreview({ content, embed, botName = "Bot", plain }: {
  content?: string | null; embed?: EmbedData | null; botName?: string; plain?: boolean;
}) {
  const color = embed?.color && /^#?[0-9a-f]{6}$/i.test(embed.color) ? `#${embed.color.replace("#", "")}` : "#ffffff";
  const hasEmbed = embed && !plain && (embed.title || embed.description || embed.fields?.length || embed.imageUrl || embed.authorName);
  return (
    <div className="rounded-lg border border-line bg-[#111] p-4">
      <div className="flex gap-3">
        <div className="size-9 shrink-0 rounded-full bg-surface-3" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-1.5 text-sm">
            <span className="font-medium">{botName}</span>
            <span className="rounded bg-fg px-1 text-[9px] font-semibold uppercase text-bg">Bot</span>
          </div>
          {(content || (plain && embed?.description)) && (
            <div className="whitespace-pre-wrap break-words text-sm leading-relaxed text-fg-2">
              <Markdown text={content || embed?.description || ""} />
            </div>
          )}
          {hasEmbed && (
            <div className="mt-1 grid max-w-[520px] rounded border-l-4 bg-surface-2 p-3" style={{ borderLeftColor: color }}>
              <div className="flex gap-3">
                <div className="min-w-0 flex-1 space-y-1.5">
                  {embed.authorName && (
                    <div className="flex items-center gap-2 text-xs font-medium">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      {embed.authorIconUrl && <img src={embed.authorIconUrl} alt="" className="size-5 rounded-full" />}
                      {embed.authorName}
                    </div>
                  )}
                  {embed.title && <div className="text-sm font-semibold">{embed.title}</div>}
                  {embed.description && <div className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-fg-2"><Markdown text={embed.description} /></div>}
                  {!!embed.fields?.length && (
                    <div className="grid grid-cols-3 gap-2 pt-1">
                      {embed.fields.map((f, i) => (
                        <div key={i} className={f.inline ? "col-span-1" : "col-span-3"}>
                          <div className="text-xs font-semibold">{f.name}</div>
                          <div className="whitespace-pre-wrap text-xs text-fg-2"><Markdown text={f.value} /></div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {embed.thumbnailUrl && <img src={embed.thumbnailUrl} alt="" className="size-16 shrink-0 rounded object-cover" />}
              </div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              {embed.imageUrl && <img src={embed.imageUrl} alt="" className="mt-3 max-h-72 w-full rounded object-cover" />}
              {(embed.footerText || embed.timestamp) && (
                <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {embed.footerIconUrl && <img src={embed.footerIconUrl} alt="" className="size-4 rounded-full" />}
                  {[embed.footerText, embed.timestamp ? "Hoy" : null].filter(Boolean).join(" • ")}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
