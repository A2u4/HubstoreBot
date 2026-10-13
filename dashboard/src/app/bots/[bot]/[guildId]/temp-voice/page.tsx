"use client";

import { Mic } from "lucide-react";
import { ConfigEditor, type SectionSpec } from "@/components/config/config-editor";
import { PageHeader } from "@/components/ui/page-header";

const sections: SectionSpec[] = [
  { title: "Voz temporal", fields: [
    { key: "tempVoiceEnabled", type: "toggle", label: "Activar canales temporales",
      description: "Al entrar al canal «hub», el bot crea un canal propio para el miembro y lo borra cuando queda vacío." },
    { key: "tempVoiceHubChannelId", type: "channel", kind: "voice", label: "Canal hub (únete para crear)" },
    { key: "tempVoiceCategoryId", type: "channel", kind: "category", label: "Categoría de los canales", help: "Vacío = la categoría del hub." },
    { key: "tempVoiceNameTemplate", type: "text", label: "Nombre del canal", max: 100, help: "Variables: {user} (apodo), {username}." },
    { key: "tempVoiceUserLimit", type: "number", label: "Límite de usuarios", min: 0, max: 99, help: "0 = sin límite." },
  ] },
];

export default function TempVoicePage() {
  return (
    <>
      <PageHeader title="Voz temporal" description="Los dueños controlan su canal con /voz (nombre, límite, bloquear, expulsar, transferir...)" icon={<Mic size={18} />} />
      <ConfigEditor sections={sections} />
    </>
  );
}
