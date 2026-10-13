"use client";

import { X } from "lucide-react";
import { useMemo } from "react";
import { CHANNEL, type ChannelInfo, useGuild } from "@/lib/client/guild";
import { Select } from "./form";

export type ChannelKind = "text" | "voice" | "category" | "any";

const KIND_TYPES: Record<ChannelKind, number[]> = {
  text: [CHANNEL.text, CHANNEL.news, CHANNEL.forum],
  voice: [CHANNEL.voice, CHANNEL.stage],
  category: [CHANNEL.category],
  any: [CHANNEL.text, CHANNEL.news, CHANNEL.forum, CHANNEL.voice, CHANNEL.stage, CHANNEL.category],
};
const PREFIX: Record<number, string> = { [CHANNEL.voice]: "🔊 ", [CHANNEL.stage]: "🎙 ", [CHANNEL.category]: "▸ ", [CHANNEL.forum]: "💬 " };

function channelOptions(channels: ChannelInfo[], kind: ChannelKind) {
  const categories = new Map(channels.filter((c) => c.type === CHANNEL.category).map((c) => [c.id, c.name]));
  return channels.filter((c) => KIND_TYPES[kind].includes(c.type)).map((c) => ({
    value: c.id,
    label: `${PREFIX[c.type] ?? "# "}${c.name}`,
    group: kind === "category" ? undefined : (c.parentId ? categories.get(c.parentId) : undefined),
  }));
}

/** Keeps a configured id visible even when the bot is offline or the channel was deleted. */
function withUnknown(options: Array<{ value: string; label: string; group?: string }>, ids: string[]) {
  const known = new Set(options.map((o) => o.value));
  return [...options, ...ids.filter((id) => id && !known.has(id)).map((id) => ({ value: id, label: `Desconocido (${id})` }))];
}

export function ChannelPicker({ value, onChange, kind = "text", placeholder = "Sin canal", id }: {
  value: string | null | undefined; onChange: (value: string | null) => void; kind?: ChannelKind; placeholder?: string; id?: string;
}) {
  const { channels } = useGuild();
  const options = useMemo(() => withUnknown(channelOptions(channels, kind), [value ?? ""]), [channels, kind, value]);
  return <Select id={id} value={value ?? ""} onChange={(v) => onChange(v || null)} options={options} placeholder={placeholder} />;
}

export function RolePicker({ value, onChange, placeholder = "Sin rol", assignableOnly, id }: {
  value: string | null | undefined; onChange: (value: string | null) => void; placeholder?: string; assignableOnly?: boolean; id?: string;
}) {
  const { roles } = useGuild();
  const options = useMemo(() => withUnknown(
    roles.filter((r) => !assignableOnly || r.assignable).map((r) => ({ value: r.id, label: `@${r.name}` })), [value ?? ""],
  ), [roles, assignableOnly, value]);
  return <Select id={id} value={value ?? ""} onChange={(v) => onChange(v || null)} options={options} placeholder={placeholder} />;
}

function MultiPicker({ value, onChange, options, placeholder, render }: {
  value: string[]; onChange: (value: string[]) => void; options: Array<{ value: string; label: string; group?: string }>;
  placeholder: string; render: (id: string) => string;
}) {
  const available = options.filter((o) => !value.includes(o.value));
  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {value.map((id) => (
            <span key={id} className="inline-flex items-center gap-1 rounded-md border border-line-strong bg-surface-3 px-2 py-1 text-xs">
              {render(id)}
              <button type="button" aria-label="Quitar" onClick={() => onChange(value.filter((v) => v !== id))}
                      className="text-muted hover:text-fg"><X size={12} /></button>
            </span>
          ))}
        </div>
      )}
      <Select value="" onChange={(v) => v && onChange([...value, v])} options={available} placeholder={placeholder} />
    </div>
  );
}

export function ChannelMultiPicker({ value, onChange, kind = "text", placeholder = "Añadir canal..." }: {
  value: string[]; onChange: (value: string[]) => void; kind?: ChannelKind; placeholder?: string;
}) {
  const { channels, channelName } = useGuild();
  const options = useMemo(() => channelOptions(channels, kind), [channels, kind]);
  return <MultiPicker value={value} onChange={onChange} options={options} placeholder={placeholder} render={channelName} />;
}

export function RoleMultiPicker({ value, onChange, placeholder = "Añadir rol...", assignableOnly }: {
  value: string[]; onChange: (value: string[]) => void; placeholder?: string; assignableOnly?: boolean;
}) {
  const { roles, roleName } = useGuild();
  const options = useMemo(() => roles.filter((r) => !assignableOnly || r.assignable)
    .map((r) => ({ value: r.id, label: `@${r.name}` })), [roles, assignableOnly]);
  return <MultiPicker value={value} onChange={onChange} options={options} placeholder={placeholder} render={roleName} />;
}
