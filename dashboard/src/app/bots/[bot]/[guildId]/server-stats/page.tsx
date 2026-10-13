"use client";

import { BarChart2 } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { ListEditor, newId } from "@/components/config/list-editor";
import { Field, Input, Select } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { ChannelPicker } from "@/components/ui/pickers";

interface StatChannel { id: string; channelId: string; type: string; format: string }

const TYPES = [
  { value: "members", label: "Total de miembros", example: "👥 Miembros: {value}" },
  { value: "humans", label: "Miembros humanos", example: "🧑 Humanos: {value}" },
  { value: "bots", label: "Bots", example: "🤖 Bots: {value}" },
  { value: "online", label: "En línea", example: "🟢 En línea: {value}" },
  { value: "roles", label: "Roles", example: "🏷️ Roles: {value}" },
  { value: "channels", label: "Canales", example: "📢 Canales: {value}" },
  { value: "boosts", label: "Boosts", example: "💎 Boosts: {value}" },
];

const sections: SectionSpec[] = [{
  title: "Canales de estadísticas",
  description: "El bot renombra cada canal de voz con el valor actual (Discord permite 2 cambios de nombre cada 10 minutos por canal).",
  fields: [{
    key: "statsChannels", type: "custom", wide: true,
    render: (value, set) => (
      <ListEditor<StatChannel>
        value={value as StatChannel[]} onChange={set} max={20} addLabel="Añadir contador" empty="No hay contadores."
        create={() => ({ id: newId(), channelId: "", type: "members", format: TYPES[0].example })}
        renderItem={(item, update) => (
          <div className="grid gap-3 md:grid-cols-3">
            <Field label="Canal de voz"><ChannelPicker kind="voice" value={item.channelId} onChange={(v) => update({ channelId: v ?? "" })} /></Field>
            <Field label="Dato"><Select value={item.type} options={TYPES} onChange={(type) => update({
              type, format: item.format.trim() ? item.format : TYPES.find((t) => t.value === type)?.example ?? "{value}" })} /></Field>
            <Field label="Formato" help={`Vista previa: ${item.format.replace("{value}", "1.234")}`}>
              <Input value={item.format} maxLength={200} onChange={(e) => update({ format: e.target.value })} />
            </Field>
          </div>
        )}
      />
    ),
  }],
}];

export default function ServerStatsPage() {
  return (
    <>
      <PageHeader title="Estadísticas" description="Contadores visibles en la lista de canales" icon={<BarChart2 size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
