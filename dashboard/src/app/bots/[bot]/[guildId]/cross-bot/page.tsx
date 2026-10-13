"use client";

import { Network } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { Toggle } from "@/components/ui/form";
import { PageHeader } from "@/components/ui/page-header";
import { useGuild } from "@/lib/client/guild";

function PeerChecklist({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { peers, guildId } = useGuild();
  const others = peers.filter((p) => p.guildId && p.guildId !== guildId);
  if (!others.length) return <p className="text-sm text-muted">No hay otros bots configurados (<span className="kbd">BOT_GUILD_ID</span> en el .env).</p>;
  return (
    <div className="space-y-3">
      {others.map((peer) => (
        <Toggle key={peer.id} label={peer.name} description={`Servidor ${peer.guildId}`} checked={value.includes(peer.guildId!)}
                onChange={(on) => onChange(on ? [...value, peer.guildId!] : value.filter((id) => id !== peer.guildId))} />
      ))}
    </div>
  );
}

const sections: SectionSpec[] = [
  { title: "Bans sincronizados", fields: [
    { key: "banSyncEnabled", type: "toggle", label: "Propagar bans", description: "Cuando un moderador banea aquí, los bots hermanos banean al mismo usuario en sus servidores." },
    { key: "banLogChannelId", type: "channel", label: "Canal de log de bans", help: "Bans locales y sincronizados. Vacío = registro de moderación." },
  ] },
  { title: "Reputación compartida", description: "La reputación de un usuario suma la local más la de los servidores marcados. Para que sea bidireccional, el otro servidor también debe marcar a este.", fields: [
    { key: "repSyncGuildIds", type: "custom", wide: true, render: (value, set) => <PeerChecklist value={(value as string[]) ?? []} onChange={set} /> },
  ] },
];

export default function CrossBotPage() {
  return (
    <>
      <PageHeader title="Sincronizar bots" description="Bans y reputación compartidos entre Vapiano, Hub Store y Trade Zone" icon={<Network size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
