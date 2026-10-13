"use client";

import { ScrollText } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { PageHeader } from "@/components/ui/page-header";

const sections: SectionSpec[] = [
  { title: "Registros", fields: [
    { key: "loggingEnabled", type: "toggle", label: "Activar registros", description: "Mensajes editados/borrados, cambios de miembros, roles, canales y voz." },
  ] },
  { title: "Canales", description: "Si un canal específico no está definido, el bot usa el de auditoría (y lo crea como #auditoria si hace falta).", fields: [
    { key: "auditLogChannelId", type: "channel", label: "Auditoría (general)" },
    { key: "modLogChannelId", type: "channel", label: "Moderación" },
    { key: "warnLogChannelId", type: "channel", label: "Advertencias" },
    { key: "banLogChannelId", type: "channel", label: "Bans (locales y sincronizados)" },
    { key: "messageLogChannelId", type: "channel", label: "Mensajes editados y borrados" },
    { key: "joinLeaveLogChannelId", type: "channel", label: "Entradas y salidas" },
    { key: "voiceLogChannelId", type: "channel", label: "Voz" },
    { key: "verificationLogChannelId", type: "channel", label: "Verificación" },
  ] },
];

export default function LoggingPage() {
  return (
    <>
      <PageHeader title="Registros" description="Dónde publica el bot cada tipo de evento" icon={<ScrollText size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
